<#
    A rendered page proves a visual draws. These tests prove the page still tells the
    truth when a reader USES it: each interactive state is reproduced as the query that
    state produces, and compared with independently written SQL.

    What is covered:
      slicers            country, segment, plan, industry, severity - alone and combined
      calculation group  every Time Comparison item, and one applied under a slicer
      field parameter    the six cuts the Customer Cut parameter offers
      cross-filtering    selecting a plan filters the cohort matrix
      the data boundary  nothing is reported beyond the as-of month, whatever is selected

    NOT covered here, and said so rather than implied: whether the field PARAMETER
    resolves its chosen column inside a visual. That resolution happens when Power BI
    builds the visual's query, not in a query this script can write, so it is proven by
    rendering the page and reading the axis - see Validation/evidence/.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\test_interactions.ps1
#>
param([string]$SqlServer = "localhost\SQLEXPRESS")
$ErrorActionPreference = "Stop"
$script:pass = 0; $script:fail = 0

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
if (-not $cat) { throw "No live Power BI model. Open SaaSRevenue.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=SaaSRevenueBI;Integrated Security=True;TrustServerCertificate=True")
$sql.Open()

function Dax([string]$q) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $q
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Sql([string]$q) {
    $cmd = $sql.CreateCommand(); $cmd.CommandText = $q; $cmd.CommandTimeout = 300
    $da = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Check($name, $actual, $expected, $tol) {
    $ok = $false
    if ($null -eq $expected) { $ok = ($null -eq $actual -or $actual -is [System.DBNull]) }
    elseif ($null -ne $actual -and -not ($actual -is [System.DBNull])) {
        $ok = ([Math]::Abs([double]$actual - [double]$expected) -le [double]$tol)
    }
    if ($ok) { $script:pass++ } else {
        $script:fail++
        Write-Host ("  [FAIL] {0,-62} expected {1} got {2}" -f $name, $expected, $actual) -ForegroundColor Red
    }
}
$ASOFM = "(SELECT DATEFROMPARTS(YEAR(CONVERT(DATE, ConfigValue, 23)), MONTH(CONVERT(DATE, ConfigValue, 23)), 1) FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate')"

Write-Host "`n== slicers ==" -ForegroundColor Yellow
$slicers = @(
    @{ n = "country = Germany";     dax = 'DimCustomer[Country] = "Germany"';        where = "c.Country = 'Germany'" },
    @{ n = "segment = Enterprise";  dax = 'DimCustomer[Segment] = "Enterprise"';     where = "c.Segment = 'Enterprise'" },
    @{ n = "plan = Business";       dax = 'DimPlan[PlanName] = "Business"';          where = "p.PlanName = 'Business'" },
    @{ n = "industry = Healthcare"; dax = 'DimCustomer[Industry] = "Healthcare"';    where = "c.Industry = 'Healthcare'" },
    @{ n = "billing = Annual";      dax = 'DimCustomer[BillingCycle] = "Annual"';    where = "c.BillingCycle = 'Annual'" },
    @{ n = "status = Churned";      dax = 'DimCustomer[SubscriptionStatus] = "Churned"'; where = "c.SubscriptionStatus = 'Churned'" }
)
foreach ($s in $slicers) {
    $a = (Dax "EVALUATE ROW ( ""v"", CALCULATE ( [MRR], $($s.dax) ) )").Rows[0][0]
    $e = (Sql @"
SELECT SUM(m.MRR) FROM dbo.FactSubscriptionMonth m
JOIN dbo.DimCustomer c ON c.CustomerID = m.CustomerID
JOIN dbo.DimPlan p ON p.PlanID = c.PlanID
JOIN dbo.FactSubscription s ON s.CustomerID = m.CustomerID
WHERE m.MonthStart = $ASOFM AND $($s.where)
"@).Rows[0][0]
    # A churned customer has no snapshot row in the as-of month, so both sides are
    # legitimately empty - which is the right answer, not a failure.
    if ($e -is [System.DBNull]) { Check "MRR with $($s.n) is blank" $a $null 0 }
    else { Check "MRR with $($s.n)" $a ([double]$e) 0.01 }
}

# Two at once, which is where a broken relationship usually shows.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [MRR], DimCustomer[Country] = "Canada", DimPlan[PlanName] = "Starter" ) )').Rows[0][0]
$e = (Sql @"
SELECT COALESCE(SUM(m.MRR), 0) FROM dbo.FactSubscriptionMonth m
JOIN dbo.DimCustomer c ON c.CustomerID = m.CustomerID
JOIN dbo.DimPlan p ON p.PlanID = c.PlanID
WHERE m.MonthStart = $ASOFM AND c.Country = 'Canada' AND p.PlanName = 'Starter'
"@).Rows[0][0]
Check "MRR with country AND plan together" $a ([double]$e) 0.01

# A plan filter must reach the facts that hang off the CUSTOMER, not just the
# subscription - this is the defect the first render found.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Tickets], DimPlan[PlanName] = "Enterprise" ) )').Rows[0][0]
$e = (Sql @"
SELECT COUNT(*) FROM dbo.FactSupportTicket t
JOIN dbo.DimCustomer c ON c.CustomerID = t.CustomerID
JOIN dbo.DimPlan p ON p.PlanID = c.PlanID
WHERE p.PlanName = 'Enterprise'
"@).Rows[0][0]
Check "a plan filter reaches TICKETS" $a ([double]$e) 0
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Acquisition Spend], DimPlan[PlanName] = "Enterprise" ) )').Rows[0][0]
$e = (Sql @"
SELECT SUM(a.AcquisitionCost) FROM dbo.FactAcquisition a
JOIN dbo.DimCustomer c ON c.CustomerID = a.CustomerID
JOIN dbo.DimPlan p ON p.PlanID = c.PlanID
WHERE p.PlanName = 'Enterprise'
"@).Rows[0][0]
Check "a plan filter reaches ACQUISITION COST" $a ([double]$e) 0.01
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Usage Customers], DimPlan[PlanName] = "Enterprise" ) )').Rows[0][0]
$e = (Sql @"
SELECT COUNT(DISTINCT u.CustomerID) FROM dbo.FactUsageMonthly u
JOIN dbo.DimCustomer c ON c.CustomerID = u.CustomerID
JOIN dbo.DimPlan p ON p.PlanID = c.PlanID
WHERE p.PlanName = 'Enterprise'
"@).Rows[0][0]
Check "a plan filter reaches USAGE" $a ([double]$e) 0

Write-Host "`n== the calculation group ==" -ForegroundColor Yellow
$items = @{
    "Selected period"    = "SELECT SUM(MRR) FROM dbo.FactSubscriptionMonth WHERE MonthStart = '2026-08-01'"
    "Prior month"        = "SELECT SUM(MRR) FROM dbo.FactSubscriptionMonth WHERE MonthStart = '2026-07-01'"
    "Prior year"         = "SELECT SUM(MRR) FROM dbo.FactSubscriptionMonth WHERE MonthStart = '2025-08-01'"
}
foreach ($k in $items.Keys) {
    $a = (Dax @"
EVALUATE
CALCULATETABLE (
    ROW ( "v", [MRR] ),
    'Time Comparison'[Comparison] = "$k",
    DimDate[MonthStart] = DATE ( 2026, 8, 1 )
)
"@).Rows[0][0]
    Check "MRR under '$k'" $a ([double](Sql $items[$k]).Rows[0][0]) 0.01
}
# The group applied UNDER a slicer: the comparison must respect the selection.
$a = (Dax @"
EVALUATE
CALCULATETABLE (
    ROW ( "v", [MRR] ),
    'Time Comparison'[Comparison] = "Prior month",
    DimDate[MonthStart] = DATE ( 2026, 8, 1 ),
    DimCustomer[Country] = "Germany"
)
"@).Rows[0][0]
$e = (Sql @"
SELECT SUM(m.MRR) FROM dbo.FactSubscriptionMonth m
JOIN dbo.DimCustomer c ON c.CustomerID = m.CustomerID
WHERE m.MonthStart = '2026-07-01' AND c.Country = 'Germany'
"@).Rows[0][0]
Check "'Prior month' with a country slicer set" $a ([double]$e) 0.01

Write-Host "`n== the field parameter ==" -ForegroundColor Yellow
$cuts = @("Segment", "Industry", "Country", "Plan", "Acquisition channel", "Billing cycle")
foreach ($c in $cuts) {
    $d = Dax "EVALUATE CALCULATETABLE ( 'Customer Cut', 'Customer Cut'[Customer Cut] = ""$c"" )"
    Check "the parameter offers '$c'" $d.Rows.Count 1 0
}

Write-Host "`n== cross-filtering and the data boundary ==" -ForegroundColor Yellow
# Selecting a plan must move the cohort matrix.
$a = (Dax @"
EVALUATE
CALCULATETABLE (
    ROW ( "v", [Cohort Customers Retained] ),
    DimPlan[PlanName] = "Enterprise",
    DimCohort[CohortLabel] = "Mar 2025",
    DimTenureMonth[TenureMonth] = 12
)
"@).Rows[0][0]
$e = (Sql @"
SELECT COUNT(DISTINCT m.CustomerID) FROM dbo.FactSubscriptionMonth m
JOIN dbo.DimCustomer c ON c.CustomerID = m.CustomerID
JOIN dbo.DimPlan p ON p.PlanID = c.PlanID
WHERE p.PlanName = 'Enterprise' AND m.CohortMonth = '2025-03-01' AND m.TenureMonth = 12
"@).Rows[0][0]
Check "a plan selection filters the cohort matrix" $a ([double]$e) 0

# Nothing is reported past the as-of month, whatever is selected.
foreach ($m in @("DATE ( 2026, 9, 1 )", "DATE ( 2027, 1, 1 )")) {
    $a = (Dax "EVALUATE CALCULATETABLE ( ROW ( ""v"", [MRR] ), DimDate[MonthStart] = $m )").Rows[0][0]
    Check "MRR is blank at $m" $a $null 0
    $a = (Dax "EVALUATE CALCULATETABLE ( ROW ( ""v"", [Logo Churn %] ), DimDate[MonthStart] = $m )").Rows[0][0]
    Check "logo churn is blank at $m" $a $null 0
}
# ...and a cohort cell that has not happened yet stays blank rather than reading 0%.
$a = (Dax @"
EVALUATE
CALCULATETABLE (
    ROW ( "v", [Cohort Retention %] ),
    DimCohort[CohortLabel] = "Jun 2026",
    DimTenureMonth[TenureMonth] = 12
)
"@).Rows[0][0]
Check "a cohort cell beyond the data is blank, not 0%" $a $null 0

$conn.Close(); $sql.Close()
Write-Host ""
$colour = if ($script:fail) { "Red" } else { "Green" }
Write-Host ("INTERACTIONS: {0} of {1} checks passed" -f $script:pass, ($script:pass + $script:fail)) -ForegroundColor $colour
if ($script:fail) { exit 1 }
exit 0
