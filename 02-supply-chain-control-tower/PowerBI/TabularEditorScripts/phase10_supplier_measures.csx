// =============================================================================
// Phase 10 - Supplier Performance scoring
// Supply Chain Control Tower
//
//   TabularEditor.exe <definition> -S phase10_supplier_measures.csx -TMDL <definition>
//
// THE SCORE HAS THREE COMPONENTS, NOT FOUR.
// The dataset records no received or fulfilled quantity, so fulfilment
// performance cannot be measured. Rather than invent a fourth component, the
// weight is redistributed across what is genuinely measurable and the omission
// is stated. Nothing here is called OTIF.
//
// WEIGHTS - 45 / 35 / 20, chosen after measuring each distribution:
//   45%  On-Time Receipt Performance   raw spread 0.286 - 0.520
//   35%  Lead-Time Reliability         raw spread 3.49 - 10.40 days std dev
//   20%  Quality (defect rate)         raw spread 0.0294 - 0.0364
//
// The suggested 40/30/30 was not used. Defect rate varies by only 0.7
// percentage points across all 120 suppliers, so min-max normalisation
// stretches near-noise across a full 0-1 range. A 30% weight would let that
// noise drive nearly a third of the score. It keeps a real 20% because quality
// is a genuine supplier obligation, but it should not outvote delivery
// performance that varies twenty times more widely.
//
// RELIABILITY IS CONSISTENCY, NOT SPEED. Lead-Time Reliability scores the
// standard deviation of actual lead time, not its average. A long but
// predictable lead time can be planned around; an erratic one cannot. Average
// lead time is reported alongside as description, not scored.
//
// NORMALISATION. Min-max across the whole supplier population using
// REMOVEFILTERS, so a slicer cannot silently rescale the score and change what
// "Excellent" means. Every component is oriented so higher is better.
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
var DEC2  = "0.00";
var SCORE = "0.0";
var F = "11 Supplier Performance";

L("=== RAW SUPPLIER METRICS ===");

M("Total Suppliers", F, COUNT,
  "Distinct suppliers in the current filter context.",
  "DISTINCTCOUNT ( FactPurchaseOrders[SupplierID] )");

M("Supplier Lead Time Variability", F, DEC2,
  "Standard deviation of actual order-to-receipt days across RECEIVED purchase orders. Consistency, not speed: an erratic supplier cannot be planned around even if fast on average.",
  "CALCULATE ( STDEV.S ( FactPurchaseOrders[ActualLeadTimeDays] ), FactPurchaseOrders[IsReceived] = TRUE () )");

M("Average Defect Rate", F, "0.00%",
  "Mean defect rate across purchase orders. Note the whole supplier base spans only 2.94% to 3.64%, so differences between suppliers are small in absolute terms.",
  "AVERAGE ( FactPurchaseOrders[DefectRate] )");

L("");
L("=== NORMALISED COMPONENTS - each 0 to 1, higher is better ===");

// Population bounds are taken across every supplier with REMOVEFILTERS, so the
// scale is stable: filtering to one category cannot rescale the score and turn
// a mid-table supplier into an apparent leader.
Func<string, string, string> NORM = (metric, higherIsBetter) =>
@"VAR Population =
    ADDCOLUMNS (
        CALCULATETABLE ( VALUES ( DimSupplier[SupplierID] ), REMOVEFILTERS () ),
        ""@V"", " + metric + @"
    )
VAR Lo = MINX ( Population, [@V] )
VAR Hi = MAXX ( Population, [@V] )
VAR This = " + metric + @"
VAR Scaled = DIVIDE ( This - Lo, Hi - Lo )
RETURN
    IF ( NOT ISBLANK ( This ), " + (higherIsBetter == "yes" ? "Scaled" : "1 - Scaled") + " )";

M("On-Time Receipt Score", F, DEC2,
  "On-time receipt performance normalised across the supplier population. 1 is the best performer, 0 the worst.",
  NORM("[On-Time Receipt %]", "yes"));

M("Lead-Time Reliability Score", F, DEC2,
  "Lead-time consistency normalised across the population, inverted so that low variability scores high.",
  NORM("[Supplier Lead Time Variability]", "no"));

M("Quality Score", F, DEC2,
  "Defect rate normalised across the population and inverted so that low defects score high. The underlying spread is only 0.7 percentage points, so this component separates suppliers weakly in absolute terms.",
  NORM("[Average Defect Rate]", "no"));

L("");
L("=== COMPOSITE SCORE ===");

M("Supplier Performance Score", F, SCORE,
  "Weighted composite on a 0-100 scale: 45% on-time receipt, 35% lead-time reliability, 20% quality. Higher is always better. There is no fulfilment component - the dataset records no received quantity, so it cannot be measured and is not invented.",
@"VAR OnTime = [On-Time Receipt Score]
VAR Reliability = [Lead-Time Reliability Score]
VAR Quality = [Quality Score]
RETURN
    IF (
        NOT ISBLANK ( OnTime ),
        100 * ( 0.45 * OnTime + 0.35 * Reliability + 0.20 * Quality )
    )");

M("Supplier Rank", F, COUNT,
  "Rank by performance score within the selected supplier population, best first.",
  "RANKX ( ALLSELECTED ( DimSupplier[SupplierID] ), [Supplier Performance Score], , DESC, DENSE )");

// Round cut points on a normalised 0-100 scale, deliberately NOT percentiles:
// percentiles would force equal group sizes and hide the fact that most of this
// supplier base performs moderately.
M("Supplier Performance Class", F, null,
  "Excellent 70+, Good 55-69, Needs Improvement 40-54, High Risk below 40. Round cut points on the normalised scale rather than percentiles, so class sizes reflect real performance rather than being forced equal.",
@"VAR S = [Supplier Performance Score]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( S ), BLANK (),
        S >= 70, ""Excellent"",
        S >= 55, ""Good"",
        S >= 40, ""Needs Improvement"",
        ""High Risk""
    )");

L("");
L("=== PORTFOLIO ROLL-UPS ===");

var SUPPLIERS = "VALUES ( DimSupplier[SupplierID] )";

M("Average Supplier Score", F, SCORE,
  "Mean performance score across suppliers in context. Averaged over suppliers, not over purchase orders, so a high-volume supplier does not dominate.",
  "AVERAGEX ( " + SUPPLIERS + ", [Supplier Performance Score] )");

Action<string, string, string> CLS = (name, cls, desc) =>
    M(name, F, COUNT, desc,
      "SUMX ( " + SUPPLIERS + ", IF ( [Supplier Performance Class] = \"" + cls + "\", 1, 0 ) )");

CLS("Excellent Suppliers", "Excellent", "Suppliers scoring 70 or above.");
CLS("High-Risk Suppliers", "High Risk", "Suppliers scoring below 40 - the group creating most operational risk.");

M("Suppliers at Class", F, COUNT,
  "Suppliers in the performance class in context. Without a class filter, every scored supplier.",
@"VAR Sel = SELECTEDVALUE ( SupplierClass[Class] )
RETURN
    SUMX (
        " + SUPPLIERS + @",
        IF (
            IF ( ISBLANK ( Sel ), NOT ISBLANK ( [Supplier Performance Class] ),
                 [Supplier Performance Class] = Sel ),
            1, 0
        )
    )");

M("PO Value at Supplier Class", F, MONEY,
  "Purchase-order value placed with suppliers in the class in context. Shows whether spend is concentrated among strong or weak suppliers.",
@"VAR Sel = SELECTEDVALUE ( SupplierClass[Class] )
RETURN
    SUMX (
        " + SUPPLIERS + @",
        IF ( ISBLANK ( Sel ) || [Supplier Performance Class] = Sel, [Purchase Order Value], 0 )
    )");

L("");
L("Measures added: " + count);
L("Total measures: " + Model.AllMeasures.Count());
System.IO.File.WriteAllText(
    System.IO.Path.Combine(System.IO.Path.GetTempPath(), "phase10_log.txt"), log.ToString());
