<#
    Parses the generated TMDL folder with the Tabular deserialiser BEFORE Power BI
    opens it. Power BI Desktop reacts to a malformed TMDL by opening a blank
    "Untitled" document with no error on screen, so this is the only cheap way to
    see the actual message - it names the document, line number and line.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\parse_tmdl.ps1
#>
$ErrorActionPreference = "Stop"
$binn = "C:\Program Files\Microsoft SQL Server\170\DTS\Binn"
$dll = Join-Path $binn "Microsoft.AnalysisServices.Tabular.dll"
if (-not (Test-Path $dll)) { throw "Tabular assembly not found at $dll" }
Add-Type -Path $dll
$path = (Join-Path $PSScriptRoot "..\PowerBI\EnterpriseFPA.SemanticModel\definition" | Resolve-Path).Path

try {
    $db = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder($path)
} catch {
    Write-Host "TMDL PARSE FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit 1
}
$m = $db.Model
$groups = @($m.Tables | Where-Object { $null -ne $_.CalculationGroup })
$measures = ($m.Tables | ForEach-Object { $_.Measures.Count } | Measure-Object -Sum).Sum
$columns = ($m.Tables | ForEach-Object { $_.Columns.Count } | Measure-Object -Sum).Sum
Write-Host ("TMDL parses: {0} tables ({1} calculation groups), {2} columns, {3} measures, {4} relationships, {5} role(s)" -f `
        $m.Tables.Count, $groups.Count, $columns, $measures, $m.Relationships.Count, $m.Roles.Count) -ForegroundColor Green
foreach ($g in $groups) {
    Write-Host ("  {0,-14} precedence {1,3}  items: {2}" -f $g.Name, $g.CalculationGroup.Precedence,
        (($g.CalculationGroup.CalculationItems | ForEach-Object { $_.Name }) -join ", "))
}
foreach ($r in $m.Roles) { Write-Host ("  role {0}: {1} table permissions" -f $r.Name, $r.TablePermissions.Count) }
exit 0
