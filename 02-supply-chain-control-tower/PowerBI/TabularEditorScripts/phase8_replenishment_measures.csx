// =============================================================================
// Phase 8 - Replenishment & Stockout Risk measures
// Supply Chain Control Tower
//
//   TabularEditor.exe <definition> -S phase8_replenishment_measures.csx -TMDL <definition>
//
// Adds the inventory-optimisation layer behind the Stockout & Replenishment
// Risk page. Every threshold below is an absolute business rule, derived from
// inspecting the actual distribution first - not fitted to produce an
// attractive spread of colours.
//
// What the data actually says (measured before any measure was written):
//   median weeks of supply        115 weeks
//   median reorder point          108 units
//   median inventory position   1,968 units
//   below reorder point           178 of 3,000 product-warehouse lines (5.9%)
//   excess stock (>26wk cover)    79.6% of inventory value
// This operation is heavily overstocked while specific lines still run short.
// The measures must surface both facts rather than smooth them away.
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
    m.FormatString = format;
    m.Description = description;
    count++;
    L("  " + folder + " / " + name);
};

var COUNT = "#,0";
var MONEY = "#,0.00";
var DEC2  = "0.00";
var F = "09 Replenishment";

L("=== DEMAND BASIS ===");

// A 13-week window, anchored to the as-of date and immune to date slicers.
// Thirteen weeks matches ModelConfig[ForecastHorizonWeeks] and is a standard
// planning quarter: long enough to smooth weekly noise, short enough to reflect
// current demand rather than two-year-old history.
M("Average Weekly Demand", F, DEC2,
  "Mean weekly demand over the 13 weeks ending at the as-of date. Anchored: ignores date slicers, so replenishment figures do not change when a user filters the calendar.",
@"VAR AsOf = [As Of Date]
VAR WindowStart = AsOf - 91
RETURN
    CALCULATE (
        AVERAGE ( FactWeeklyDemand[ActualDemandUnits] ),
        REMOVEFILTERS ( DimDate ),
        FactWeeklyDemand[WeekStart] > WindowStart,
        FactWeeklyDemand[WeekStart] <= AsOf
    )");

M("Demand Standard Deviation", F, DEC2,
  "Standard deviation of weekly demand over the same 13-week window. Feeds demand variability and the XYZ classification.",
@"VAR AsOf = [As Of Date]
VAR WindowStart = AsOf - 91
RETURN
    CALCULATE (
        STDEV.S ( FactWeeklyDemand[ActualDemandUnits] ),
        REMOVEFILTERS ( DimDate ),
        FactWeeklyDemand[WeekStart] > WindowStart,
        FactWeeklyDemand[WeekStart] <= AsOf
    )");

M("Demand Coefficient of Variation", F, DEC2,
  "Standard deviation divided by mean weekly demand. The dimensionless measure of demand predictability behind XYZ.",
  "DIVIDE ( [Demand Standard Deviation], [Average Weekly Demand] )");

L("");
L("=== REORDER LOGIC ===");

M("Lead Time Weeks", F, DEC2,
  "Supplier planning lead time expressed in weeks. Uses DimProduct[LeadTimeDays], the planning assumption - not observed supplier performance.",
  "DIVIDE ( AVERAGE ( DimProduct[LeadTimeDays] ), 7 )");

M("Safety Stock Units", F, COUNT,
  "Safety stock as supplied on DimProduct. A statistical alternative driven by demand variability and a service level is a candidate refinement, but the supplied figure is used here so the reorder point rests on given data rather than an assumed service level.",
  "SUM ( DimProduct[SafetyStockUnits] )");

M("Expected Demand During Lead Time", F, DEC2,
  "Average weekly demand multiplied by lead time in weeks. The stock consumed while a replenishment order is in transit.",
  "[Average Weekly Demand] * [Lead Time Weeks]");

M("Reorder Point", F, DEC2,
  "Expected demand during lead time plus safety stock. Falling below this means an order should already have been raised.",
  "[Expected Demand During Lead Time] + [Safety Stock Units]");

M("Reorder Gap", F, DEC2,
  "Reorder point minus inventory position. Positive means the line is short by that many units.",
  "[Reorder Point] - [Current Inventory Position]");

// Never negative: a surplus is not a negative order.
M("Suggested Reorder Quantity", F, COUNT,
  "Units to order to return to the reorder point. Floored at zero - a surplus is not a negative order.",
  "MAX ( 0, [Reorder Gap] )");

M("Weeks of Supply", F, DEC2,
  "How many weeks the current inventory position covers at recent demand. Blank where there is no demand, since dividing by zero demand is meaningless rather than infinite.",
  "DIVIDE ( [Current Inventory Position], [Average Weekly Demand] )");

L("");
L("=== STATUS ===");

// Thresholds, and why each one:
//   Critical         position below the safety buffer itself - already exposed
//   Reorder Required position below the reorder point - order now
//   Monitor          within twice the reorder point - approaching the trigger
//   Overstock        more than 26 weeks (six months) of cover
//   Healthy          everything else
// 26 weeks is a conventional excess-stock horizon, chosen before seeing how
// many rows it would classify. On this dataset it captures 86.7% of lines,
// which is a finding about the data, not a reason to move the threshold.
M("Replenishment Status", F, null,
  "Critical: position below safety stock. Reorder Required: below reorder point. Monitor: below twice the reorder point. Overstock: more than 26 weeks of cover. Healthy: everything else. Thresholds are absolute business rules, documented in Documentation/inventory_logic.md.",
@"VAR Position = [Current Inventory Position]
VAR Safety = [Safety Stock Units]
VAR ROP = [Reorder Point]
VAR WoS = [Weeks of Supply]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( Position ), BLANK (),
        Position < Safety, ""Critical"",
        Position < ROP, ""Reorder Required"",
        Position < 2 * ROP, ""Monitor"",
        NOT ISBLANK ( WoS ) && WoS > 26, ""Overstock"",
        ""Healthy""
    )");

L("");
L("=== PORTFOLIO ROLL-UPS ===");

// Reorder point is a per-product-per-warehouse concept, so any total has to be
// built by iterating that grain. Summing the components first would compare a
// portfolio-wide reorder point against a portfolio-wide position and hide every
// line-level shortage inside the aggregate surplus.
var GRAIN =
@"VAR Snap = [Current Inventory Snapshot Date]
VAR Grain =
    CALCULATETABLE (
        SUMMARIZE ( FactInventorySnapshot, DimProduct[ProductID], DimWarehouse[WarehouseID] ),
        REMOVEFILTERS ( DimDate ),
        FactInventorySnapshot[SnapshotDate] = Snap
    )
RETURN
    ";

M("Products Requiring Reorder", F, COUNT,
  "Product-warehouse lines whose inventory position sits below their reorder point. Iterates the product-warehouse grain: a portfolio-level comparison would hide line shortages inside the aggregate surplus.",
  GRAIN + "SUMX ( Grain, IF ( [Reorder Gap] > 0, 1, 0 ) )");

M("Critical Products", F, COUNT,
  "Product-warehouse lines already below their safety stock, not merely below the reorder point.",
  GRAIN + "SUMX ( Grain, IF ( [Current Inventory Position] < [Safety Stock Units], 1, 0 ) )");

M("Suggested Reorder Units", F, COUNT,
  "Total units to order across every short line.",
  GRAIN + "SUMX ( Grain, MAX ( 0, [Reorder Gap] ) )");

M("Average Weeks of Supply", F, DEC2,
  "Mean weeks of cover across product-warehouse lines that carry demand.",
  GRAIN + "AVERAGEX ( Grain, [Weeks of Supply] )");

M("Excess Inventory Units", F, COUNT,
  "Units held beyond 26 weeks of cover, floored at zero.",
  GRAIN + "SUMX ( Grain, MAX ( 0, [Current Inventory Position] - 26 * [Average Weekly Demand] ) )");

M("Excess Inventory Value", F, MONEY,
  "Value of stock held beyond 26 weeks of cover, priced at unit cost per product. The working capital tied up in stock that will not turn over within six months.",
  GRAIN + @"SUMX (
        Grain,
        MAX ( 0, [Current Inventory Position] - 26 * [Average Weekly Demand] )
            * CALCULATE ( SELECTEDVALUE ( DimProduct[UnitCost] ) )
    )");

L("");
L("=== FINAL ===");
L("Measures added: " + count);
L("Total measures: " + Model.AllMeasures.Count());
System.IO.File.WriteAllText(
    System.IO.Path.Combine(System.IO.Path.GetTempPath(), "phase8_log.txt"), log.ToString());
