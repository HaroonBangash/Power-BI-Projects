// Class labels are measures, so they cannot serve as chart axes. Three small
// disconnected dimensions provide the axes; measures count the product grain
// against the value in context. Same pattern as ReplenishmentStatus.
var log = new System.Text.StringBuilder();
Action<string,string,string> Dim = (name, desc, data) => {
    if (Model.Tables.Contains(name)) Model.Tables[name].Delete();
    var t = Model.AddCalculatedTable(name, data);
    t.Description = desc;
    log.AppendLine("  " + name + " created");
};
Dim("ABCClass",
    "Disconnected dimension holding the three ABC value classes, so ABC can be used as a chart axis. Unrelated to any fact table.",
@"DATATABLE ( ""Class"", STRING, ""ClassOrder"", INTEGER,
  { { ""A"", 1 }, { ""B"", 2 }, { ""C"", 3 } } )");
Dim("XYZClass",
    "Disconnected dimension holding the three XYZ demand-variability classes. X is most predictable, Z most volatile.",
@"DATATABLE ( ""Class"", STRING, ""ClassOrder"", INTEGER,
  { { ""X"", 1 }, { ""Y"", 2 }, { ""Z"", 3 } } )");
Dim("ABCXYZClass",
    "Disconnected dimension holding the nine combined classes, ordered A-to-C then X-to-Z so the 3x3 matrix reads naturally.",
@"DATATABLE ( ""Class"", STRING, ""ABC"", STRING, ""XYZ"", STRING, ""ClassOrder"", INTEGER,
  { { ""AX"", ""A"", ""X"", 1 }, { ""AY"", ""A"", ""Y"", 2 }, { ""AZ"", ""A"", ""Z"", 3 },
    { ""BX"", ""B"", ""X"", 4 }, { ""BY"", ""B"", ""Y"", 5 }, { ""BZ"", ""B"", ""Z"", 6 },
    { ""CX"", ""C"", ""X"", 7 }, { ""CY"", ""C"", ""Y"", 8 }, { ""CZ"", ""C"", ""Z"", 9 } } )");
log.AppendLine("Tables: " + Model.Tables.Count);
System.IO.File.WriteAllText(System.IO.Path.Combine(System.IO.Path.GetTempPath(),"phase9b.txt"), log.ToString());
