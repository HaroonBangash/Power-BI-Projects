// Replenishment status is a MEASURE, so it cannot be a chart axis. The standard
// pattern is a small disconnected dimension holding the status values, plus a
// measure that counts grain rows matching the value in context.
var log = new System.Text.StringBuilder();
if (Model.Tables.Contains("ReplenishmentStatus")) Model.Tables["ReplenishmentStatus"].Delete();
var t = Model.AddCalculatedTable("ReplenishmentStatus",
@"DATATABLE (
    ""Status"", STRING,
    ""StatusOrder"", INTEGER,
    {
        { ""Critical"", 1 },
        { ""Reorder Required"", 2 },
        { ""Monitor"", 3 },
        { ""Healthy"", 4 },
        { ""Overstock"", 5 }
    }
)");
t.Description = "Disconnected dimension listing the five replenishment statuses, so status can be used as a chart axis. Deliberately unrelated to any fact table.";
foreach (var c in t.Columns) if (c.Name == "StatusOrder") c.IsHidden = true;
log.AppendLine("ReplenishmentStatus table created with " + t.Columns.Count + " columns");

var mt = Model.Tables["_Measures"];
if (mt.Measures.Contains("Lines at Status")) mt.Measures["Lines at Status"].Delete();
var m = mt.AddMeasure("Lines at Status",
@"VAR Sel = SELECTEDVALUE ( ReplenishmentStatus[Status] )
VAR Snap = [Current Inventory Snapshot Date]
VAR Grain =
    CALCULATETABLE (
        SUMMARIZE ( FactInventorySnapshot, DimProduct[ProductID], DimWarehouse[WarehouseID] ),
        REMOVEFILTERS ( DimDate ),
        FactInventorySnapshot[SnapshotDate] = Snap
    )
RETURN
    IF (
        NOT ISBLANK ( Sel ),
        SUMX ( Grain, IF ( [Replenishment Status] = Sel, 1, 0 ) ),
        COUNTROWS ( Grain )
    )", "09 Replenishment");
m.FormatString = "#,0";
m.Description = "Count of product-warehouse lines at the replenishment status in context. Without a status filter it returns every line.";
log.AppendLine("Measure 'Lines at Status' added");
log.AppendLine("Total measures: " + Model.AllMeasures.Count());
System.IO.File.WriteAllText(System.IO.Path.Combine(System.IO.Path.GetTempPath(), "phase8b.txt"), log.ToString());
