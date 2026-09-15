// =============================================================================
// Phase 6 - Core DAX & Measure Layer
// Supply Chain Control Tower
//
//   TabularEditor.exe <definition> -S phase6_core_measures.csx -TMDL <definition>
//
// Creates the _Measures table and 44 foundational measures.
//
// No calculation groups, no time intelligence, no ABC/XYZ, no supplier score,
// no forecasting, no RLS. Those are later phases.
//
// Note: TE2's script compiler predates C# local functions, so helpers are
// declared as delegates.
// =============================================================================

var log = new System.Text.StringBuilder();
Action<string> L = s => log.AppendLine(s);

// -----------------------------------------------------------------------------
// 1. The _Measures table
// -----------------------------------------------------------------------------
// A single-row calculated table holding nothing but measures. The leading
// underscore sorts it to the top of the field list. Its one column exists only
// because a table must have one, and is hidden.
//
// Measures are centralised rather than scattered across fact tables: a measure
// parked on FactSalesOrders implies it only concerns sales, which stops being
// true the moment it references another table.
// -----------------------------------------------------------------------------
L("=== 1. MEASURE TABLE ===");
if (Model.Tables.Contains("_Measures")) Model.Tables["_Measures"].Delete();
var mt = Model.AddCalculatedTable("_Measures", "ROW(\"_\", BLANK())");
mt.Description = "Holds all business measures. The single hidden column exists only because a table requires one.";
foreach (var c in mt.Columns) { c.IsHidden = true; }
L("  _Measures created with " + mt.Columns.Count + " hidden column(s)");

// -----------------------------------------------------------------------------
// Measure helper
// -----------------------------------------------------------------------------
int count = 0;
Action<string, string, string, string, string> M =
    (name, folder, format, description, dax) =>
{
    var m = mt.AddMeasure(name, dax, folder);
    m.FormatString = format;
    m.Description = description;
    count++;
};

// Format constants. No currency symbol is applied: the source states no
// currency, and asserting one would be inventing information. Set project-wide
// later if a reporting currency is chosen.
var MONEY = "#,0.00";
var COUNT = "#,0";
var PCT   = "0.0%";
var DAYS  = "0.00";
var DATE  = "yyyy-mm-dd";

// =============================================================================
// 08 MODEL CONTROLS
// =============================================================================
L("");
L("=== 08 MODEL CONTROLS ===");

// ModelConfig is disconnected and stores every value as text, so the key is
// isolated with REMOVEFILTERS and the date is parsed explicitly rather than
// with DATEVALUE, which is locale-dependent. GETDATE()/TODAY() is never used:
// today is already past the extract, so a system-date anchor would reclassify
// in-flight orders as overdue and drift further every day.
M("As Of Date", "08 Model Controls", DATE,
  "The dataset's fixed extract date, read from ModelConfig. Anchors every current and overdue calculation. Never substitute TODAY().",
@"VAR ConfigText =
    CALCULATE (
        SELECTEDVALUE ( ModelConfig[ConfigValue] ),
        REMOVEFILTERS ( ModelConfig ),
        ModelConfig[ConfigKey] = ""AsOfDate""
    )
RETURN
    IF (
        NOT ISBLANK ( ConfigText ),
        DATE ( VALUE ( LEFT ( ConfigText, 4 ) ), VALUE ( MID ( ConfigText, 6, 2 ) ), VALUE ( RIGHT ( ConfigText, 2 ) ) )
    )");

M("Forecast Horizon Weeks", "08 Model Controls", COUNT,
  "Planned forward forecast horizon in weeks, read from ModelConfig.",
@"VAR ConfigText =
    CALCULATE (
        SELECTEDVALUE ( ModelConfig[ConfigValue] ),
        REMOVEFILTERS ( ModelConfig ),
        ModelConfig[ConfigKey] = ""ForecastHorizonWeeks""
    )
RETURN
    IF ( NOT ISBLANK ( ConfigText ), VALUE ( ConfigText ) )");

// =============================================================================
// 01 CORE KPIs
// =============================================================================
L("=== 01 CORE KPIs ===");

M("Total Revenue", "01 Core KPIs", MONEY,
  "Total sales-order revenue in the current filter context.",
  "SUM ( FactSalesOrders[Revenue] )");

// SalesOrderID is the table's primary key, so COUNTROWS and DISTINCTCOUNT agree.
// COUNTROWS is used because it is materially cheaper.
M("Sales Orders", "01 Core KPIs", COUNT,
  "Count of sales orders. SalesOrderID is unique per row, so this equals a distinct order count.",
  "COUNTROWS ( FactSalesOrders )");

M("Units Sold", "01 Core KPIs", COUNT,
  "Total quantity ordered across sales orders. This is quantity ORDERED; the dataset records no delivered quantity.",
  "SUM ( FactSalesOrders[Quantity] )");

M("Purchase Order Value", "01 Core KPIs", MONEY,
  "Total committed purchase-order value in the current filter context.",
  "SUM ( FactPurchaseOrders[POValue] )");

M("Freight Cost", "01 Core KPIs", MONEY,
  "Total outbound freight cost across shipments.",
  "SUM ( FactShipments[FreightCost] )");

M("On-Time Delivery %", "01 Core KPIs", PCT,
  "Share of DELIVERED orders that arrived on or before the promised date. Orders not yet due are excluded: they can be neither on time nor late. This is on-time only - it is NOT OTIF, because the dataset records no delivered quantity.",
  "DIVIDE ( [On-Time Deliveries], [Completed Deliveries] )");

// =============================================================================
// 02 SALES
// =============================================================================
L("=== 02 SALES ===");

M("Average Order Value", "02 Sales", MONEY,
  "Revenue divided by number of sales orders.",
  "DIVIDE ( [Total Revenue], [Sales Orders] )");

M("Average Selling Price", "02 Sales", MONEY,
  "Revenue divided by units sold. The realised price per unit, which differs from DimProduct[UnitPrice] because the source carries genuine price variance.",
  "DIVIDE ( [Total Revenue], [Units Sold] )");

M("Open Sales Orders", "02 Sales", COUNT,
  "Orders scheduled to deliver after the as-of date. In flight, not overdue.",
  "CALCULATE ( [Sales Orders], FactSalesOrders[IsOpenOrder] = TRUE () )");

M("Delivered Sales Orders", "02 Sales", COUNT,
  "Orders delivered on or before the as-of date.",
  "CALCULATE ( [Sales Orders], FactSalesOrders[IsDelivered] = TRUE () )");

M("Sales Orders Due As Of Date", "02 Sales", COUNT,
  "Orders whose promised delivery date fell on or before the as-of date - the population for which on-time performance is measurable.",
@"VAR AsOf = [As Of Date]
RETURN
    CALCULATE ( [Sales Orders], FactSalesOrders[PromisedDeliveryDate] <= AsOf )");

// =============================================================================
// 03 INVENTORY & DEMAND
// =============================================================================
L("=== 03 INVENTORY & DEMAND ===");

// SEMI-ADDITIVE. Inventory may be summed across products and warehouses but
// never across time: summing all 105 snapshots returns 334,301,020 units, a
// figure that existed at no point in reality, against 5,640,283 actually held.
//
// Every current-inventory measure therefore resolves ONE snapshot date and uses
// REMOVEFILTERS(DimDate) so a report date slicer cannot blank it out. This is
// the anchored 'current position' reading. A period-relative variant is a
// separate measure for a later phase, and would be named to say so.
M("Current Inventory Snapshot Date", "03 Inventory & Demand", DATE,
  "The latest inventory snapshot on or before the as-of date. Anchored: ignores date slicers so current stock never disappears from a filtered page.",
@"VAR AsOf = [As Of Date]
RETURN
    CALCULATE (
        MAX ( FactInventorySnapshot[SnapshotDate] ),
        REMOVEFILTERS ( DimDate ),
        FactInventorySnapshot[SnapshotDate] <= AsOf
    )");

M("Current On Hand Units", "03 Inventory & Demand", COUNT,
  "Units on hand at the current snapshot. Responds to product, category and warehouse filters but never sums across time.",
@"VAR SnapDate = [Current Inventory Snapshot Date]
RETURN
    CALCULATE (
        SUM ( FactInventorySnapshot[OnHandUnits] ),
        REMOVEFILTERS ( DimDate ),
        FactInventorySnapshot[SnapshotDate] = SnapDate
    )");

M("Current Inbound Units", "03 Inventory & Demand", COUNT,
  "Units in transit at the current snapshot. Ranges 0-29 per row in this dataset, so it barely moves replenishment arithmetic.",
@"VAR SnapDate = [Current Inventory Snapshot Date]
RETURN
    CALCULATE (
        SUM ( FactInventorySnapshot[InboundUnits] ),
        REMOVEFILTERS ( DimDate ),
        FactInventorySnapshot[SnapshotDate] = SnapDate
    )");

M("Current Inventory Position", "03 Inventory & Demand", COUNT,
  "On hand plus inbound at the current snapshot.",
  "[Current On Hand Units] + [Current Inbound Units]");

// Unit cost varies by product, so the value must be formed at row grain.
// [Current On Hand Units] * AVERAGE(UnitCost) would be wrong across any mix of
// products. The iterator runs over one snapshot only - roughly 3,000 rows.
M("Current Inventory Value", "01 Core KPIs", MONEY,
  "Value of stock held at the current snapshot, as on-hand units times unit cost evaluated per row. Rebuilt in DAX because the stored InventoryValue column was removed from the reporting contract as exactly derivable.",
@"VAR SnapDate = [Current Inventory Snapshot Date]
RETURN
    CALCULATE (
        SUMX (
            FactInventorySnapshot,
            FactInventorySnapshot[OnHandUnits] * RELATED ( DimProduct[UnitCost] )
        ),
        REMOVEFILTERS ( DimDate ),
        FactInventorySnapshot[SnapshotDate] = SnapDate
    )");

M("Actual Demand Units", "03 Inventory & Demand", COUNT,
  "Actual weekly demand. Independent of sales orders in this dataset - the two series must never be presented as derived from one another.",
  "SUM ( FactWeeklyDemand[ActualDemandUnits] )");

M("Baseline Forecast Units", "03 Inventory & Demand", COUNT,
  "The supplied baseline forecast. This is the locked benchmark any model must beat in the forecasting phase.",
  "SUM ( FactWeeklyDemand[BaselineForecastUnits] )");

M("Demand Variance Units", "03 Inventory & Demand", COUNT,
  "Baseline forecast minus actual demand. Negative means the baseline under-forecast.",
  "[Baseline Forecast Units] - [Actual Demand Units]");

M("Demand Variance %", "03 Inventory & Demand", PCT,
  "Demand variance as a share of actual demand. This is forecast BIAS, not accuracy: opposite errors cancel.",
  "DIVIDE ( [Demand Variance Units], [Actual Demand Units] )");

// =============================================================================
// 04 PROCUREMENT
// =============================================================================
L("=== 04 PROCUREMENT ===");

M("Purchase Orders", "04 Procurement", COUNT,
  "Count of purchase orders. PurchaseOrderID is unique per row.",
  "COUNTROWS ( FactPurchaseOrders )");

M("Units Ordered", "04 Procurement", COUNT,
  "Total quantity ordered from suppliers.",
  "SUM ( FactPurchaseOrders[QuantityOrdered] )");

M("Average Purchase Order Value", "04 Procurement", MONEY,
  "Purchase-order value divided by number of purchase orders.",
  "DIVIDE ( [Purchase Order Value], [Purchase Orders] )");

M("Open Purchase Orders", "04 Procurement", COUNT,
  "Purchase orders scheduled to arrive after the as-of date. In flight, not late.",
  "CALCULATE ( [Purchase Orders], FactPurchaseOrders[IsOpenPO] = TRUE () )");

M("Received Purchase Orders", "04 Procurement", COUNT,
  "Purchase orders received on or before the as-of date.",
  "CALCULATE ( [Purchase Orders], FactPurchaseOrders[IsReceived] = TRUE () )");

M("Purchase Orders Due As Of Date", "04 Procurement", COUNT,
  "Purchase orders whose expected receipt date fell on or before the as-of date.",
@"VAR AsOf = [As Of Date]
RETURN
    CALCULATE ( [Purchase Orders], FactPurchaseOrders[ExpectedReceiptDate] <= AsOf )");

M("Average Supplier Lead Time", "04 Procurement", DAYS,
  "Mean days from order to receipt, over RECEIVED purchase orders only. Distinct from DimProduct[LeadTimeDays], which is the planning assumption.",
  "CALCULATE ( AVERAGE ( FactPurchaseOrders[ActualLeadTimeDays] ), FactPurchaseOrders[IsReceived] = TRUE () )");

// =============================================================================
// 05 LOGISTICS
// =============================================================================
L("=== 05 LOGISTICS ===");

M("Total Shipments", "05 Logistics", COUNT,
  "Count of outbound shipments.",
  "COUNTROWS ( FactShipments )");

M("Average Freight Cost per Shipment", "05 Logistics", MONEY,
  "Freight cost divided by number of shipments.",
  "DIVIDE ( [Freight Cost], [Total Shipments] )");

// DISTINCTCOUNT rather than COUNTROWS: shipments are 1:1 with orders in this
// dataset, but real distribution splits an order across several shipments, and
// the measure should stay correct if that becomes true.
M("Average Freight Cost per Sales Order", "05 Logistics", MONEY,
  "Freight cost divided by distinct sales orders shipped. Uses a distinct count so the measure stays correct if an order is ever split across shipments.",
  "DIVIDE ( [Freight Cost], DISTINCTCOUNT ( FactShipments[SalesOrderID] ) )");

// =============================================================================
// 06 DELIVERY PERFORMANCE
// =============================================================================
L("=== 06 DELIVERY PERFORMANCE ===");

// The denominator throughout is COMPLETED records only. Including open orders
// would score deliveries that have not happened against dates that have not
// arrived. DeliveryDelayDays is NULL while open, so the flag and the null are
// belt and braces.
M("Completed Deliveries", "06 Delivery Performance", COUNT,
  "Orders actually delivered on or before the as-of date. The denominator for all delivery performance.",
  "CALCULATE ( [Sales Orders], FactSalesOrders[IsDelivered] = TRUE () )");

M("On-Time Deliveries", "06 Delivery Performance", COUNT,
  "Delivered orders that arrived on or before the promised date.",
@"CALCULATE (
    [Sales Orders],
    FactSalesOrders[IsDelivered] = TRUE (),
    FactSalesOrders[DeliveryDelayDays] <= 0
)");

M("Late Deliveries", "06 Delivery Performance", COUNT,
  "Delivered orders that arrived after the promised date.",
@"CALCULATE (
    [Sales Orders],
    FactSalesOrders[IsDelivered] = TRUE (),
    FactSalesOrders[DeliveryDelayDays] > 0
)");

M("Late Delivery %", "06 Delivery Performance", PCT,
  "Share of delivered orders that arrived late.",
  "DIVIDE ( [Late Deliveries], [Completed Deliveries] )");

M("Average Delivery Delay Days", "06 Delivery Performance", DAYS,
  "Mean days between promised and actual delivery, over delivered orders. Positive means late; early deliveries pull the average down.",
  "CALCULATE ( AVERAGE ( FactSalesOrders[DeliveryDelayDays] ), FactSalesOrders[IsDelivered] = TRUE () )");

M("Completed Receipts", "06 Delivery Performance", COUNT,
  "Purchase orders actually received. The denominator for supplier receipt performance.",
  "CALCULATE ( [Purchase Orders], FactPurchaseOrders[IsReceived] = TRUE () )");

M("On-Time Receipts", "06 Delivery Performance", COUNT,
  "Received purchase orders that arrived on or before the expected receipt date.",
@"CALCULATE (
    [Purchase Orders],
    FactPurchaseOrders[IsReceived] = TRUE (),
    FactPurchaseOrders[ReceiptDelayDays] <= 0
)");

M("Late Receipts", "06 Delivery Performance", COUNT,
  "Received purchase orders that arrived after the expected receipt date.",
@"CALCULATE (
    [Purchase Orders],
    FactPurchaseOrders[IsReceived] = TRUE (),
    FactPurchaseOrders[ReceiptDelayDays] > 0
)");

M("On-Time Receipt %", "06 Delivery Performance", PCT,
  "Share of received purchase orders that arrived on time. Supplier delivery reliability. NOT OTIF - no received quantity exists to prove 'in full'.",
  "DIVIDE ( [On-Time Receipts], [Completed Receipts] )");

M("Average Receipt Delay Days", "06 Delivery Performance", DAYS,
  "Mean days between expected and actual receipt, over received purchase orders.",
  "CALCULATE ( AVERAGE ( FactPurchaseOrders[ReceiptDelayDays] ), FactPurchaseOrders[IsReceived] = TRUE () )");

// =============================================================================
// 07 DATE ROLES
// =============================================================================
L("=== 07 DATE ROLES ===");

// Foundations only. These demonstrate that each inactive relationship resolves,
// and give later phases a worked pattern. The full catalogue is deliberately
// not duplicated across every date role.
//
// Each carries NOT ISBLANK on its role column. Without it, USERELATIONSHIP
// swaps the active relationship but restricts nothing when no date filter is
// present, so every row counts whether or not it holds that date. Measured
// during Phase 6 validation: 'by Scheduled Delivery Date' returned 80,000
// against the 435 orders that actually carry one. Correct DAX, misleading
// number - and precisely the sort of figure that reaches an executive card.
// The predicate is a no-op under a date filter and makes the measure honest
// without one.
M("Sales Orders by Actual Delivery Date", "07 Date Roles", COUNT,
  "Sales orders counted by when they were DELIVERED rather than ordered. Excludes orders not yet delivered.",
@"CALCULATE (
    [Sales Orders],
    USERELATIONSHIP ( FactSalesOrders[ActualDeliveryDate], DimDate[Date] ),
    NOT ISBLANK ( FactSalesOrders[ActualDeliveryDate] )
)");

M("Sales Orders by Promised Delivery Date", "07 Date Roles", COUNT,
  "Sales orders counted by when delivery was PROMISED. The natural denominator for period on-time analysis.",
@"CALCULATE (
    [Sales Orders],
    USERELATIONSHIP ( FactSalesOrders[PromisedDeliveryDate], DimDate[Date] ),
    NOT ISBLANK ( FactSalesOrders[PromisedDeliveryDate] )
)");

M("Sales Orders by Scheduled Delivery Date", "07 Date Roles", COUNT,
  "Open orders counted by expected delivery date - the forward order book. Only in-flight orders carry this date, so this counts the open book, not the whole table.",
@"CALCULATE (
    [Sales Orders],
    USERELATIONSHIP ( FactSalesOrders[ScheduledDeliveryDate], DimDate[Date] ),
    NOT ISBLANK ( FactSalesOrders[ScheduledDeliveryDate] )
)");

M("Purchase Orders by Actual Receipt Date", "07 Date Roles", COUNT,
  "Purchase orders counted by when goods were RECEIVED rather than ordered. Excludes POs not yet received.",
@"CALCULATE (
    [Purchase Orders],
    USERELATIONSHIP ( FactPurchaseOrders[ActualReceiptDate], DimDate[Date] ),
    NOT ISBLANK ( FactPurchaseOrders[ActualReceiptDate] )
)");

M("Purchase Orders by Scheduled Receipt Date", "07 Date Roles", COUNT,
  "Open purchase orders counted by expected arrival - the inbound pipeline that later feeds stockout risk. Only open POs carry this date.",
@"CALCULATE (
    [Purchase Orders],
    USERELATIONSHIP ( FactPurchaseOrders[ScheduledReceiptDate], DimDate[Date] ),
    NOT ISBLANK ( FactPurchaseOrders[ScheduledReceiptDate] )
)");

L("");
L("=== FINAL STATE ===");
L("Measures created: " + count);
L("Total measures in model: " + Model.AllMeasures.Count());
L("Tables: " + Model.Tables.Count);
L("Relationships: " + Model.Relationships.Count
  + " (active " + Model.Relationships.Count(r => r.IsActive) + ")");
foreach (var g in Model.AllMeasures.GroupBy(x => x.DisplayFolder).OrderBy(x => x.Key))
    L("  " + g.Key + ": " + g.Count());

var logPath = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "phase6_log.txt");
System.IO.File.WriteAllText(logPath, log.ToString());
