/*=============================================================================
  06_create_views.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Create the analytics views - the ONLY objects Power BI consumes.

  Why a view layer at all
  -----------------------
  It decouples the report from the tables. A column can be renamed, retyped or
  restructured in dbo and absorbed by editing one view, without the semantic
  model or any report page noticing. Pointing Power BI at dbo directly would
  make every physical change a breaking change.

  Design rules
  ------------
  1. One view per table. No wide denormalised reporting view: the semantic
     model needs a star schema, and flattening here would destroy it.
  2. Thin and foldable. Simple projections, no window functions, no scalar
     UDFs, no CASE over large row sets. Power Query must be able to push
     filters - especially the RangeStart/RangeEnd predicates that incremental
     refresh will add later - straight through to the engine.
  3. No KPIs. OTIF, turnover, ABC, XYZ, supplier scores and forecast accuracy
     all respond to filter context and belong in DAX. Only stable row-level
     business state is exposed here.
  4. No SELECT *. Columns are listed so that adding a column to a table cannot
     silently change the contract.

  Idempotent: CREATE OR ALTER.
=============================================================================*/

USE SupplyChainBI;
GO

/*=============================================================================
  Configuration
  ---------------------------------------------------------------------------
  Exposed so the semantic model can read the as-of date rather than hard-coding
  it in DAX. Six rows; it imports at no cost and keeps one definition of the
  anchor date across SQL, Python and Power BI.
=============================================================================*/
CREATE OR ALTER VIEW analytics.vw_ModelConfig
AS
SELECT
    ConfigKey,
    ConfigValue,
    [Description]
FROM dbo.ModelConfig;
GO

/*=============================================================================
  DIMENSIONS
=============================================================================*/

CREATE OR ALTER VIEW analytics.vw_DimDate
AS
SELECT
    [Date],
    DateKey,
    [Year],
    [Quarter],
    QuarterLabel,
    YearQuarterKey,
    YearQuarterLabel,
    MonthNumber,
    MonthName,
    MonthShortName,
    YearMonthKey,
    YearMonthLabel,
    ISOYear,
    ISOWeek,
    ISOYearWeekKey,
    ISOYearWeekLabel,
    WeekStartDate,
    WeekEndDate,
    DayOfMonth,
    DayOfWeekISO,
    DayName,
    DayShortName,
    IsWeekend,
    FinancialYearNumber,
    FinancialYear,
    FinancialQuarter,
    FinancialMonthNumber,
    IsOnOrBeforeAsOfDate
FROM dbo.DimDate;
GO

CREATE OR ALTER VIEW analytics.vw_DimProduct
AS
SELECT
    ProductID,
    ProductName,
    Category,
    PrimarySupplierID,   -- relates DimProduct to DimSupplier
    UnitCost,            -- also the basis for deriving inventory value in DAX
    UnitPrice,
    LeadTimeDays,        -- PLANNING lead time; not supplier actuals
    SafetyStockUnits,
    HasDemandSignal      -- 0 for the 500 products with no inventory or demand
FROM dbo.DimProduct;
GO

CREATE OR ALTER VIEW analytics.vw_DimSupplier
AS
SELECT
    SupplierID,
    SupplierName,
    Country,
    SupplierTier
FROM dbo.DimSupplier;
GO

CREATE OR ALTER VIEW analytics.vw_DimWarehouse
AS
SELECT
    WarehouseID,
    WarehouseName,
    Country,
    Region               -- derived grouping; supports Region -> Warehouse drill
FROM dbo.DimWarehouse;
GO

/*=============================================================================
  FACTS
=============================================================================*/

/*-----------------------------------------------------------------------------
  vw_SalesOrders
  ---------------------------------------------------------------------------
  OrderDate is the intended incremental-refresh partition column: it is a plain
  date on the base table with no expression wrapped around it, so a
  RangeStart/RangeEnd predicate folds to a clean sargable WHERE clause.
-----------------------------------------------------------------------------*/
CREATE OR ALTER VIEW analytics.vw_SalesOrders
AS
SELECT
    SalesOrderID,
    OrderDate,
    ProductID,
    WarehouseID,
    Quantity,
    Revenue,
    PromisedDeliveryDate,
    ActualDeliveryDate,      -- NULL while the order is open
    ScheduledDeliveryDate,   -- NULL once the order is delivered
    OrderStatus,
    Channel,
    IsDelivered,
    IsOpenOrder,             -- exclude these from OTIF: not yet due
    DeliveryDelayDays        -- NULL while open; positive means late
FROM dbo.FactSalesOrders;
GO

/*-----------------------------------------------------------------------------
  vw_PurchaseOrders
  ---------------------------------------------------------------------------
  PurchasePriceVariance is exposed because POValue genuinely diverges from
  QuantityOrdered x UnitCost on 24,998 of 25,000 rows. That divergence is real
  purchase price variance and underpins the Purchase Price Performance metric.
  It is arithmetic on the current row - not an aggregate - so it neither breaks
  folding nor pre-empts a DAX measure.
-----------------------------------------------------------------------------*/
CREATE OR ALTER VIEW analytics.vw_PurchaseOrders
AS
SELECT
    po.PurchaseOrderID,
    po.OrderDate,
    po.SupplierID,
    po.ProductID,
    po.WarehouseID,
    po.QuantityOrdered,
    po.POValue,
    po.ExpectedReceiptDate,
    po.ActualReceiptDate,       -- NULL while the PO is open
    po.ScheduledReceiptDate,    -- NULL once the PO is received
    po.DefectRate,
    po.[Status],
    po.IsReceived,
    po.IsOpenPO,                -- exclude these from supplier OTIF
    po.ActualLeadTimeDays,      -- supplier performance: order to receipt
    po.ReceiptDelayDays,        -- positive means received after the promise
    ExpectedPOValue       = CAST(po.QuantityOrdered * p.UnitCost AS decimal(18,2)),
    PurchasePriceVariance = CAST(po.POValue - (po.QuantityOrdered * p.UnitCost) AS decimal(18,2))
FROM      dbo.FactPurchaseOrders AS po
JOIN      dbo.DimProduct         AS p ON p.ProductID = po.ProductID;
GO

/*-----------------------------------------------------------------------------
  vw_Shipments
  ---------------------------------------------------------------------------
  Resolves the missing ProductID.

  FactShipments carries no ProductID, yet the brief requires OTIF and freight
  analysis by product and category. Three options were weighed:

    a) Bidirectional filtering DimProduct -> FactSalesOrders -> FactShipments.
       Rejected: ambiguous filter paths and a documented anti-pattern.
    b) Storing ProductID physically on dbo.FactShipments.
       Rejected: duplicates data the relational model already holds, and would
       drift if an order were ever re-pointed at a different product.
    c) Resolving it here, in the view. CHOSEN.

  Option (c) keeps dbo normalised while presenting Power BI a clean star: a
  direct DimProduct -> FactShipments relationship with single-direction
  filtering and no ambiguity.

  INNER JOIN is safe. Script 07 declares FK_FactShipments_SalesOrder, so the
  engine guarantees every shipment has a parent order and the join cannot drop
  a row. Script 08 verifies the count regardless.

  PromisedDeliveryDate is carried across because carrier on-time performance
  cannot be measured without the commitment, and the shipment fact has no
  promise date of its own.
-----------------------------------------------------------------------------*/
CREATE OR ALTER VIEW analytics.vw_Shipments
AS
SELECT
    sh.ShipmentID,
    sh.SalesOrderID,
    so.ProductID,                          -- resolved through the sales order
    sh.WarehouseID,
    sh.Carrier,
    sh.ShipDate,
    so.PromisedDeliveryDate,               -- the commitment being measured
    sh.ActualDeliveryDate,                 -- NULL while in transit
    sh.ScheduledDeliveryDate,              -- NULL once delivered
    sh.FreightCost,
    sh.DeliveryStatus,                     -- source flag, for reconciliation only
    sh.IsShipped,
    sh.IsDelivered,                        -- exclude 0 from delivery OTIF
    sh.TransitDays,
    so.OrderDate
FROM      dbo.FactShipments   AS sh
JOIN      dbo.FactSalesOrders AS so ON so.SalesOrderID = sh.SalesOrderID;
GO

/*-----------------------------------------------------------------------------
  vw_WeeklyDemand
  ---------------------------------------------------------------------------
  Passed through untouched. BaselineForecastUnits is the locked Phase 14
  benchmark; altering it here would invalidate the model comparison.

  WeekStart is a Monday on every row and is a candidate incremental-refresh
  partition column.
-----------------------------------------------------------------------------*/
CREATE OR ALTER VIEW analytics.vw_WeeklyDemand
AS
SELECT
    WeekStart,
    ProductID,
    WarehouseID,
    ActualDemandUnits,
    BaselineForecastUnits
FROM dbo.FactWeeklyDemand;
GO

/*-----------------------------------------------------------------------------
  vw_InventorySnapshot
  ---------------------------------------------------------------------------
  SEMI-ADDITIVE. On-hand units may be summed across products and warehouses but
  never across time. The semantic model must resolve a single snapshot date
  within filter context; summing 105 weekly balances would report a stock
  position that never existed.

  InventoryValue is deliberately absent. It equals OnHandUnits x UnitCost on
  all 315,000 rows with zero deviation, so DAX can derive it from DimProduct.
  Joining DimProduct here to recreate it would add a join to a 315,000-row view
  and hand VertiPaq a 237,846-distinct-value column to compress, in exchange
  for information the model already holds.
-----------------------------------------------------------------------------*/
CREATE OR ALTER VIEW analytics.vw_InventorySnapshot
AS
SELECT
    SnapshotDate,
    ProductID,
    WarehouseID,
    OnHandUnits,
    InboundUnits
FROM dbo.FactInventorySnapshot;
GO

/*-----------------------------------------------------------------------------
  vw_SecurityUserAccess
  ---------------------------------------------------------------------------
  Source for dynamic RLS. Email is already lower-cased so the DAX predicate can
  compare against USERPRINCIPALNAME() without case handling.

  No security logic is applied here. This view is data, not policy - it must
  return every mapping row so the semantic model can filter on it.
-----------------------------------------------------------------------------*/
CREATE OR ALTER VIEW analytics.vw_SecurityUserAccess
AS
SELECT
    UserEmail,
    [Role],
    WarehouseID,        -- may be the sentinel 'ALL'
    IsAllWarehouses
FROM dbo.SecurityUserAccess;
GO

/*----------------------------------------------------------- confirmation --*/
SELECT
    ViewName    = QUOTENAME(s.name) + '.' + QUOTENAME(v.name),
    ColumnCount = (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id = v.object_id)
FROM      sys.views   AS v
JOIN      sys.schemas AS s ON s.schema_id = v.schema_id
WHERE     s.name = 'analytics'
ORDER BY  v.name;
GO
