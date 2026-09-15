/*=============================================================================
  04_create_core_tables.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Create the typed, keyed dbo core tables.

  Typing policy
  -------------
    Identifiers   varchar, right-sized. The data is ASCII, so varchar halves
                  storage against nvarchar with no loss.
    Descriptions  nvarchar. Names and free text may legitimately carry unicode.
    Dates         date. No time component exists anywhere in the source.
    Money         decimal(18,2). The conventional financial type; float is never
                  used for currency because binary rounding makes totals
                  irreproducible.
    Rates         decimal(9,6). DefectRate is a proportion in [0,1] carrying
                  four decimals; this types it tightly rather than as money.
    Counts        int.

  Key policy
  ----------
  PRIMARY KEYs are declared inline. Phase 2 proved every one of these grains is
  unique, so declaring them here makes the transformation in script 05 fail
  loudly and immediately if that ever stops being true. FOREIGN KEYs are
  deferred to script 07 because they require every parent row to be present
  first.

  Ambiguous source dates
  ----------------------
  The source stores one column that means two different things: for a completed
  record it is the actual date; for an open record it is a future expectation.
  Each is split here into two single-meaning columns, populated in script 05:

      ActualDeliveryDate    / ActualReceiptDate      NULL unless completed
      ScheduledDeliveryDate / ScheduledReceiptDate   NULL unless still open

  The two are mutually exclusive, so COALESCE(Actual, Scheduled) yields the
  best known date for any record without either column ever being ambiguous.

  Idempotent: safe to re-run.
=============================================================================*/

USE SupplyChainBI;
GO
SET NOCOUNT ON;
GO

/*-----------------------------------------------------------------------------
  Drop in dependency order (children before parents)
-----------------------------------------------------------------------------*/
DROP TABLE IF EXISTS dbo.FactShipments;
DROP TABLE IF EXISTS dbo.FactSalesOrders;
DROP TABLE IF EXISTS dbo.FactPurchaseOrders;
DROP TABLE IF EXISTS dbo.FactWeeklyDemand;
DROP TABLE IF EXISTS dbo.FactInventorySnapshot;
DROP TABLE IF EXISTS dbo.SecurityUserAccess;
DROP TABLE IF EXISTS dbo.DimProduct;
DROP TABLE IF EXISTS dbo.DimSupplier;
DROP TABLE IF EXISTS dbo.DimWarehouse;
DROP TABLE IF EXISTS dbo.DimDate;
GO

/*=============================================================================
  DIMENSIONS
=============================================================================*/

/*-----------------------------------------------------------------------------
  DimDate
  ---------------------------------------------------------------------------
  Generated in script 05, not loaded from source. The supplied calendar stops
  at 2026-08-31 while facts reach 2026-10-07, so importing it would leave 1,938
  fact rows unable to join. Generating it also lets us add the sort keys and
  week-start column the semantic model needs.

  [Date] is the primary key and the column facts relate to. An integer
  surrogate (DateKey) is carried for SQL-side sorting and for anyone joining
  this warehouse directly, but relationships use the date itself: VertiPaq
  stores dates as integers internally, so an int key would buy no measurable
  performance at this scale while adding a column to every fact.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.DimDate
(
    [Date]               date         NOT NULL,
    DateKey              int          NOT NULL,  -- yyyymmdd
    [Year]               smallint     NOT NULL,
    [Quarter]            tinyint      NOT NULL,
    QuarterLabel         varchar(2)   NOT NULL,  -- Q3
    YearQuarterKey       int          NOT NULL,  -- 20263, sorts YearQuarterLabel
    YearQuarterLabel     varchar(7)   NOT NULL,  -- 2026 Q3
    MonthNumber          tinyint      NOT NULL,
    MonthName            varchar(20)  NOT NULL,
    MonthShortName       varchar(3)   NOT NULL,
    YearMonthKey         int          NOT NULL,  -- 202608, sorts YearMonthLabel
    YearMonthLabel       varchar(8)   NOT NULL,  -- Aug 2026
    ISOYear              smallint     NOT NULL,
    ISOWeek              tinyint      NOT NULL,
    ISOYearWeekKey       int          NOT NULL,  -- 202636, sorts the label
    ISOYearWeekLabel     varchar(8)   NOT NULL,  -- 2026-W36
    WeekStartDate        date         NOT NULL,  -- Monday; joins the weekly facts
    WeekEndDate          date         NOT NULL,  -- Sunday
    DayOfMonth           tinyint      NOT NULL,
    DayOfWeekISO         tinyint      NOT NULL,  -- 1 = Monday
    DayName              varchar(20)  NOT NULL,
    DayShortName         varchar(3)   NOT NULL,
    IsWeekend            bit          NOT NULL,
    FinancialYearNumber  smallint     NOT NULL,  -- 2027
    FinancialYear        varchar(4)   NOT NULL,  -- FY27
    FinancialQuarter     tinyint      NOT NULL,
    FinancialMonthNumber tinyint      NOT NULL,  -- 1 = July
    IsOnOrBeforeAsOfDate bit          NOT NULL,  -- against ModelConfig AsOfDate
    CONSTRAINT PK_DimDate PRIMARY KEY CLUSTERED ([Date])
);
GO

/*-----------------------------------------------------------------------------
  DimProduct
  ---------------------------------------------------------------------------
  HasDemandSignal is derived, not sourced. Only 500 of the 1,000 products carry
  inventory and demand history, so every inventory, reorder and stockout
  measure is blank for the other half. The flag makes that visible and
  filterable instead of leaving users to wonder why a product shows no stock.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.DimProduct
(
    ProductID         varchar(10)   NOT NULL,
    ProductName       nvarchar(100) NOT NULL,
    Category          nvarchar(50)  NOT NULL,
    PrimarySupplierID varchar(10)   NOT NULL,
    UnitCost          decimal(18,2) NOT NULL,
    UnitPrice         decimal(18,2) NOT NULL,
    LeadTimeDays      int           NOT NULL,   -- planning lead time
    SafetyStockUnits  int           NOT NULL,   -- supplied safety stock
    HasDemandSignal   bit           NOT NULL,   -- derived; see script 05
    CONSTRAINT PK_DimProduct PRIMARY KEY CLUSTERED (ProductID)
);
GO

CREATE TABLE dbo.DimSupplier
(
    SupplierID   varchar(10)   NOT NULL,
    SupplierName nvarchar(100) NOT NULL,
    Country      nvarchar(50)  NOT NULL,
    SupplierTier nvarchar(20)  NOT NULL,
    CONSTRAINT PK_DimSupplier PRIMARY KEY CLUSTERED (SupplierID)
);
GO

/*-----------------------------------------------------------------------------
  DimWarehouse
  ---------------------------------------------------------------------------
  Region is a derived geographic grouping over the four source countries, added
  to support the Region -> Warehouse -> Category -> SKU drill path. It is
  documented as derived because it does not exist in the source file.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.DimWarehouse
(
    WarehouseID   varchar(10)   NOT NULL,
    WarehouseName nvarchar(100) NOT NULL,
    Country       nvarchar(50)  NOT NULL,
    Region        nvarchar(50)  NOT NULL,   -- derived; see script 05
    CONSTRAINT PK_DimWarehouse PRIMARY KEY CLUSTERED (WarehouseID)
);
GO

/*=============================================================================
  FACTS
=============================================================================*/

/*-----------------------------------------------------------------------------
  FactSalesOrders
  ---------------------------------------------------------------------------
  Grain: one row per sales order. Verified unique on SalesOrderID.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.FactSalesOrders
(
    SalesOrderID          varchar(20)   NOT NULL,
    OrderDate             date          NOT NULL,
    ProductID             varchar(10)   NOT NULL,
    WarehouseID           varchar(10)   NOT NULL,
    Quantity              int           NOT NULL,
    Revenue               decimal(18,2) NOT NULL,
    PromisedDeliveryDate  date          NOT NULL,  -- the commitment
    ActualDeliveryDate    date          NULL,      -- NULL while open
    ScheduledDeliveryDate date          NULL,      -- NULL once delivered
    OrderStatus           varchar(20)   NOT NULL,
    Channel               nvarchar(20)  NOT NULL,
    IsDelivered           bit           NOT NULL,
    IsOpenOrder           bit           NOT NULL,
    DeliveryDelayDays     int           NULL,      -- NULL while open
    CONSTRAINT PK_FactSalesOrders PRIMARY KEY CLUSTERED (SalesOrderID)
);
GO

/*-----------------------------------------------------------------------------
  FactPurchaseOrders
  ---------------------------------------------------------------------------
  Grain: one row per purchase order. Verified unique on PurchaseOrderID.

  PurchasePriceVariance is retained because POValue is genuinely NOT derivable
  from QuantityOrdered x UnitCost - it deviates on 24,998 of 25,000 rows. That
  deviation is real purchase price variance and is the basis of the Purchase
  Price Performance metric required of the supplier scorecard.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.FactPurchaseOrders
(
    PurchaseOrderID      varchar(20)   NOT NULL,
    OrderDate            date          NOT NULL,
    SupplierID           varchar(10)   NOT NULL,
    ProductID            varchar(10)   NOT NULL,
    WarehouseID          varchar(10)   NOT NULL,
    QuantityOrdered      int           NOT NULL,
    POValue              decimal(18,2) NOT NULL,
    ExpectedReceiptDate  date          NOT NULL,  -- the commitment
    ActualReceiptDate    date          NULL,      -- NULL while open
    ScheduledReceiptDate date          NULL,      -- NULL once received
    DefectRate           decimal(9,6)  NOT NULL,
    [Status]             varchar(20)   NOT NULL,
    IsReceived           bit           NOT NULL,
    IsOpenPO             bit           NOT NULL,
    ActualLeadTimeDays   int           NULL,      -- receipt minus order
    ReceiptDelayDays     int           NULL,      -- actual minus expected
    CONSTRAINT PK_FactPurchaseOrders PRIMARY KEY CLUSTERED (PurchaseOrderID)
);
GO

/*-----------------------------------------------------------------------------
  FactShipments
  ---------------------------------------------------------------------------
  Grain: one row per shipment. Verified unique on ShipmentID, and 1:1 with
  sales orders in this dataset (80,000 distinct SalesOrderID in each).

  Kept as a separate fact rather than merged into FactSalesOrders. A shipment
  is genuinely its own grain - real distribution splits an order across several
  shipments - and the 1:1 here is a property of this dataset, not of the
  business process. Merging would encode a coincidence into the schema.

  WarehouseID is retained despite agreeing with the sales order on all 80,000
  rows, because it lets DimWarehouse relate directly to shipments rather than
  filtering through the order fact.

  ProductID is deliberately NOT stored here. It is resolved in
  analytics.vw_Shipments through SalesOrderID.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.FactShipments
(
    ShipmentID            varchar(20)   NOT NULL,
    SalesOrderID          varchar(20)   NOT NULL,
    WarehouseID           varchar(10)   NOT NULL,
    Carrier               nvarchar(50)  NOT NULL,
    ShipDate              date          NOT NULL,
    ActualDeliveryDate    date          NULL,      -- NULL while in transit
    ScheduledDeliveryDate date          NULL,      -- NULL once delivered
    FreightCost           decimal(18,2) NOT NULL,
    DeliveryStatus        varchar(20)   NOT NULL,  -- source flag, kept to
                                                   -- reconcile against derived OTIF
    IsShipped             bit           NOT NULL,
    IsDelivered           bit           NOT NULL,
    TransitDays           int           NULL,      -- delivery minus ship
    CONSTRAINT PK_FactShipments PRIMARY KEY CLUSTERED (ShipmentID)
);
GO

/*-----------------------------------------------------------------------------
  FactWeeklyDemand
  ---------------------------------------------------------------------------
  Grain: WeekStart + ProductID + WarehouseID. Verified unique, and a complete
  dense grid of 105 weeks x 500 products x 6 warehouses = 315,000 rows.

  Left exactly as supplied. No smoothing, no gap-filling, no outlier treatment.
  BaselineForecastUnits is the locked benchmark the Phase 14 model must beat,
  so altering this table would invalidate the comparison.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.FactWeeklyDemand
(
    WeekStart             date        NOT NULL,
    ProductID             varchar(10) NOT NULL,
    WarehouseID           varchar(10) NOT NULL,
    ActualDemandUnits     int         NOT NULL,
    BaselineForecastUnits int         NOT NULL,
    CONSTRAINT PK_FactWeeklyDemand
        PRIMARY KEY CLUSTERED (WeekStart, ProductID, WarehouseID)
);
GO

/*-----------------------------------------------------------------------------
  FactInventorySnapshot
  ---------------------------------------------------------------------------
  Grain: SnapshotDate + ProductID + WarehouseID. Verified unique, complete
  dense grid of 315,000 rows.

  A SEMI-ADDITIVE fact. On-hand units may be summed across products and
  warehouses but never across time: adding 105 weekly balances would report a
  figure that never existed. The semantic model must select a single snapshot
  date within filter context.

  InventoryValue is NOT stored here. It reconciled to OnHandUnits x UnitCost on
  315,000 of 315,000 rows with zero deviation, so it is fully derivable from
  DimProduct. Storing it would add a 237,846-distinct-value column that
  compresses poorly in VertiPaq to hold information the model already has. The
  raw value is preserved in stg.FactInventorySnapshot and is reconciled in
  script 08.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.FactInventorySnapshot
(
    SnapshotDate date        NOT NULL,
    ProductID    varchar(10) NOT NULL,
    WarehouseID  varchar(10) NOT NULL,
    OnHandUnits  int         NOT NULL,
    InboundUnits int         NOT NULL,
    CONSTRAINT PK_FactInventorySnapshot
        PRIMARY KEY CLUSTERED (SnapshotDate, ProductID, WarehouseID)
);
GO

/*-----------------------------------------------------------------------------
  SecurityUserAccess
  ---------------------------------------------------------------------------
  Source for dynamic row-level security. The Supply Director row carries the
  literal sentinel 'ALL' rather than a warehouse code, so IsAllWarehouses is
  derived to make the RLS predicate explicit rather than string-matching a
  magic value inside DAX.

  No RLS logic is implemented here - that belongs to the semantic model.
-----------------------------------------------------------------------------*/
CREATE TABLE dbo.SecurityUserAccess
(
    UserEmail        nvarchar(200) NOT NULL,
    [Role]           nvarchar(50)  NOT NULL,
    WarehouseID      varchar(10)   NOT NULL,   -- may be the sentinel 'ALL'
    IsAllWarehouses  bit           NOT NULL,   -- derived; see script 05
    CONSTRAINT PK_SecurityUserAccess PRIMARY KEY CLUSTERED (UserEmail, WarehouseID)
);
GO

/*----------------------------------------------------------- confirmation --*/
SELECT
    TableName   = QUOTENAME(s.name) + '.' + QUOTENAME(t.name),
    ColumnCount = (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id = t.object_id),
    PrimaryKey  = k.name
FROM      sys.tables  AS t
JOIN      sys.schemas AS s ON s.schema_id = t.schema_id
LEFT JOIN sys.key_constraints AS k
       ON k.parent_object_id = t.object_id AND k.type = 'PK'
WHERE     s.name = 'dbo'
  AND     t.name <> 'ModelConfig'
ORDER BY  t.name;
GO
