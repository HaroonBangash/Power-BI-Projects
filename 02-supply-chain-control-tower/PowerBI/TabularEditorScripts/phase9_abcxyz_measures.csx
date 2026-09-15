// =============================================================================
// Phase 9 - ABC / XYZ Inventory Segmentation
// Supply Chain Control Tower
//
//   TabularEditor.exe <definition> -S phase9_abcxyz_measures.csx -TMDL <definition>
//
// GRAIN. Both classifications are PRODUCT level. Demand is stored at
// product x warehouse x week, so the XYZ measures sum to product x week FIRST.
// Computing CV at product-warehouse grain and pairing it with product-level ABC
// would be a silent grain mismatch: the two classes could not honestly be
// combined. It also changes the answer materially - product-warehouse CV runs
// roughly twice product-level CV, because summing six warehouses smooths noise.
//
// THRESHOLD STABILITY. XYZ boundaries are derived from the complete eligible
// portfolio using REMOVEFILTERS, so a Category slicer cannot silently redefine
// what X, Y and Z mean. They are computed, never hard-coded, so they follow the
// data if it changes.
//
// Measured from the live source before implementation:
//   ABC   A 512 (79.99% of revenue) | B 279 (14.98%) | C 209 (5.04%)
//         513 products reach 80% of revenue - matching the Phase 2 audit
//   XYZ   500 products with demand history, CV range 0.0560 - 0.3512
//         P33 = 0.129674   P66 = 0.170917
//   500 products carry no demand history and are explicitly Unclassified.
// =============================================================================

var log = new System.Text.StringBuilder();
Action<string> L = s => log.AppendLine(s);
var mt = Model.Tables["_Measures"];
int count = 0;
Action<string, string, string, string, string> M =
    (name, folder, format, description, dax) =>
{
    if (mt.Measures.Contains(name)) mt.Measures[name].Delete();
    var m = mt.AddMeasure(name, dax, folder);
    if (format != null) m.FormatString = format;
    m.Description = description;
    count++;
    L("  " + name);
};

var COUNT = "#,0";
var MONEY = "#,0.00";
var PCT   = "0.0%";
var CV4   = "0.0000";
var F = "10 ABC / XYZ";

// The 13-week window, matching the replenishment layer and ForecastHorizonWeeks.
var WEEKLY_TOTALS =
@"VAR AsOf = [As Of Date]
VAR WindowStart = AsOf - 91
VAR WeeklyTotals =
    CALCULATETABLE (
        ADDCOLUMNS (
            SUMMARIZE ( FactWeeklyDemand, FactWeeklyDemand[WeekStart] ),
            ""@Units"", CALCULATE ( SUM ( FactWeeklyDemand[ActualDemandUnits] ) )
        ),
        REMOVEFILTERS ( DimDate ),
        FactWeeklyDemand[WeekStart] > WindowStart,
        FactWeeklyDemand[WeekStart] <= AsOf
    )
RETURN
    ";

L("=== PRODUCT-LEVEL DEMAND ===");

M("Product Average Weekly Demand", F, "0.00",
  "Mean weekly demand for a product, summed across warehouses first. Distinct from [Average Weekly Demand], which works at product-warehouse grain for replenishment.",
  WEEKLY_TOTALS + "AVERAGEX ( WeeklyTotals, [@Units] )");

M("Product Demand Std Dev", F, "0.00",
  "Standard deviation of a product's total weekly demand across the 13-week window.",
  WEEKLY_TOTALS + "STDEVX.S ( WeeklyTotals, [@Units] )");

M("Product Demand CV", F, CV4,
  "Coefficient of variation of product-level weekly demand: standard deviation divided by mean. Blank where mean demand is zero - dividing by no demand is meaningless, not infinite.",
  "DIVIDE ( [Product Demand Std Dev], [Product Average Weekly Demand] )");

L("");
L("=== XYZ THRESHOLDS - computed, portfolio-stable ===");

// REMOVEFILTERS across the model so the boundaries describe the whole eligible
// portfolio. Without it, a Category slicer would redefine X, Y and Z and the
// class labels would mean something different on every page state.
var CV_POP =
@"VAR Population =
    FILTER (
        ADDCOLUMNS (
            CALCULATETABLE ( VALUES ( DimProduct[ProductID] ), REMOVEFILTERS () ),
            ""@CV"", [Product Demand CV]
        ),
        NOT ISBLANK ( [@CV] )
    )
RETURN
    ";

M("XYZ P33 Threshold", F, CV4,
  "Lower tercile of product demand CV across the whole eligible portfolio. Computed, not hard-coded, and deliberately immune to report filters so class meaning stays stable.",
  CV_POP + "PERCENTILEX.INC ( Population, [@CV], DIVIDE ( 1, 3 ) )");

M("XYZ P66 Threshold", F, CV4,
  "Upper tercile of product demand CV across the whole eligible portfolio.",
  CV_POP + "PERCENTILEX.INC ( Population, [@CV], DIVIDE ( 2, 3 ) )");

L("");
L("=== ABC ===");

// Contribution is measured against ALLSELECTED, so external slicers such as
// Category define the comparison population while the product's own row context
// is removed. Without removing it every product would show 100% contribution.
var REV_POP =
@"VAR Population =
    ADDCOLUMNS ( ALLSELECTED ( DimProduct[ProductID] ), ""@Rev"", [Total Revenue] )
VAR TotalRev = SUMX ( Population, [@Rev] )
VAR ThisRev = [Total Revenue]
RETURN
    ";

M("Product Revenue Contribution %", F, PCT,
  "A product's share of revenue across the selected comparison population.",
  REV_POP + "DIVIDE ( ThisRev, TotalRev )");

M("Product Revenue Rank", F, COUNT,
  "Revenue rank within the selected population, highest first.",
  "RANKX ( ALLSELECTED ( DimProduct[ProductID] ), [Total Revenue], , DESC, DENSE )");

M("Cumulative Revenue %", F, PCT,
  "Running share of revenue for this product and every product ranked above it. The basis of the ABC boundary.",
  REV_POP + @"IF (
        NOT ISBLANK ( ThisRev ),
        DIVIDE ( SUMX ( FILTER ( Population, [@Rev] >= ThisRev ), [@Rev] ), TotalRev )
    )");

// 80 / 95 describe VALUE contribution, not an expected share of products. On
// this catalogue class A holds 51.2% of products because that is genuinely how
// many are needed to reach 80% of revenue. Forcing a 20/30/50 split would be
// fabricating a Pareto curve the data does not have.
M("ABC Class", F, null,
  "A: products making up the first 80% of cumulative revenue. B: next 15%. C: remainder. Thresholds describe value contribution, not a target share of products - on this catalogue A holds 51.2% of SKUs, which is the real distribution.",
@"VAR Cum = [Cumulative Revenue %]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( Cum ), BLANK (),
        Cum <= 0.80, ""A"",
        Cum <= 0.95, ""B"",
        ""C""
    )");

L("");
L("=== XYZ AND COMBINED ===");

M("XYZ Class", F, null,
  "X: lowest third of demand variability, most predictable. Y: middle third. Z: highest third, most volatile. Boundaries are measured terciles of the portfolio CV distribution, because generic cut-offs such as X<0.5 would classify every product here as X.",
@"VAR CV = [Product Demand CV]
VAR P33 = [XYZ P33 Threshold]
VAR P66 = [XYZ P66 Threshold]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( CV ), BLANK (),
        CV <= P33, ""X"",
        CV <= P66, ""Y"",
        ""Z""
    )");

// A product with no demand history gets no XYZ, and therefore no combined
// class. It is never defaulted to X: that would invent predictability from
// absent data.
M("ABC XYZ Class", F, null,
  "Combined class, only where both parts are valid. Products with no demand history stay unclassified rather than being defaulted into X.",
@"VAR A = [ABC Class]
VAR X = [XYZ Class]
RETURN
    IF ( NOT ISBLANK ( A ) && NOT ISBLANK ( X ), A & X )");

L("");
L("=== CLASS COUNTS via the disconnected dimensions ===");

var PRODUCTS = "VALUES ( DimProduct[ProductID] )";

M("Products at ABC Class", F, COUNT,
  "Products in the ABC class in context. Without a class filter, every product with revenue.",
@"VAR Sel = SELECTEDVALUE ( ABCClass[Class] )
RETURN
    SUMX (
        " + PRODUCTS + @",
        IF (
            IF ( ISBLANK ( Sel ), NOT ISBLANK ( [ABC Class] ), [ABC Class] = Sel ),
            1,
            0
        )
    )");

M("Products at XYZ Class", F, COUNT,
  "Products in the XYZ class in context. Without a class filter, every product carrying demand history.",
@"VAR Sel = SELECTEDVALUE ( XYZClass[Class] )
RETURN
    SUMX (
        " + PRODUCTS + @",
        IF (
            IF ( ISBLANK ( Sel ), NOT ISBLANK ( [XYZ Class] ), [XYZ Class] = Sel ),
            1,
            0
        )
    )");

M("Products at ABCXYZ Class", F, COUNT,
  "Products in the combined class in context. The value behind each cell of the 3x3 matrix.",
@"VAR Sel = SELECTEDVALUE ( ABCXYZClass[Class] )
RETURN
    SUMX (
        " + PRODUCTS + @",
        IF (
            IF ( ISBLANK ( Sel ), NOT ISBLANK ( [ABC XYZ Class] ), [ABC XYZ Class] = Sel ),
            1,
            0
        )
    )");

M("Revenue at ABC Class", F, MONEY,
  "Revenue attributable to the ABC class in context.",
@"VAR Sel = SELECTEDVALUE ( ABCClass[Class] )
RETURN
    SUMX (
        " + PRODUCTS + @",
        IF ( ISBLANK ( Sel ) || [ABC Class] = Sel, [Total Revenue], 0 )
    )");

M("Inventory Value at ABCXYZ Class", F, MONEY,
  "Current inventory value held in the combined class in context. Shows where working capital sits across the strategy grid.",
@"VAR Sel = SELECTEDVALUE ( ABCXYZClass[Class] )
RETURN
    SUMX (
        " + PRODUCTS + @",
        IF ( ISBLANK ( Sel ) || [ABC XYZ Class] = Sel, [Current Inventory Value], 0 )
    )");

L("");
L("=== HEADLINE KPIs ===");

Action<string, string, string, string> KPI = (name, cls, expr, desc) =>
    M(name, F, COUNT, desc,
      "SUMX ( " + PRODUCTS + ", IF ( " + expr + ", 1, 0 ) )");

KPI("A-Class Products", "A", "[ABC Class] = \"A\"",
    "Products in the first 80% of cumulative revenue.");
KPI("B-Class Products", "B", "[ABC Class] = \"B\"", "Products in the next 15% of revenue.");
KPI("C-Class Products", "C", "[ABC Class] = \"C\"", "Products in the remaining 5% of revenue.");
KPI("X-Class Products", "X", "[XYZ Class] = \"X\"", "Most predictable third of demand.");
KPI("Y-Class Products", "Y", "[XYZ Class] = \"Y\"", "Middle third of demand variability.");
KPI("Z-Class Products", "Z", "[XYZ Class] = \"Z\"", "Most volatile third of demand.");
KPI("AZ Products", "AZ", "[ABC XYZ Class] = \"AZ\"",
    "High financial importance with volatile demand. The group needing the closest forecasting and inventory attention.");
KPI("Unclassified Products", "", "ISBLANK ( [XYZ Class] ) && NOT ISBLANK ( [ABC Class] )",
    "Products with revenue but no weekly demand history, so no XYZ class can be assigned. Counted explicitly rather than hidden or defaulted into X.");

M("A-Class Inventory Value", F, MONEY,
  "Current inventory value held in class A products - the working capital tied to the products that drive 80% of revenue.",
  "SUMX ( " + PRODUCTS + ", IF ( [ABC Class] = \"A\", [Current Inventory Value], 0 ) )");

L("");
L("Measures added: " + count);
L("Total measures: " + Model.AllMeasures.Count());
System.IO.File.WriteAllText(
    System.IO.Path.Combine(System.IO.Path.GetTempPath(), "phase9_log.txt"), log.ToString());
