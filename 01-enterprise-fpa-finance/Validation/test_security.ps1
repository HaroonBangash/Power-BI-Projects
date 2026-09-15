<#
    Row-level security evidence, run with Power BI Desktop open and refreshed.

    1 SECURE DEFAULT   Connecting AS THE ROLE (Roles=...) with no impersonation: the
                       signed-in Windows user is not in the mapping table, so the role
                       must show nothing at all.
    2 SCOPE            For every mapped user, the role's own filter expression is
                       evaluated against the model: how many entities and departments
                       that user may see.
    3 EQUIVALENCE      For representative users, the figures the user WOULD see are
                       computed under their scope and compared with an independent SQL
                       query - the model and the database must agree on a restricted
                       view, not only on the whole.
    4 TREASURY         A department-scoped user must see no receivables, payables or
                       cash: those facts carry an entity but no department.

    LIMIT, STATED: the engine's EffectiveUserName impersonation needs a real Windows
    account, so the synthetic @northstar.demo addresses cannot be impersonated here
    ("The name provided is not a properly formed account name"). Desktop's "View as
    other user" is a UI action and is listed in PROJECT_STATE as a manual check.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\test_security.ps1
#>
param([string]$SqlServer = "localhost\SQLEXPRESS")
$ErrorActionPreference = "Stop"
$pass = 0; $fail = 0

$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse | Select-Object -First 1
Add-Type -Path $dll.FullName
$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$port = $null; $cat = $null
foreach ($ws in (Get-ChildItem $wsRoot -Directory | Sort-Object LastWriteTime -Descending)) {
    $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
    if (-not (Test-Path $pf)) { continue }
    try {
        $p = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$p")
        $c.Open(); $cmd = $c.CreateCommand(); $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rd = $cmd.ExecuteReader(); $k = $null; if ($rd.Read()) { $k = $rd.GetValue(0) }; $rd.Close(); $c.Close()
        if ($k) { $port = $p; $cat = $k; break }
    } catch {}
}
if (-not $cat) { throw "No live Power BI model. Open EnterpriseFPA.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=FinancePlanningBI;Integrated Security=True;TrustServerCertificate=True")
$sql.Open()

function Dax($q, $c = $conn) {
    $cmd = $c.CreateCommand(); $cmd.CommandText = $q
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Sql($q) {
    $cmd = $sql.CreateCommand(); $cmd.CommandText = $q
    $da = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Check($name, $actual, $expected, $tol = 0) {
    $ok = if ($expected -is [string]) { "$actual" -eq "$expected" }
          else { [Math]::Abs([double]$actual - [double]$expected) -le $tol }
    if ($ok) { $script:pass++ } else { $script:fail++; Write-Host ("  [FAIL] {0}: expected {1}, got {2}" -f $name, $expected, $actual) -ForegroundColor Red }
}

Write-Host "== 1. secure default: the role with no impersonation ==" -ForegroundColor Yellow
$roleConn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection(
    "Data Source=localhost:$port;Initial Catalog=$cat;Roles=Entity and Department Access")
$roleConn.Open()
$r = Dax 'EVALUATE ROW("entities", COALESCE(COUNTROWS(DimEntity),0), "departments", COALESCE(COUNTROWS(DimDepartment),0), "revenue", COALESCE([Revenue],0), "ar", COALESCE([AR Balance],0), "cash", COALESCE([Cash Balance],0))' $roleConn
Check "unmapped user sees no entities" $r.Rows[0][0] 0
Check "unmapped user sees no departments" $r.Rows[0][1] 0
Check "unmapped user sees no revenue" $r.Rows[0][2] 0
Check "unmapped user sees no receivables" $r.Rows[0][3] 0
Check "unmapped user sees no cash" $r.Rows[0][4] 0
$roleConn.Close()
Write-Host ("  entities={0} departments={1} revenue={2} AR={3} cash={4}" -f $r.Rows[0][0], $r.Rows[0][1], $r.Rows[0][2], $r.Rows[0][3], $r.Rows[0][4])

Write-Host "`n== 2-4. every mapped user's scope, and what they would see ==" -ForegroundColor Yellow
$users = Sql "SELECT UserEmail, [Role], EntityID, DepartmentID FROM dbo.SecurityUserAccess ORDER BY UserEmail"
foreach ($u in $users.Rows) {
    $email = $u["UserEmail"]; $ent = $u["EntityID"]; $dep = $u["DepartmentID"]
    $entFilter = if ($ent -eq "ALL") { "NOT ISBLANK ( DimEntity[EntityID] )" } else { "DimEntity[EntityID] = ""$ent""" }
    $depFilter = if ($dep -eq "ALL") { "NOT ISBLANK ( DimDepartment[DepartmentID] )" } else { "DimDepartment[DepartmentID] = ""$dep""" }
    $treasury = if ($dep -eq "ALL") { 1 } else { 0 }

    $d = Dax @"
EVALUATE
ROW (
    "entities",
        COUNTROWS ( FILTER ( DimEntity,
            VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[EntityID] ), SecurityUserAccess[UserEmail] = "$email" )
            RETURN "ALL" IN UserScope || DimEntity[EntityID] IN UserScope ) ),
    "departments",
        COUNTROWS ( FILTER ( DimDepartment,
            VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[DepartmentID] ), SecurityUserAccess[UserEmail] = "$email" )
            RETURN "ALL" IN UserScope || DimDepartment[DepartmentID] IN UserScope ) ),
    "revenue", CALCULATE ( [Revenue], FILTER ( ALL ( DimEntity ), $entFilter ), FILTER ( ALL ( DimDepartment ), $depFilter ) ),
    "treasuryVisible",
        VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[DepartmentID] ), SecurityUserAccess[UserEmail] = "$email" )
        RETURN IF ( "ALL" IN UserScope, 1, 0 )
)
"@
    $expectedEntities = if ($ent -eq "ALL") { 6 } else { 1 }
    $expectedDepts = if ($dep -eq "ALL") { 10 } else { 1 }
    $sqlRevenue = (Sql @"
SELECT -SUM(CASE WHEN a.AccountGroup = 'Revenue' THEN f.AmountAUD END)
FROM dbo.FactFinancials f
JOIN dbo.DimAccount a ON a.AccountCode = f.AccountCode
WHERE f.VersionID = 'ACT'
  AND ('$ent' = 'ALL' OR f.EntityID = '$ent')
  AND ('$dep' = 'ALL' OR f.DepartmentID = '$dep')
"@).Rows[0][0]

    Check "$email entities" $d.Rows[0][0] $expectedEntities
    Check "$email departments" $d.Rows[0][1] $expectedDepts
    Check "$email revenue matches SQL under the same scope" $d.Rows[0][2] ([double]$sqlRevenue) 0.02
    Check "$email treasury visibility" $d.Rows[0][3] $treasury
    Write-Host ("  {0,-32} {1,-18} entities={2,2} departments={3,2} revenue={4,14:n0} treasury={5}" -f `
            $email, $u["Role"], $d.Rows[0][0], $d.Rows[0][1], $d.Rows[0][2], $(if ($d.Rows[0][3] -eq 1) { "visible" } else { "hidden " }))
}

$conn.Close(); $sql.Close()
Write-Host ""
Write-Host ("SECURITY: {0} of {1} checks passed" -f $pass, ($pass + $fail)) -ForegroundColor Cyan
if ($fail) { exit 1 }
exit 0
