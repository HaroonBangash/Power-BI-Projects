/*=============================================================================
  05_transform_and_clean.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Type, clean and load stg -> dbo, generate the calendar, and resolve
            the ambiguous source date columns into single-meaning columns.

  Conversion policy
  -----------------
  TRY_CONVERT is used throughout rather than CAST. A malformed value becomes
  NULL, and because the target columns are NOT NULL the insert then fails
  loudly on the specific row rather than silently truncating or rounding.
  Phase 2 proved every value in the source is well formed, so this is a
  safety net rather than an expected path.

  The as-of date
  --------------
  Read once from dbo.ModelConfig into @AsOfDate and used for every completion
  test. GETDATE() is deliberately never referenced: today is already later than
  the extract, so a system-date rule would reclassify in-flight orders as
  overdue and drift further every day the report is opened.

  Idempotent: dbo tables are emptied in dependency order first, so this script
  may be re-run without duplicating rows or violating foreign keys.
=============================================================================*/

USE SupplyChainBI;
GO
SET NOCOUNT ON;
GO

/*-----------------------------------------------------------------------------
  Clear dbo in dependency order (children before parents).
  DELETE rather than TRUNCATE so the script still works once script 07 has
  added the foreign keys.
-----------------------------------------------------------------------------*/
DELETE FROM dbo.FactShipments;
DELETE FROM dbo.FactSalesOrders;
DELETE FROM dbo.FactPurchaseOrders;
DELETE FROM dbo.FactWeeklyDemand;
DELETE FROM dbo.FactInventorySnapshot;
DELETE FROM dbo.SecurityUserAccess;
DELETE FROM dbo.DimProduct;
DELETE FROM dbo.DimSupplier;
DELETE FROM dbo.DimWarehouse;
DELETE FROM dbo.DimDate;
GO

/*=============================================================================
  1. DimDate  -  generated, not imported
  ---------------------------------------------------------------------------
  Built from a tally rather than a recursive CTE: set-based, no recursion
  limit, and it scales unchanged if the horizon is extended.

  ISO handling is DATEFIRST-independent. 1900-01-01 was a Monday, so
      (DATEDIFF(day, '1900-01-01', d) % 7) + 1
  yields 1 for Monday through 7 for Sunday regardless of session settings -
  which a DATEPART(weekday, ...) expression would not.

  The ISO year is the year of the Thursday falling in the same ISO week, which
  is what makes the last days of December belong to the following ISO year.

  Financial year runs July to June, matching the FinancialYear column in the
  supplied source calendar: July 2026 to June 2027 is FY27.
=============================================================================*/

DECLARE @CalStart date, @CalEnd date, @AsOfDate date;

SELECT @CalStart = TRY_CONVERT(date, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = 'CalendarStartDate';
SELECT @CalEnd   = TRY_CONVERT(date, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = 'CalendarEndDate';
SELECT @AsOfDate = TRY_CONVERT(date, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate';

;WITH n(n) AS
(
    SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL
    SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL SELECT 0 UNION ALL
    SELECT 0 UNION ALL SELECT 0
),
tally AS   -- 10^4 = 10,000 rows, ample for a 5.5-year calendar
(
    SELECT TOP (DATEDIFF(day, @CalStart, @CalEnd) + 1)
           Offset = ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1
    FROM   n AS a CROSS JOIN n AS b CROSS JOIN n AS c CROSS JOIN n AS d
),
dates AS
(
    SELECT d = DATEADD(day, Offset, @CalStart) FROM tally
),
iso AS
(
    SELECT
        d,
        -- 1 = Monday .. 7 = Sunday, independent of @@DATEFIRST
        WeekdayISO = (DATEDIFF(day, '1900-01-01', d) % 7) + 1
    FROM dates
),
calc AS
(
    SELECT
        d,
        WeekdayISO,
        WeekStartDate = DATEADD(day, 1 - WeekdayISO, d),
        WeekEndDate   = DATEADD(day, 7 - WeekdayISO, d),
        ISOWeek       = DATEPART(ISO_WEEK, d),
        -- The ISO year is the calendar year of that week's Thursday.
        ISOYear       = YEAR(DATEADD(day, 4 - WeekdayISO, d)),
        MonthNumber   = MONTH(d),
        [Year]        = YEAR(d)
    FROM iso
)
INSERT INTO dbo.DimDate
(
    [Date], DateKey, [Year], [Quarter], QuarterLabel, YearQuarterKey, YearQuarterLabel,
    MonthNumber, MonthName, MonthShortName, YearMonthKey, YearMonthLabel,
    ISOYear, ISOWeek, ISOYearWeekKey, ISOYearWeekLabel, WeekStartDate, WeekEndDate,
    DayOfMonth, DayOfWeekISO, DayName, DayShortName, IsWeekend,
    FinancialYearNumber, FinancialYear, FinancialQuarter, FinancialMonthNumber,
    IsOnOrBeforeAsOfDate
)
SELECT
    [Date]            = d,
    DateKey           = ([Year] * 10000) + (MonthNumber * 100) + DAY(d),
    [Year]            = [Year],
    [Quarter]         = DATEPART(quarter, d),
    QuarterLabel      = CONCAT('Q', DATEPART(quarter, d)),
    YearQuarterKey    = ([Year] * 10) + DATEPART(quarter, d),
    YearQuarterLabel  = CONCAT([Year], ' Q', DATEPART(quarter, d)),
    MonthNumber       = MonthNumber,
    MonthName         = DATENAME(month, d),
    MonthShortName    = LEFT(DATENAME(month, d), 3),
    YearMonthKey      = ([Year] * 100) + MonthNumber,
    YearMonthLabel    = CONCAT(LEFT(DATENAME(month, d), 3), ' ', [Year]),
    ISOYear           = ISOYear,
    ISOWeek           = ISOWeek,
    ISOYearWeekKey    = (ISOYear * 100) + ISOWeek,
    ISOYearWeekLabel  = CONCAT(ISOYear, '-W', RIGHT(CONCAT('0', ISOWeek), 2)),
    WeekStartDate     = WeekStartDate,
    WeekEndDate       = WeekEndDate,
    DayOfMonth        = DAY(d),
    DayOfWeekISO      = WeekdayISO,
    DayName           = DATENAME(weekday, d),
    DayShortName      = LEFT(DATENAME(weekday, d), 3),
    IsWeekend         = CASE WHEN WeekdayISO >= 6 THEN 1 ELSE 0 END,
    -- July onwards belongs to the next financial year.
    FinancialYearNumber  = [Year] + CASE WHEN MonthNumber >= 7 THEN 1 ELSE 0 END,
    FinancialYear        = CONCAT('FY', RIGHT(CAST([Year] + CASE WHEN MonthNumber >= 7 THEN 1 ELSE 0 END AS varchar(4)), 2)),
    FinancialQuarter     = (((MonthNumber - 7 + 12) % 12) / 3) + 1,
    FinancialMonthNumber = ((MonthNumber - 7 + 12) % 12) + 1,
    IsOnOrBeforeAsOfDate = CASE WHEN d <= @AsOfDate THEN 1 ELSE 0 END
FROM calc
OPTION (MAXRECURSION 0);

PRINT CONCAT('DimDate generated: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  2. DimSupplier
=============================================================================*/
INSERT INTO dbo.DimSupplier (SupplierID, SupplierName, Country, SupplierTier)
SELECT
    SupplierID   = LTRIM(RTRIM(SupplierID)),
    SupplierName = LTRIM(RTRIM(SupplierName)),
    Country      = LTRIM(RTRIM(Country)),
    SupplierTier = LTRIM(RTRIM(SupplierTier))
FROM stg.DimSupplier;

PRINT CONCAT('DimSupplier loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  3. DimWarehouse
  ---------------------------------------------------------------------------
  Region is DERIVED, not sourced. It groups the four source countries so the
  report can offer a Region -> Warehouse -> Category -> SKU drill path. The
  ELSE branch keeps any future country visible rather than silently dropping it.
=============================================================================*/
INSERT INTO dbo.DimWarehouse (WarehouseID, WarehouseName, Country, Region)
SELECT
    WarehouseID   = LTRIM(RTRIM(WarehouseID)),
    WarehouseName = LTRIM(RTRIM(WarehouseName)),
    Country       = LTRIM(RTRIM(Country)),
    Region        = CASE LTRIM(RTRIM(Country))
                        WHEN 'Australia'   THEN 'Oceania'
                        WHEN 'New Zealand' THEN 'Oceania'
                        WHEN 'Singapore'   THEN 'Asia'
                        WHEN 'UAE'         THEN 'Middle East'
                        ELSE 'Unclassified'
                    END
FROM stg.DimWarehouse;

PRINT CONCAT('DimWarehouse loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  4. DimProduct
  ---------------------------------------------------------------------------
  HasDemandSignal is derived against stg rather than dbo so this step carries
  no ordering dependency on the fact loads below.
=============================================================================*/
INSERT INTO dbo.DimProduct
(
    ProductID, ProductName, Category, PrimarySupplierID,
    UnitCost, UnitPrice, LeadTimeDays, SafetyStockUnits, HasDemandSignal
)
SELECT
    ProductID         = LTRIM(RTRIM(p.ProductID)),
    ProductName       = LTRIM(RTRIM(p.ProductName)),
    Category          = LTRIM(RTRIM(p.Category)),
    PrimarySupplierID = LTRIM(RTRIM(p.PrimarySupplierID)),
    UnitCost          = TRY_CONVERT(decimal(18,2), p.UnitCost),
    UnitPrice         = TRY_CONVERT(decimal(18,2), p.UnitPrice),
    LeadTimeDays      = TRY_CONVERT(int, p.LeadTimeDays),
    SafetyStockUnits  = TRY_CONVERT(int, p.SafetyStockUnits),
    HasDemandSignal   = CASE WHEN EXISTS (
                                 SELECT 1 FROM stg.FactWeeklyDemand AS wd
                                 WHERE LTRIM(RTRIM(wd.ProductID)) = LTRIM(RTRIM(p.ProductID))
                             ) THEN 1 ELSE 0 END
FROM stg.DimProduct AS p;

PRINT CONCAT('DimProduct loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  5. FactSalesOrders
  ---------------------------------------------------------------------------
  THE CENTRAL TRANSFORMATION OF THIS PHASE.

  The source column named ActualDeliveryDate carries two different meanings:
  a real delivery date on completed orders, and a forward expectation on open
  ones. Phase 2 proved the split is exact - every one of the 435 open orders,
  and only those, has a date after the as-of date.

  Completion is derived from the DATE rather than from OrderStatus, because the
  date is the physical fact and the status is a label describing it. Script 08
  then verifies the two agree on all 80,000 rows; if they ever diverge, that is
  a finding rather than something silently absorbed.

  DeliveryDelayDays is left NULL for open orders. An order that is not yet due
  has no delay - recording zero would understate lateness and recording a
  negative number would invent earliness.
=============================================================================*/
DECLARE @AsOf date = (SELECT TRY_CONVERT(date, ConfigValue, 23)
                      FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate');

INSERT INTO dbo.FactSalesOrders
(
    SalesOrderID, OrderDate, ProductID, WarehouseID, Quantity, Revenue,
    PromisedDeliveryDate, ActualDeliveryDate, ScheduledDeliveryDate,
    OrderStatus, Channel, IsDelivered, IsOpenOrder, DeliveryDelayDays
)
SELECT
    SalesOrderID          = LTRIM(RTRIM(s.SalesOrderID)),
    OrderDate             = d.OrderDate,
    ProductID             = LTRIM(RTRIM(s.ProductID)),
    WarehouseID           = LTRIM(RTRIM(s.WarehouseID)),
    Quantity              = TRY_CONVERT(int, s.Quantity),
    Revenue               = TRY_CONVERT(decimal(18,2), s.Revenue),
    PromisedDeliveryDate  = d.PromisedDeliveryDate,
    ActualDeliveryDate    = CASE WHEN d.SourceDeliveryDate <= @AsOf THEN d.SourceDeliveryDate END,
    ScheduledDeliveryDate = CASE WHEN d.SourceDeliveryDate >  @AsOf THEN d.SourceDeliveryDate END,
    OrderStatus           = LTRIM(RTRIM(s.OrderStatus)),
    Channel               = LTRIM(RTRIM(s.Channel)),
    IsDelivered           = CASE WHEN d.SourceDeliveryDate <= @AsOf THEN 1 ELSE 0 END,
    IsOpenOrder           = CASE WHEN d.SourceDeliveryDate >  @AsOf THEN 1 ELSE 0 END,
    DeliveryDelayDays     = CASE WHEN d.SourceDeliveryDate <= @AsOf
                                 THEN DATEDIFF(day, d.PromisedDeliveryDate, d.SourceDeliveryDate)
                            END
FROM stg.FactSalesOrders AS s
CROSS APPLY
(
    SELECT
        OrderDate            = TRY_CONVERT(date, s.OrderDate, 23),
        PromisedDeliveryDate = TRY_CONVERT(date, s.PromisedDeliveryDate, 23),
        SourceDeliveryDate   = TRY_CONVERT(date, s.ActualDeliveryDate, 23)
) AS d;

PRINT CONCAT('FactSalesOrders loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  6. FactPurchaseOrders
  ---------------------------------------------------------------------------
  Same treatment as sales orders: 368 open POs carry a future receipt date that
  is an expectation, not a receipt.

  ActualLeadTimeDays measures supplier performance (order to receipt) and is
  distinct from DimProduct.LeadTimeDays, which is the planning assumption used
  for reorder points. Phase 2 found actuals running 5-47 days against a
  planning range of 5-30, so the two must never be conflated.

  ReceiptDelayDays is positive when a receipt landed after the expected date.
=============================================================================*/
DECLARE @AsOfPO date = (SELECT TRY_CONVERT(date, ConfigValue, 23)
                        FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate');

INSERT INTO dbo.FactPurchaseOrders
(
    PurchaseOrderID, OrderDate, SupplierID, ProductID, WarehouseID,
    QuantityOrdered, POValue, ExpectedReceiptDate, ActualReceiptDate,
    ScheduledReceiptDate, DefectRate, [Status], IsReceived, IsOpenPO,
    ActualLeadTimeDays, ReceiptDelayDays
)
SELECT
    PurchaseOrderID      = LTRIM(RTRIM(p.PurchaseOrderID)),
    OrderDate            = d.OrderDate,
    SupplierID           = LTRIM(RTRIM(p.SupplierID)),
    ProductID            = LTRIM(RTRIM(p.ProductID)),
    WarehouseID          = LTRIM(RTRIM(p.WarehouseID)),
    QuantityOrdered      = TRY_CONVERT(int, p.QuantityOrdered),
    POValue              = TRY_CONVERT(decimal(18,2), p.POValue),
    ExpectedReceiptDate  = d.ExpectedReceiptDate,
    ActualReceiptDate    = CASE WHEN d.SourceReceiptDate <= @AsOfPO THEN d.SourceReceiptDate END,
    ScheduledReceiptDate = CASE WHEN d.SourceReceiptDate >  @AsOfPO THEN d.SourceReceiptDate END,
    DefectRate           = TRY_CONVERT(decimal(9,6), p.DefectRate),
    [Status]             = LTRIM(RTRIM(p.[Status])),
    IsReceived           = CASE WHEN d.SourceReceiptDate <= @AsOfPO THEN 1 ELSE 0 END,
    IsOpenPO             = CASE WHEN d.SourceReceiptDate >  @AsOfPO THEN 1 ELSE 0 END,
    ActualLeadTimeDays   = CASE WHEN d.SourceReceiptDate <= @AsOfPO
                                THEN DATEDIFF(day, d.OrderDate, d.SourceReceiptDate)
                           END,
    ReceiptDelayDays     = CASE WHEN d.SourceReceiptDate <= @AsOfPO
                                THEN DATEDIFF(day, d.ExpectedReceiptDate, d.SourceReceiptDate)
                           END
FROM stg.FactPurchaseOrders AS p
CROSS APPLY
(
    SELECT
        OrderDate           = TRY_CONVERT(date, p.OrderDate, 23),
        ExpectedReceiptDate = TRY_CONVERT(date, p.ExpectedReceiptDate, 23),
        SourceReceiptDate   = TRY_CONVERT(date, p.ActualReceiptDate, 23)
) AS d;

PRINT CONCAT('FactPurchaseOrders loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  7. FactShipments
  ---------------------------------------------------------------------------
  Shipments inherit the same ambiguity: 435 rows carry a delivery date beyond
  the as-of date, and 55 carry a ship date beyond it.

  The source DeliveryStatus column is retained but must be treated with care.
  It reproduces (DeliveryDate > PromisedDeliveryDate) on all 80,000 rows -
  INCLUDING the 435 not yet delivered, where it is a verdict on an event that
  has not happened. It is kept only so the DAX-derived OTIF can be reconciled
  against it in later phases; it is never the basis of a KPI.
=============================================================================*/
DECLARE @AsOfSh date = (SELECT TRY_CONVERT(date, ConfigValue, 23)
                        FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate');

INSERT INTO dbo.FactShipments
(
    ShipmentID, SalesOrderID, WarehouseID, Carrier, ShipDate,
    ActualDeliveryDate, ScheduledDeliveryDate, FreightCost, DeliveryStatus,
    IsShipped, IsDelivered, TransitDays
)
SELECT
    ShipmentID            = LTRIM(RTRIM(s.ShipmentID)),
    SalesOrderID          = LTRIM(RTRIM(s.SalesOrderID)),
    WarehouseID           = LTRIM(RTRIM(s.WarehouseID)),
    Carrier               = LTRIM(RTRIM(s.Carrier)),
    ShipDate              = d.ShipDate,
    ActualDeliveryDate    = CASE WHEN d.SourceDeliveryDate <= @AsOfSh THEN d.SourceDeliveryDate END,
    ScheduledDeliveryDate = CASE WHEN d.SourceDeliveryDate >  @AsOfSh THEN d.SourceDeliveryDate END,
    FreightCost           = TRY_CONVERT(decimal(18,2), s.FreightCost),
    DeliveryStatus        = LTRIM(RTRIM(s.DeliveryStatus)),
    IsShipped             = CASE WHEN d.ShipDate           <= @AsOfSh THEN 1 ELSE 0 END,
    IsDelivered           = CASE WHEN d.SourceDeliveryDate <= @AsOfSh THEN 1 ELSE 0 END,
    TransitDays           = CASE WHEN d.SourceDeliveryDate <= @AsOfSh
                                 THEN DATEDIFF(day, d.ShipDate, d.SourceDeliveryDate)
                            END
FROM stg.FactShipments AS s
CROSS APPLY
(
    SELECT
        ShipDate           = TRY_CONVERT(date, s.ShipDate, 23),
        SourceDeliveryDate = TRY_CONVERT(date, s.DeliveryDate, 23)
) AS d;

PRINT CONCAT('FactShipments loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  8. FactWeeklyDemand
  ---------------------------------------------------------------------------
  Typed only. No smoothing, no gap-filling, no outlier treatment. The grid is
  already complete and BaselineForecastUnits is the locked Phase 14 benchmark.
=============================================================================*/
INSERT INTO dbo.FactWeeklyDemand
(
    WeekStart, ProductID, WarehouseID, ActualDemandUnits, BaselineForecastUnits
)
SELECT
    WeekStart             = TRY_CONVERT(date, w.WeekStart, 23),
    ProductID             = LTRIM(RTRIM(w.ProductID)),
    WarehouseID           = LTRIM(RTRIM(w.WarehouseID)),
    ActualDemandUnits     = TRY_CONVERT(int, w.ActualDemandUnits),
    BaselineForecastUnits = TRY_CONVERT(int, w.BaselineForecastUnits)
FROM stg.FactWeeklyDemand AS w;

PRINT CONCAT('FactWeeklyDemand loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  9. FactInventorySnapshot
  ---------------------------------------------------------------------------
  InventoryValue is intentionally not carried forward. It equals
  OnHandUnits x UnitCost on all 315,000 rows with zero deviation, so it is
  fully recoverable from DimProduct. Dropping it removes a 237,846-distinct-
  value column that would compress poorly in VertiPaq. The source value stays
  in stg and is reconciled in script 08.
=============================================================================*/
INSERT INTO dbo.FactInventorySnapshot
(
    SnapshotDate, ProductID, WarehouseID, OnHandUnits, InboundUnits
)
SELECT
    SnapshotDate = TRY_CONVERT(date, i.SnapshotDate, 23),
    ProductID    = LTRIM(RTRIM(i.ProductID)),
    WarehouseID  = LTRIM(RTRIM(i.WarehouseID)),
    OnHandUnits  = TRY_CONVERT(int, i.OnHandUnits),
    InboundUnits = TRY_CONVERT(int, i.InboundUnits)
FROM stg.FactInventorySnapshot AS i;

PRINT CONCAT('FactInventorySnapshot loaded: ', @@ROWCOUNT, ' rows.');
GO

/*=============================================================================
  10. SecurityUserAccess
  ---------------------------------------------------------------------------
  Email is lower-cased and trimmed so the later RLS predicate can compare it to
  USERPRINCIPALNAME() without depending on how the identity provider cases the
  address.

  IsAllWarehouses turns the literal sentinel 'ALL' into an explicit boolean, so
  the security rule reads as a flag test rather than a magic string comparison
  buried in DAX. No RLS logic is implemented here.
=============================================================================*/
INSERT INTO dbo.SecurityUserAccess (UserEmail, [Role], WarehouseID, IsAllWarehouses)
SELECT
    UserEmail       = LOWER(LTRIM(RTRIM(u.UserEmail))),
    [Role]          = LTRIM(RTRIM(u.[Role])),
    WarehouseID     = UPPER(LTRIM(RTRIM(u.WarehouseID))),
    IsAllWarehouses = CASE WHEN UPPER(LTRIM(RTRIM(u.WarehouseID))) = 'ALL' THEN 1 ELSE 0 END
FROM stg.SecurityUserAccess AS u;

PRINT CONCAT('SecurityUserAccess loaded: ', @@ROWCOUNT, ' rows.');
GO

/*----------------------------------------------------------- confirmation --*/
SELECT TableName = 'dbo.DimDate',               [RowCount] = COUNT(*) FROM dbo.DimDate
UNION ALL SELECT 'dbo.DimProduct',              COUNT(*) FROM dbo.DimProduct
UNION ALL SELECT 'dbo.DimSupplier',             COUNT(*) FROM dbo.DimSupplier
UNION ALL SELECT 'dbo.DimWarehouse',            COUNT(*) FROM dbo.DimWarehouse
UNION ALL SELECT 'dbo.FactSalesOrders',         COUNT(*) FROM dbo.FactSalesOrders
UNION ALL SELECT 'dbo.FactPurchaseOrders',      COUNT(*) FROM dbo.FactPurchaseOrders
UNION ALL SELECT 'dbo.FactShipments',           COUNT(*) FROM dbo.FactShipments
UNION ALL SELECT 'dbo.FactWeeklyDemand',        COUNT(*) FROM dbo.FactWeeklyDemand
UNION ALL SELECT 'dbo.FactInventorySnapshot',   COUNT(*) FROM dbo.FactInventorySnapshot
UNION ALL SELECT 'dbo.SecurityUserAccess',      COUNT(*) FROM dbo.SecurityUserAccess
ORDER BY TableName;
GO
