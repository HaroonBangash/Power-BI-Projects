// =============================================================================
// Phase 5 - Semantic Model Architecture
// Supply Chain Control Tower
//
// Executed via Tabular Editor 2 against the PBIP TMDL definition folder:
//   TabularEditor.exe <definition> -S phase5_semantic_model.csx -TMDL <definition>
//
// Builds the star schema: relationships, date-table marking, sort-by columns,
// hierarchies, visibility, data categories, formats and descriptions.
//
// No measures. No RLS. No calculation groups. Those are later phases.
//
// Note: TE2's script compiler predates C# local functions, so helpers are
// declared as delegates.
// =============================================================================

var log = new System.Text.StringBuilder();
Action<string> L = s => log.AppendLine(s);

// -----------------------------------------------------------------------------
// Helper: create a single-column relationship.
// In TOM, FromColumn is the MANY side and ToColumn is the ONE side.
// Every relationship in this model is Many->One, single-direction. Bidirectional
// filtering is never used: it creates ambiguous paths and is the usual cause of
// a model that returns different answers depending on visual order.
// -----------------------------------------------------------------------------
Action<string, string, string, string, bool> Rel =
    (fromTable, fromCol, toTable, toCol, isActive) =>
{
    var r = Model.AddRelationship();
    r.FromColumn = Model.Tables[fromTable].Columns[fromCol];
    r.ToColumn = Model.Tables[toTable].Columns[toCol];
    r.FromCardinality = RelationshipEndCardinality.Many;
    r.ToCardinality = RelationshipEndCardinality.One;
    r.CrossFilteringBehavior = CrossFilteringBehavior.OneDirection;
    r.IsActive = isActive;
    L("  " + (isActive ? "ACTIVE   " : "inactive ") + toTable + "[" + toCol + "] 1 -> * "
        + fromTable + "[" + fromCol + "]");
};

L("=== 1. RELATIONSHIPS ===");
L("-- DimProduct --");
Rel("FactSalesOrders", "ProductID", "DimProduct", "ProductID", true);
Rel("FactPurchaseOrders", "ProductID", "DimProduct", "ProductID", true);
Rel("FactShipments", "ProductID", "DimProduct", "ProductID", true);
Rel("FactWeeklyDemand", "ProductID", "DimProduct", "ProductID", true);
Rel("FactInventorySnapshot", "ProductID", "DimProduct", "ProductID", true);

L("-- DimWarehouse --");
Rel("FactSalesOrders", "WarehouseID", "DimWarehouse", "WarehouseID", true);
Rel("FactPurchaseOrders", "WarehouseID", "DimWarehouse", "WarehouseID", true);
Rel("FactShipments", "WarehouseID", "DimWarehouse", "WarehouseID", true);
Rel("FactWeeklyDemand", "WarehouseID", "DimWarehouse", "WarehouseID", true);
Rel("FactInventorySnapshot", "WarehouseID", "DimWarehouse", "WarehouseID", true);

L("-- DimSupplier (procurement only; NOT snowflaked onto DimProduct) --");
Rel("FactPurchaseOrders", "SupplierID", "DimSupplier", "SupplierID", true);

L("-- DimDate: primary event date of each fact (active) --");
Rel("FactSalesOrders", "OrderDate", "DimDate", "Date", true);
Rel("FactPurchaseOrders", "OrderDate", "DimDate", "Date", true);
Rel("FactShipments", "ShipDate", "DimDate", "Date", true);
Rel("FactWeeklyDemand", "WeekStart", "DimDate", "Date", true);
Rel("FactInventorySnapshot", "SnapshotDate", "DimDate", "Date", true);

L("-- DimDate: role-playing alternates (inactive, for USERELATIONSHIP) --");
Rel("FactSalesOrders", "PromisedDeliveryDate", "DimDate", "Date", false);
Rel("FactSalesOrders", "ActualDeliveryDate", "DimDate", "Date", false);
Rel("FactSalesOrders", "ScheduledDeliveryDate", "DimDate", "Date", false);
Rel("FactPurchaseOrders", "ExpectedReceiptDate", "DimDate", "Date", false);
Rel("FactPurchaseOrders", "ActualReceiptDate", "DimDate", "Date", false);
Rel("FactPurchaseOrders", "ScheduledReceiptDate", "DimDate", "Date", false);
Rel("FactShipments", "ActualDeliveryDate", "DimDate", "Date", false);
Rel("FactShipments", "ScheduledDeliveryDate", "DimDate", "Date", false);

// FactShipments[PromisedDeliveryDate] and [OrderDate] deliberately get NO
// relationship. Both are copies carried from the sales order. They are useful
// row-level inputs to DAX (on-time derivation, order-to-dispatch fulfilment
// time), but relating them would create a second path to "by order date"
// alongside FactSalesOrders[OrderDate]. Two ways to answer one question is how
// report authors end up with figures that disagree.

L("");
L("=== 2. MARK DIMDATE AS THE DATE TABLE ===");
// Required for DAX time intelligence to work reliably. DimDate qualifies: the
// Date column is unique, non-null and contiguous across 2,007 days.
Model.Tables["DimDate"].DataCategory = "Time";
Model.Tables["DimDate"].Columns["Date"].IsKey = true;
L("  DimDate.DataCategory = Time; DimDate[Date].IsKey = true");

L("");
L("=== 3. SORT-BY COLUMNS ===");
// Without these, month names sort alphabetically: April, August, December...
Action<string, string, string> SortBy = (table, col, by) =>
{
    Model.Tables[table].Columns[col].SortByColumn = Model.Tables[table].Columns[by];
    L("  " + table + "[" + col + "] sorted by [" + by + "]");
};
SortBy("DimDate", "MonthName", "MonthNumber");
SortBy("DimDate", "MonthShortName", "MonthNumber");
SortBy("DimDate", "DayName", "DayOfWeekISO");
SortBy("DimDate", "DayShortName", "DayOfWeekISO");
SortBy("DimDate", "YearMonthLabel", "YearMonthKey");
SortBy("DimDate", "YearQuarterLabel", "YearQuarterKey");
SortBy("DimDate", "ISOYearWeekLabel", "ISOYearWeekKey");
SortBy("DimDate", "QuarterLabel", "Quarter");
SortBy("DimDate", "FinancialYear", "FinancialYearNumber");

L("");
L("=== 4. HIERARCHIES ===");
Action<string, string, string[]> Hier = (table, name, levels) =>
{
    var t = Model.Tables[table];
    if (t.Hierarchies.Contains(name)) t.Hierarchies[name].Delete();
    var h = t.AddHierarchy(name);
    foreach (var lv in levels) h.AddLevel(t.Columns[lv], lv);
    L("  " + table + " / " + name + ": " + string.Join(" > ", levels));
};
Hier("DimDate", "Calendar", new[] { "Year", "QuarterLabel", "MonthName", "Date" });
Hier("DimDate", "Financial Calendar", new[] { "FinancialYear", "FinancialQuarter", "MonthName", "Date" });
Hier("DimProduct", "Product", new[] { "Category", "ProductName" });
Hier("DimWarehouse", "Geography", new[] { "Region", "Country", "WarehouseName" });

L("");
L("=== 5. HIDE TECHNICAL COLUMNS ===");
// Rule applied: hide anything a report author should not drag onto a visual.
// Fact-side foreign keys are hidden because the dimension supplies the
// attribute; degenerate transaction identifiers stay VISIBLE because
// drill-through detail pages and distinct counts genuinely need them.
var hide = new[] {
    // Fact foreign keys - use the dimension instead
    "FactSalesOrders|ProductID","FactSalesOrders|WarehouseID",
    "FactPurchaseOrders|ProductID","FactPurchaseOrders|WarehouseID","FactPurchaseOrders|SupplierID",
    "FactShipments|ProductID","FactShipments|WarehouseID",
    "FactWeeklyDemand|ProductID","FactWeeklyDemand|WarehouseID",
    "FactInventorySnapshot|ProductID","FactInventorySnapshot|WarehouseID",
    // DimDate sort keys - they drive sortByColumn and are meaningless on a visual
    "DimDate|DateKey","DimDate|YearMonthKey","DimDate|YearQuarterKey",
    "DimDate|ISOYearWeekKey","DimDate|MonthNumber","DimDate|DayOfWeekISO",
    "DimDate|FinancialMonthNumber","DimDate|FinancialYearNumber",
    // Unrelated date copies on shipments - DAX inputs only, no relationship
    "FactShipments|PromisedDeliveryDate","FactShipments|OrderDate",
    // Source flag retained only to reconcile against DAX-derived OTIF. It judges
    // 435 deliveries that have not happened, so it must not reach a visual.
    "FactShipments|DeliveryStatus",
    // Foreign key with no relationship by design - see the snowflake decision
    "DimProduct|PrimarySupplierID"
};
foreach (var h in hide)
{
    var p = h.Split('|');
    Model.Tables[p[0]].Columns[p[1]].IsHidden = true;
}
L("  Columns hidden: " + hide.Length);

L("");
L("=== 6. DATA CATEGORIES ===");
Model.Tables["DimWarehouse"].Columns["Country"].DataCategory = "Country";
Model.Tables["DimSupplier"].Columns["Country"].DataCategory = "Country";
// The six warehouses are named for the cities they occupy, so this is accurate
// and enables warehouse-level map visuals. Revisit if a second site ever opens
// in a city already represented.
Model.Tables["DimWarehouse"].Columns["WarehouseName"].DataCategory = "City";
// Region holds Oceania / Asia / Middle East. 'Middle East' is not a continent,
// so no geographic category is applied rather than forcing a wrong one.
L("  Country x2 -> Country; WarehouseName -> City; Region left uncategorised");

L("");
L("=== 7. FORMAT STRINGS ===");
// Storage type is untouched - see decision D18. Formatting and storage are
// separate concerns and only the display format is set here.
Model.Tables["FactPurchaseOrders"].Columns["DefectRate"].FormatString = "0.00%";
foreach (var s in new[] {
    "FactSalesOrders|Quantity","FactPurchaseOrders|QuantityOrdered",
    "FactInventorySnapshot|OnHandUnits","FactInventorySnapshot|InboundUnits",
    "FactWeeklyDemand|ActualDemandUnits","FactWeeklyDemand|BaselineForecastUnits",
    "DimProduct|SafetyStockUnits","DimProduct|LeadTimeDays" })
{
    var p = s.Split('|');
    Model.Tables[p[0]].Columns[p[1]].FormatString = "#,0";
}
L("  DefectRate -> 0.00%; 8 unit columns -> #,0");

L("");
L("=== 8. DESCRIPTIONS ===");
Action<string, string> TDesc = (t, d) => { Model.Tables[t].Description = d; };
Action<string, string, string> CDesc = (t, c, d) => { Model.Tables[t].Columns[c].Description = d; };

TDesc("DimDate", "Conformed calendar, 2022-01-01 to 2027-06-30. Generated in SQL, not imported: the supplied calendar ended before the facts did. Marked as the model's date table. Financial year runs July to June.");
TDesc("DimProduct", "Product master, 1,000 SKUs. Only 500 carry inventory and demand history - see HasDemandSignal.");
TDesc("DimSupplier", "Supplier master, 120 suppliers. Relates to purchase orders only.");
TDesc("DimWarehouse", "Six distribution centres across four countries.");
TDesc("FactSalesOrders", "Grain: one row per sales order. 80,000 rows. Active date is OrderDate.");
TDesc("FactPurchaseOrders", "Grain: one row per purchase order. 25,000 rows. Active date is OrderDate.");
TDesc("FactShipments", "Grain: one row per shipment. 80,000 rows. Active date is ShipDate. ProductID is resolved from the sales order in the SQL view, so no fact-to-fact relationship is needed.");
TDesc("FactWeeklyDemand", "Grain: WeekStart x Product x Warehouse. Complete dense grid, 105 weeks x 500 products x 6 warehouses. BaselineForecastUnits is the locked forecasting benchmark.");
TDesc("FactInventorySnapshot", "Grain: SnapshotDate x Product x Warehouse. SEMI-ADDITIVE: never sum across time. Complete dense grid, 315,000 rows.");
TDesc("ModelConfig", "Disconnected configuration table. Supplies AsOfDate (2026-08-31) and other constants to DAX so they are not hard-coded across measures.");
TDesc("SecurityUserAccess", "Disconnected during Phase 5. Source for dynamic row-level security, implemented in a later phase.");

CDesc("DimDate", "Date", "Model date key. Unique, contiguous, no gaps.");
CDesc("DimDate", "IsOnOrBeforeAsOfDate", "True for dates on or before the 2026-08-31 as-of date. Use to exclude the forward horizon from historical visuals.");
CDesc("DimDate", "FinancialYear", "July-June financial year. July 2026 to June 2027 is FY27.");
CDesc("DimProduct", "HasDemandSignal", "True for the 500 products carrying inventory and demand history. Inventory, reorder and stockout measures are blank for the rest - by data coverage, not by fault.");
CDesc("DimProduct", "LeadTimeDays", "PLANNING lead time, used for reorder point. Distinct from actual supplier performance in FactPurchaseOrders[ActualLeadTimeDays].");
CDesc("DimProduct", "SafetyStockUnits", "Safety stock as supplied. A statistical alternative is evaluated in the inventory phase.");
CDesc("DimProduct", "UnitCost", "Also the basis for deriving inventory value: InventoryValue was dropped from the fact because it equals OnHandUnits x UnitCost exactly.");
CDesc("FactSalesOrders", "ActualDeliveryDate", "NULL while the order is open. Populated only for the 79,565 orders delivered on or before the as-of date.");
CDesc("FactSalesOrders", "ScheduledDeliveryDate", "NULL once delivered. Populated only for the 435 orders still in flight - an expectation, not a fact.");
CDesc("FactSalesOrders", "IsOpenOrder", "True for orders not yet due. EXCLUDE from OTIF: an order that is not due can be neither on time nor late.");
CDesc("FactSalesOrders", "DeliveryDelayDays", "Actual minus promised, in days. Positive means late. NULL while open.");
CDesc("FactPurchaseOrders", "ActualLeadTimeDays", "Order to receipt, in days. Supplier performance - not the planning lead time on DimProduct.");
CDesc("FactPurchaseOrders", "PurchasePriceVariance", "POValue minus QuantityOrdered x UnitCost. Genuine price variance: the two differ on 24,998 of 25,000 rows.");
CDesc("FactPurchaseOrders", "ScheduledReceiptDate", "Inbound pipeline. Populated only for the 368 open POs; feeds stockout risk analysis.");
CDesc("FactShipments", "SalesOrderID", "Degenerate identifier. Deliberately NOT related to FactSalesOrders - a fact-to-fact relationship would break the star schema.");
CDesc("FactInventorySnapshot", "OnHandUnits", "SEMI-ADDITIVE. May be summed across products and warehouses, never across time.");
CDesc("FactInventorySnapshot", "InboundUnits", "Stock in transit. Ranges 0-29 against on-hand reaching 4,186, so it barely moves reorder arithmetic in this dataset.");
CDesc("SecurityUserAccess", "IsAllWarehouses", "True for the Supply Director row, where WarehouseID holds the sentinel 'ALL'.");
L("  Descriptions applied to 11 tables and 17 columns");

L("");
L("=== FINAL STATE ===");
L("Tables: " + Model.Tables.Count);
L("Relationships: " + Model.Relationships.Count
    + "  (active " + Model.Relationships.Count(r => r.IsActive)
    + ", inactive " + Model.Relationships.Count(r => !r.IsActive) + ")");
var bidi = Model.Relationships.Count(r => r.CrossFilteringBehavior == CrossFilteringBehavior.BothDirections);
L("Bidirectional relationships: " + bidi + " (must be 0)");
L("Hierarchies: " + Model.Tables.Sum(t => t.Hierarchies.Count));
L("Hidden columns: " + Model.Tables.Sum(t => t.Columns.Count(c => c.IsHidden)));
L("Measures: " + Model.AllMeasures.Count() + " (none expected in Phase 5)");

// Log to the system temp folder rather than a machine-specific path, so the
// script is portable to any checkout of this repository.
var logPath = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "phase5_log.txt");
System.IO.File.WriteAllText(logPath, log.ToString());
