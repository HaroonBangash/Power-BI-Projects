var log = new System.Text.StringBuilder();
if (Model.Tables.Contains("SupplierClass")) Model.Tables["SupplierClass"].Delete();
var t = Model.AddCalculatedTable("SupplierClass",
@"DATATABLE ( ""Class"", STRING, ""ClassOrder"", INTEGER,
  { { ""Excellent"", 1 }, { ""Good"", 2 },
    { ""Needs Improvement"", 3 }, { ""High Risk"", 4 } } )");
t.Description = "Disconnected dimension holding the four supplier performance classes, so class can serve as a chart axis. Unrelated to any fact table.";
log.AppendLine("SupplierClass created. Tables: " + Model.Tables.Count);
System.IO.File.WriteAllText(System.IO.Path.Combine(System.IO.Path.GetTempPath(),"p10b.txt"), log.ToString());
