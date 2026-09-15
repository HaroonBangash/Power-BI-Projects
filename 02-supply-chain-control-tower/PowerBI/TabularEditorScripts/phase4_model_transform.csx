// =============================================================================
// Phase 4 semantic-model transformation
// Supply Chain Control Tower
//
// Executed via Tabular Editor 2 against the PBIP TMDL definition folder.
// Tabular Editor owns TMDL serialisation, so file naming, object references
// and the model manifest stay internally consistent - no hand-edited text.
//
// Note: TE2's script compiler predates C# local functions, so helpers are
// declared as delegates rather than methods.
// =============================================================================

var log = new System.Text.StringBuilder();
Action<string> L = s => log.AppendLine(s);

L("=== 1. REMOVE AUTO DATE/TIME ===");

// Power BI's auto date/time built one hidden calendar per date column: 18
// LocalDateTable_* plus a DateTableTemplate_*, wired up with 18 relationships
// and a 'variation' on every date column. DimDate already provides ISO weeks,
// financial year and sort keys that these tables lack, so they are pure bloat.
// Variations are cleared first: they reference the hidden tables, and deleting
// a table out from under a live reference is what corrupts a model.
int varsCleared = 0;
foreach (var t in Model.Tables)
    foreach (var c in t.Columns)
        foreach (var v in c.Variations.ToList()) { v.Delete(); varsCleared++; }
L("Variations cleared: " + varsCleared);

int relsDeleted = Model.Relationships.Count;
foreach (var r in Model.Relationships.ToList()) r.Delete();
L("Relationships deleted: " + relsDeleted);

int autoTables = 0;
foreach (var t in Model.Tables.ToList())
    if (t.Name.StartsWith("LocalDateTable_") || t.Name.StartsWith("DateTableTemplate_"))
    {
        L("  drop " + t.Name);
        t.Delete();
        autoTables++;
    }
L("Auto date tables deleted: " + autoTables);

Model.SetAnnotation("__PBI_TimeIntelligenceEnabled", "0");
L("__PBI_TimeIntelligenceEnabled -> 0");

L("");
L("=== 2. RENAME FACT TABLES ===");

// Renaming now is maximally safe: no measures, relationships or report visuals
// reference these tables yet, so nothing can be left dangling.
var renames = new Dictionary<string, string> {
    { "InventorySnapshot", "FactInventorySnapshot" },
    { "SalesOrders",       "FactSalesOrders"       },
    { "PurchaseOrders",    "FactPurchaseOrders"    },
    { "Shipments",         "FactShipments"         },
    { "WeeklyDemand",      "FactWeeklyDemand"      }
};
foreach (var kv in renames)
{
    var t = Model.Tables[kv.Key];
    t.Name = kv.Value;
    // Keep the partition name aligned with the table it belongs to.
    foreach (var p in t.Partitions) p.Name = kv.Value;
    L("  " + kv.Key + " -> " + kv.Value);
}

L("");
L("=== 3. CREATE RANGESTART / RANGEEND PARAMETERS ===");

// Shared M parameters for the incremental-refresh policy configured in Phase 21.
// The meta record is what makes Power BI treat these as parameters rather than
// plain expressions; Type="DateTime" is required for an incremental refresh
// policy to bind to them.
Action<string, string, string> AddParam = (name, dt, desc) =>
{
    if (Model.Expressions.Contains(name)) Model.Expressions[name].Delete();
    var e = Model.AddExpression(name);
    // Assign the expression explicitly rather than via the AddExpression
    // overload: the overload left it empty when tested.
    e.Expression = dt + " meta [IsParameterQuery=true, Type=\"DateTime\", IsParameterQueryRequired=true]";
    e.Kind = ExpressionKind.M;
    e.Description = desc;
    L("  " + name + " = " + e.Expression);
};
AddParam("RangeStart", "#datetime(2026, 1, 1, 0, 0, 0)",
    "Incremental refresh lower bound (inclusive). Development value only; the Service overrides it at refresh time. Not yet applied to any table filter.");
AddParam("RangeEnd", "#datetime(2026, 9, 1, 0, 0, 0)",
    "Incremental refresh upper bound (exclusive). Development value only; the Service overrides it at refresh time. Not yet applied to any table filter.");

L("");
L("=== 4. MONEY COLUMNS -> FIXED DECIMAL ===");

// The SQL source types these decimal(18,2); the connector mapped them to Double
// (floating point). Currency belongs in Fixed Decimal: exact arithmetic, no
// binary rounding drift across 80,000-row sums, and better compression.
// No currency symbol is applied - the dataset does not state a currency.
var money = new[] {
    "DimProduct|UnitCost", "DimProduct|UnitPrice",
    "FactSalesOrders|Revenue",
    "FactPurchaseOrders|POValue", "FactPurchaseOrders|ExpectedPOValue",
    "FactPurchaseOrders|PurchasePriceVariance",
    "FactShipments|FreightCost"
};
foreach (var m in money)
{
    var p = m.Split('|');
    var c = Model.Tables[p[0]].Columns[p[1]];
    c.DataType = DataType.Decimal;
    c.FormatString = "#,0.00";
    // Drop the stale hint left over from the Double mapping; it would otherwise
    // compete with the explicit format string.
    if (c.GetAnnotation("PBI_FormatHint") != null) c.RemoveAnnotation("PBI_FormatHint");
    L("  " + m.Replace("|", ".") + "  double -> decimal");
}

L("");
L("=== 5. SUMMARIZEBY -> NONE ON NON-ADDITIVE COLUMNS ===");

// Left as 'sum', dragging DimDate[Year] onto a card reports 4,058,127.
// Aggregation for these belongs in explicit measures built in Phase 6.
// Genuinely additive columns (Revenue, POValue, FreightCost, unit counts,
// PurchasePriceVariance) deliberately keep SUM.
var nonAdditive = new[] {
    "DimDate|DateKey","DimDate|Year","DimDate|Quarter","DimDate|YearQuarterKey",
    "DimDate|MonthNumber","DimDate|YearMonthKey","DimDate|ISOYear","DimDate|ISOWeek",
    "DimDate|ISOYearWeekKey","DimDate|DayOfMonth","DimDate|DayOfWeekISO",
    "DimDate|FinancialYearNumber","DimDate|FinancialQuarter","DimDate|FinancialMonthNumber",
    "DimProduct|UnitCost","DimProduct|UnitPrice","DimProduct|LeadTimeDays","DimProduct|SafetyStockUnits",
    "FactSalesOrders|DeliveryDelayDays",
    "FactPurchaseOrders|DefectRate","FactPurchaseOrders|ActualLeadTimeDays","FactPurchaseOrders|ReceiptDelayDays",
    "FactShipments|TransitDays"
};
foreach (var m in nonAdditive)
{
    var p = m.Split('|');
    Model.Tables[p[0]].Columns[p[1]].SummarizeBy = AggregateFunction.None;
}
L("Columns set to SummarizeBy=None: " + nonAdditive.Length);

L("");
L("=== 6. DATE FORMAT -> ISO ===");

// 'Long Date' renders "Monday, 31 August 2026" in every visual. This solution
// spans Australia, New Zealand, Singapore and the UAE, so an ISO format avoids
// the dd/mm versus mm/dd ambiguity entirely.
int dateCols = 0;
foreach (var t in Model.Tables)
    foreach (var c in t.Columns)
        if (c.DataType == DataType.DateTime)
        {
            c.FormatString = "yyyy-mm-dd";
            dateCols++;
        }
L("Date columns reformatted: " + dateCols);

L("");
L("=== 7. REFRESH QUERY ORDER ANNOTATION ===");
var order = new List<string>();
foreach (var t in Model.Tables.OrderBy(x => x.Name)) order.Add("\"" + t.Name + "\"");
Model.SetAnnotation("PBI_QueryOrder", "[" + string.Join(",", order) + "]");
L("PBI_QueryOrder rewritten with " + order.Count + " tables");

L("");
L("=== FINAL STATE ===");
L("Tables: " + Model.Tables.Count);
foreach (var t in Model.Tables.OrderBy(x => x.Name)) L("  " + t.Name + " (" + t.Columns.Count + " cols)");
L("Relationships: " + Model.Relationships.Count);
L("Expressions: " + Model.Expressions.Count);
foreach (var e in Model.Expressions) L("  " + e.Name + " = " + e.Expression);
L("TimeIntelligence annotation: " + Model.GetAnnotation("__PBI_TimeIntelligenceEnabled"));

System.IO.File.WriteAllText(@"D:\pbitmp\transform_log.txt", log.ToString());
