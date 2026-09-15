/*=============================================================================
  02_create_staging_tables.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Create the stg landing tables, one per source CSV.

  Design principles
  -----------------
  1. Every column is nvarchar(4000). Staging accepts the file as written. A bad
     date or a non-numeric quantity lands as text rather than failing the load,
     so ingestion and validation stay separate concerns. Type enforcement is
     05_transform_and_clean.sql's job, where a failure can be diagnosed against
     data that is already in the database.

  2. Columns mirror the CSV exactly - same names, same order. BULK INSERT maps
     fields positionally, so the order is functional, not cosmetic.

  3. No keys, no constraints, no indexes. Staging is a landing strip.

  4. No per-row lineage columns. BULK INSERT cannot populate them without a
     format file per table (verified: Msg 7301 'Cannot obtain the required
     interface IID_IColumnsInfo'). Lineage is recorded per load in stg.LoadLog.

  Tables are dropped and recreated: staging is disposable by definition.
=============================================================================*/

USE SupplyChainBI;
GO
SET NOCOUNT ON;
GO

/*-------------------------------------------------------------- dimensions --*/

DROP TABLE IF EXISTS stg.DimDate;
CREATE TABLE stg.DimDate
(
    [Date]             nvarchar(4000) NULL,
    [Year]             nvarchar(4000) NULL,
    MonthNo            nvarchar(4000) NULL,
    MonthName          nvarchar(4000) NULL,
    [Quarter]          nvarchar(4000) NULL,
    ISOWeek            nvarchar(4000) NULL,
    DayName            nvarchar(4000) NULL,
    FinancialYearStart nvarchar(4000) NULL,
    FinancialYear      nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.DimProduct;
CREATE TABLE stg.DimProduct
(
    ProductID         nvarchar(4000) NULL,
    ProductName       nvarchar(4000) NULL,
    Category          nvarchar(4000) NULL,
    PrimarySupplierID nvarchar(4000) NULL,
    UnitCost          nvarchar(4000) NULL,
    UnitPrice         nvarchar(4000) NULL,
    LeadTimeDays      nvarchar(4000) NULL,
    SafetyStockUnits  nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.DimSupplier;
CREATE TABLE stg.DimSupplier
(
    SupplierID   nvarchar(4000) NULL,
    SupplierName nvarchar(4000) NULL,
    Country      nvarchar(4000) NULL,
    SupplierTier nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.DimWarehouse;
CREATE TABLE stg.DimWarehouse
(
    WarehouseID   nvarchar(4000) NULL,
    WarehouseName nvarchar(4000) NULL,
    Country       nvarchar(4000) NULL
);
GO

/*------------------------------------------------------------------- facts --*/

DROP TABLE IF EXISTS stg.FactSalesOrders;
CREATE TABLE stg.FactSalesOrders
(
    SalesOrderID         nvarchar(4000) NULL,
    OrderDate            nvarchar(4000) NULL,
    ProductID            nvarchar(4000) NULL,
    WarehouseID          nvarchar(4000) NULL,
    Quantity             nvarchar(4000) NULL,
    Revenue              nvarchar(4000) NULL,
    PromisedDeliveryDate nvarchar(4000) NULL,
    ActualDeliveryDate   nvarchar(4000) NULL,   -- ambiguous in source: see script 05
    OrderStatus          nvarchar(4000) NULL,
    Channel              nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.FactPurchaseOrders;
CREATE TABLE stg.FactPurchaseOrders
(
    PurchaseOrderID     nvarchar(4000) NULL,
    OrderDate           nvarchar(4000) NULL,
    SupplierID          nvarchar(4000) NULL,
    ProductID           nvarchar(4000) NULL,
    WarehouseID         nvarchar(4000) NULL,
    QuantityOrdered     nvarchar(4000) NULL,
    POValue             nvarchar(4000) NULL,
    ExpectedReceiptDate nvarchar(4000) NULL,
    ActualReceiptDate   nvarchar(4000) NULL,    -- ambiguous in source: see script 05
    DefectRate          nvarchar(4000) NULL,
    [Status]            nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.FactShipments;
CREATE TABLE stg.FactShipments
(
    ShipmentID     nvarchar(4000) NULL,
    SalesOrderID   nvarchar(4000) NULL,
    WarehouseID    nvarchar(4000) NULL,
    Carrier        nvarchar(4000) NULL,
    ShipDate       nvarchar(4000) NULL,
    DeliveryDate   nvarchar(4000) NULL,
    FreightCost    nvarchar(4000) NULL,
    DeliveryStatus nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.FactWeeklyDemand;
CREATE TABLE stg.FactWeeklyDemand
(
    WeekStart             nvarchar(4000) NULL,
    ProductID             nvarchar(4000) NULL,
    WarehouseID           nvarchar(4000) NULL,
    ActualDemandUnits     nvarchar(4000) NULL,
    BaselineForecastUnits nvarchar(4000) NULL
);
GO

DROP TABLE IF EXISTS stg.FactInventorySnapshot;
CREATE TABLE stg.FactInventorySnapshot
(
    SnapshotDate   nvarchar(4000) NULL,
    ProductID      nvarchar(4000) NULL,
    WarehouseID    nvarchar(4000) NULL,
    OnHandUnits    nvarchar(4000) NULL,
    InventoryValue nvarchar(4000) NULL,   -- retained in stg for reconciliation only
    InboundUnits   nvarchar(4000) NULL
);
GO

/*---------------------------------------------------------------- security --*/

DROP TABLE IF EXISTS stg.SecurityUserAccess;
CREATE TABLE stg.SecurityUserAccess
(
    UserEmail   nvarchar(4000) NULL,
    [Role]      nvarchar(4000) NULL,
    WarehouseID nvarchar(4000) NULL   -- may hold the literal sentinel 'ALL'
);
GO

/*----------------------------------------------------------- confirmation --*/

SELECT
    TableName   = QUOTENAME(s.name) + '.' + QUOTENAME(t.name),
    ColumnCount = COUNT(c.column_id)
FROM      sys.tables   AS t
JOIN      sys.schemas  AS s ON s.schema_id = t.schema_id
JOIN      sys.columns  AS c ON c.object_id = t.object_id
WHERE     s.name = 'stg'
  AND     t.name <> 'LoadLog'
GROUP BY  s.name, t.name
ORDER BY  t.name;
GO
