<#
    Live validation of the semantic model, run with Power BI Desktop open and refreshed.

    Step 1  SWEEP      every measure is evaluated alone. One broken measure poisons the
                       whole model script and Power BI then STRIPS it from visuals and
                       saves the stripped report, so nothing else is trusted until this
                       passes. Grand-total values go to Validation/measure_values.csv.
    Step 2  RECONCILE  every measure is compared with an independently written SQL query
                       against SaaSRevenueBI. Independently written matters: the DAX and
                       the SQL are different routes to the same number, so agreement is
                       evidence rather than a tautology.
    Step 3  SECURITY   the role is tested for its secure default (an unmapped user sees
                       nothing) and its mapping logic is evaluated for each of the eight
                       users.

    AS OF: every expected value states the world on the as-of date (2026-08-31). MRR is
    a STOCK read at a month end, so its SQL counterpart reads one month of the snapshot
    and never sums a range.

    SQL expected values that divide are computed in FLOAT: SQL Server rounds a
    DECIMAL / DECIMAL quotient to as few as 6 decimal places, which would fail a
    correct DAX result.

    Usage:  powershell -ExecutionPolicy Bypass -File Validation\reconcile_measures.ps1
#>
param([string]$SqlServer = "localhost\SQLEXPRESS")
$ErrorActionPreference = "Stop"
$script:pass = 0; $script:fail = 0; $script:rows = @()

# ------------------------------------------------------------------ connect ---
$dll = Get-ChildItem "C:\Program Files\Microsoft.NET\ADOMD.NET" -Filter "Microsoft.AnalysisServices.AdomdClient.dll" -Recurse | Select-Object -First 1
Add-Type -Path $dll.FullName
$wsRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$script:port = $null; $script:cat = $null
foreach ($ws in (Get-ChildItem $wsRoot -Directory | Sort-Object LastWriteTime -Descending)) {
    $pf = Join-Path $ws.FullName "Data\msmdsrv.port.txt"
    if (-not (Test-Path $pf)) { continue }
    try {
        $p = ([System.IO.File]::ReadAllText($pf, [System.Text.Encoding]::Unicode)).Trim()
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$p")
        $c.Open(); $cmd = $c.CreateCommand(); $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
        $rd = $cmd.ExecuteReader(); $k = $null; if ($rd.Read()) { $k = $rd.GetValue(0) }; $rd.Close(); $c.Close()
        if ($k) { $script:port = $p; $script:cat = $k; break }
    } catch {}
}
if (-not $script:cat) { throw "No live Power BI model. Open SaaSRevenue.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$($script:port);Initial Catalog=$($script:cat)")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=SaaSRevenueBI;Integrated Security=True;TrustServerCertificate=True")
$sql.Open()
Write-Host "Power BI model on localhost:$($script:port); SQL on $SqlServer" -ForegroundColor Cyan

function Dax([string]$q, $c = $conn) {
    $cmd = $c.CreateCommand(); $cmd.CommandText = $q
    $da = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Sql([string]$q) {
    $cmd = $sql.CreateCommand(); $cmd.CommandText = $q; $cmd.CommandTimeout = 300
    $da = New-Object System.Data.SqlClient.SqlDataAdapter($cmd)
    $dt = New-Object System.Data.DataTable; [void]$da.Fill($dt); return , $dt
}
function Check($area, $name, $actual, $expected, $tol) {
    $ok = $false
    if ($expected -is [string]) { $ok = ("$actual" -eq "$expected") }
    elseif ($null -ne $actual -and "$actual" -ne "" -and -not ($actual -is [System.DBNull])) {
        $ok = ([Math]::Abs([double]$actual - [double]$expected) -le [double]$tol)
    }
    if ($ok) { $script:pass++; $tag = "PASS" } else { $script:fail++; $tag = "FAIL" }
    $script:rows += [pscustomobject]@{ Result = $tag; Area = $area; Check = $name; Expected = $expected; Actual = $actual }
    if (-not $ok) { Write-Host ("  [FAIL] {0,-10} {1,-62} expected {2} got {3}" -f $area, $name, $expected, $actual) -ForegroundColor Red }
}
function Scalar($area, $name, $daxExpr, $sqlExpr, $tol) {
    $a = (Dax "EVALUATE ROW ( ""v"", $daxExpr )").Rows[0][0]
    $e = (Sql "SELECT $sqlExpr").Rows[0][0]
    if ($e -is [string]) { Check $area $name "$a" $e 0 } else { Check $area $name $a ([double]$e) $tol }
}
# A row's key is every column but the last, joined; the last column is the value.
function RowKey($r) {
    $n = $r.Table.Columns.Count
    return ((0..($n - 2) | ForEach-Object { "$($r[$_])".Trim() }) -join " | ")
}
function Grouped($area, $name, $daxQuery, $sqlQuery, $tol) {
    $d = Dax $daxQuery; $s = Sql $sqlQuery
    $map = @{}; foreach ($r in $d.Rows) { $map[(RowKey $r)] = $r[$r.Table.Columns.Count - 1] }
    if ($s.Rows.Count -eq 0) { Check $area "$name (SQL returned rows)" 0 1 0 }
    foreach ($r in $s.Rows) {
        $v = $r[$r.Table.Columns.Count - 1]
        if ($v -is [string]) { Check $area "$name | $(RowKey $r)" "$($map[(RowKey $r)])" $v 0 }
        else { Check $area "$name | $(RowKey $r)" $map[(RowKey $r)] ([double]$v) $tol }
    }
    Check $area "$name | group count" $d.Rows.Count $s.Rows.Count 0
}

# The as-of month, in SQL. Every point-in-time expectation reads this one month.
$ASOFM = "(SELECT DATEFROMPARTS(YEAR(CONVERT(DATE, ConfigValue, 23)), MONTH(CONVERT(DATE, ConfigValue, 23)), 1) FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate')"

# ---------------------------------------------------------------- 1. sweep ---
Write-Host "`n== 1. SWEEP: every measure evaluated alone ==" -ForegroundColor Yellow
$tmdl = Join-Path $PSScriptRoot "..\PowerBI\SaaSRevenue.SemanticModel\definition\tables\_Measures.tmdl"
$names = @()
foreach ($ln in (Get-Content -LiteralPath $tmdl)) {
    if ($ln -match "^\tmeasure '([^']+)'") { $names += $Matches[1] }
    elseif ($ln -match "^\tmeasure (\S+) =") { $names += $Matches[1] }
}
$values = @()
foreach ($n in $names) {
    $esc = $n.Replace("]", "]]")
    try {
        $dt = Dax "EVALUATE ROW ( ""v"", [$esc] )"
        $v = $dt.Rows[0][0]
        $values += [pscustomobject]@{ Measure = $n; Value = "$v" }
        $script:pass++
    } catch {
        $script:fail++
        $script:rows += [pscustomobject]@{ Result = "FAIL"; Area = "Sweep"; Check = $n; Expected = "evaluates"; Actual = $_.Exception.Message }
        Write-Host ("  [FAIL] sweep {0}: {1}" -f $n, ($_.Exception.Message -replace "`r?`n", " ")) -ForegroundColor Red
    }
}
$values | Export-Csv -NoTypeInformation -Path (Join-Path $PSScriptRoot "measure_values.csv")
Write-Host ("  {0} measures evaluated" -f $names.Count)

# ------------------------------------------------------------ 2. reconcile ---
Write-Host "`n== 2. RECONCILE: model vs independent SQL ==" -ForegroundColor Yellow

# -- 2a. the headline stocks, on the as-of date -------------------------------
Scalar "Revenue" "MRR at the as-of month" "[MRR]" `
    "(SELECT SUM(MRR) FROM dbo.FactSubscriptionMonth WHERE MonthStart = $ASOFM)" 0.01
Scalar "Revenue" "ARR at the as-of month" "[ARR]" `
    "(SELECT SUM(MRR) * 12 FROM dbo.FactSubscriptionMonth WHERE MonthStart = $ASOFM)" 0.01
Scalar "Customers" "customers at the as-of month" "[Customers]" `
    "(SELECT COUNT(DISTINCT CustomerID) FROM dbo.FactSubscriptionMonth WHERE MonthStart = $ASOFM)" 0
Scalar "Revenue" "ARPA at the as-of month" "[ARPA]" `
    "(SELECT CONVERT(FLOAT, SUM(MRR)) / COUNT(DISTINCT CustomerID) FROM dbo.FactSubscriptionMonth WHERE MonthStart = $ASOFM)" 0.0001
Scalar "Customers" "customers ever acquired" "[Customers Ever Acquired]" "(SELECT COUNT(*) FROM dbo.FactSubscription)" 0
Scalar "Customers" "customers ever churned" "[Customers Ever Churned]" `
    "(SELECT COUNT(*) FROM dbo.FactSubscription WHERE IsChurned = 1)" 0
Scalar "Customers" "ever-churn rate" "[Ever-Churn Rate]" `
    "(SELECT CONVERT(FLOAT, SUM(CONVERT(FLOAT, IsChurned))) / COUNT(*) FROM dbo.FactSubscription)" 0.000001
Scalar "Customers" "median tenure" "[Median Tenure (Months)]" `
    "(SELECT DISTINCT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CONVERT(FLOAT, TenureMonths)) OVER () FROM dbo.FactSubscription)" 0.01

# -- 2b. MRR and customers by month: the stock, never summed ------------------
Grouped "Revenue" "MRR by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [MRR] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
SELECT CONVERT(CHAR(7), MonthStart, 126) AS m, SUM(MRR) AS v
FROM dbo.FactSubscriptionMonth GROUP BY MonthStart ORDER BY 1
"@ 0.01

Grouped "Customers" "customers by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Customers] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
SELECT CONVERT(CHAR(7), MonthStart, 126) AS m, COUNT(DISTINCT CustomerID) AS v
FROM dbo.FactSubscriptionMonth GROUP BY MonthStart ORDER BY 1
"@ 0

# -- 2c. the movement ledger --------------------------------------------------
Grouped "Movement" "MRR movement by type" @"
EVALUATE
SUMMARIZECOLUMNS ( DimMovementType[MovementType], "v", [MRR Movement] + 0 )
"@ @"
SELECT mt.MovementType, COALESCE(SUM(m.MRRDelta), 0) AS v
FROM dbo.DimMovementType mt
LEFT JOIN dbo.FactMRRMovement m ON m.MovementType = mt.MovementType
GROUP BY mt.MovementType
"@ 0.01

Grouped "Movement" "new MRR by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [New MRR] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
SELECT CONVERT(CHAR(7), MonthStart, 126) AS m, SUM(MRRDelta) AS v
FROM dbo.FactMRRMovement WHERE MovementType = 'New' GROUP BY MonthStart ORDER BY 1
"@ 0.01

Grouped "Movement" "churned MRR by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Churned MRR] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
SELECT CONVERT(CHAR(7), MonthStart, 126) AS m, SUM(MRRDelta) AS v
FROM dbo.FactMRRMovement WHERE MovementType = 'Churn' GROUP BY MonthStart ORDER BY 1
"@ 0.01

Grouped "Movement" "new customers by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [New Customers] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
SELECT CONVERT(CHAR(7), MonthStart, 126) AS m, COUNT(*) AS v
FROM dbo.FactMRRMovement WHERE MovementType IN ('New','Reactivation') GROUP BY MonthStart ORDER BY 1
"@ 0

Grouped "Movement" "churned customers by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Churned Customers] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
SELECT CONVERT(CHAR(7), MonthStart, 126) AS m, COUNT(*) AS v
FROM dbo.FactMRRMovement WHERE MovementType = 'Churn' GROUP BY MonthStart ORDER BY 1
"@ 0

# The three movements that cannot occur here. Checked as numbers, not asserted.
foreach ($t in @("Expansion", "Contraction", "Reactivation")) {
    Scalar "Movement" "$t MRR is nil" "[$t MRR] + 0" `
        "(SELECT COALESCE(SUM(MRRDelta), 0) FROM dbo.FactMRRMovement WHERE MovementType = '$t')" 0.01
}

# -- 2d. retention: the two bases, and the fact that they are equal -----------
Grouped "Retention" "logo churn % by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Logo Churn %] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
WITH snap AS (
    SELECT MonthStart, COUNT(DISTINCT CustomerID) AS n, SUM(MRR) AS mrr
    FROM dbo.FactSubscriptionMonth GROUP BY MonthStart
),
mv AS (
    SELECT MonthStart,
           SUM(CASE WHEN MovementType = 'Churn' THEN 1 ELSE 0 END) AS lost,
           -COALESCE(SUM(CASE WHEN MovementType = 'Churn' THEN MRRDelta END), 0) AS lostmrr
    FROM dbo.FactMRRMovement GROUP BY MonthStart
)
SELECT CONVERT(CHAR(7), s.MonthStart, 126) AS m, CONVERT(FLOAT, COALESCE(mv.lost, 0)) / p.n AS v
FROM snap s JOIN snap p ON p.MonthStart = DATEADD(MONTH, -1, s.MonthStart)
LEFT JOIN mv ON mv.MonthStart = s.MonthStart ORDER BY 1
"@ 0.000001

Grouped "Retention" "revenue churn % by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Revenue Churn %] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
WITH snap AS (
    SELECT MonthStart, COUNT(DISTINCT CustomerID) AS n, SUM(MRR) AS mrr
    FROM dbo.FactSubscriptionMonth GROUP BY MonthStart
),
mv AS (
    SELECT MonthStart,
           SUM(CASE WHEN MovementType = 'Churn' THEN 1 ELSE 0 END) AS lost,
           -COALESCE(SUM(CASE WHEN MovementType = 'Churn' THEN MRRDelta END), 0) AS lostmrr
    FROM dbo.FactMRRMovement GROUP BY MonthStart
)
SELECT CONVERT(CHAR(7), s.MonthStart, 126) AS m, CONVERT(FLOAT, COALESCE(mv.lostmrr, 0)) / p.mrr AS v
FROM snap s JOIN snap p ON p.MonthStart = DATEADD(MONTH, -1, s.MonthStart)
LEFT JOIN mv ON mv.MonthStart = s.MonthStart ORDER BY 1
"@ 0.000001

Grouped "Retention" "GRR % by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Gross Revenue Retention %] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
WITH snap AS (SELECT MonthStart, SUM(MRR) AS mrr FROM dbo.FactSubscriptionMonth GROUP BY MonthStart),
mv AS (SELECT MonthStart,
              COALESCE(SUM(CASE WHEN MovementType IN ('Churn','Contraction') THEN MRRDelta END), 0) AS down,
              COALESCE(SUM(CASE WHEN MovementType IN ('Expansion','Reactivation') THEN MRRDelta END), 0) AS up
       FROM dbo.FactMRRMovement GROUP BY MonthStart)
SELECT CONVERT(CHAR(7), s.MonthStart, 126) AS m, (p.mrr + COALESCE(mv.down, 0)) / p.mrr AS v
FROM snap s JOIN snap p ON p.MonthStart = DATEADD(MONTH, -1, s.MonthStart)
LEFT JOIN mv ON mv.MonthStart = s.MonthStart ORDER BY 1
"@ 0.000001

Grouped "Retention" "NRR % by month" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS ( DimDate[MonthStart], "v", [Net Revenue Retention %] ),
        "m", FORMAT ( DimDate[MonthStart], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [m]
"@ @"
WITH snap AS (SELECT MonthStart, SUM(MRR) AS mrr FROM dbo.FactSubscriptionMonth GROUP BY MonthStart),
mv AS (SELECT MonthStart,
              COALESCE(SUM(CASE WHEN MovementType IN ('Churn','Contraction') THEN MRRDelta END), 0) AS down,
              COALESCE(SUM(CASE WHEN MovementType IN ('Expansion','Reactivation') THEN MRRDelta END), 0) AS up
       FROM dbo.FactMRRMovement GROUP BY MonthStart)
SELECT CONVERT(CHAR(7), s.MonthStart, 126) AS m,
       (p.mrr + COALESCE(mv.down, 0) + COALESCE(mv.up, 0)) / p.mrr AS v
FROM snap s JOIN snap p ON p.MonthStart = DATEADD(MONTH, -1, s.MonthStart)
LEFT JOIN mv ON mv.MonthStart = s.MonthStart ORDER BY 1
"@ 0.000001

Scalar "Retention" "NRR less GRR is zero (no expansion exists)" "[NRR less GRR (pp)] + 0" "0.0" 0.000001
Scalar "Retention" "trailing 12m revenue retention" "[Trailing 12m Revenue Retention %]" @"
(SELECT (o.mrr + COALESCE(d.down, 0)) / o.mrr
 FROM (SELECT CONVERT(FLOAT, SUM(MRR)) AS mrr FROM dbo.FactSubscriptionMonth
       WHERE MonthStart = DATEADD(MONTH, -12, $ASOFM)) o
 CROSS JOIN (SELECT SUM(MRRDelta) AS down FROM dbo.FactMRRMovement
             WHERE MovementType IN ('Churn','Contraction')
               AND MonthStart > DATEADD(MONTH, -12, $ASOFM) AND MonthStart <= $ASOFM) d)
"@ 0.000001

# -- 2e. cohorts --------------------------------------------------------------
Grouped "Cohort" "cohort size by cohort" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimCohort[CohortMonth], "v", [Cohort Size] ),
    "c", FORMAT ( DimCohort[CohortMonth], "yyyy-MM" ),
    "val", [v]
)
ORDER BY [c]
"@ @"
SELECT CONVERT(CHAR(7), CohortMonth, 126) AS c, CohortSize AS v FROM dbo.DimCohort ORDER BY 1
"@ 0

Grouped "Cohort" "retention at month 12 by cohort" @"
EVALUATE
FILTER (
    SELECTCOLUMNS (
        SUMMARIZECOLUMNS (
            DimCohort[CohortMonth],
            TREATAS ( { 12 }, DimTenureMonth[TenureMonth] ),
            "v", [Cohort Retention %]
        ),
        "c", FORMAT ( DimCohort[CohortMonth], "yyyy-MM" ),
        "val", [v]
    ),
    NOT ISBLANK ( [val] )
)
ORDER BY [c]
"@ @"
SELECT CONVERT(CHAR(7), c.CohortMonth, 126) AS c,
       CONVERT(FLOAT, COUNT(DISTINCT m.CustomerID)) / c.CohortSize AS v
FROM dbo.DimCohort c
JOIN dbo.FactSubscriptionMonth m ON m.CohortMonth = c.CohortMonth AND m.TenureMonth = 12
WHERE DATEADD(MONTH, 12, c.CohortMonth) <= $ASOFM
GROUP BY c.CohortMonth, c.CohortSize
ORDER BY 1
"@ 0.000001

# -- 2f. the cuts: one that matters and three that do not ---------------------
Grouped "Cuts" "MRR by plan" @"
EVALUATE SUMMARIZECOLUMNS ( DimPlan[PlanName], "v", [MRR] )
"@ @"
SELECT p.PlanName, SUM(m.MRR) AS v
FROM dbo.FactSubscriptionMonth m JOIN dbo.DimPlan p ON p.PlanID = m.PlanID
WHERE m.MonthStart = $ASOFM GROUP BY p.PlanName
"@ 0.01

Grouped "Cuts" "ever-churn rate by plan" @"
EVALUATE SUMMARIZECOLUMNS ( DimPlan[PlanName], "v", [Churn Rate by Group] )
"@ @"
SELECT p.PlanName, CONVERT(FLOAT, SUM(CONVERT(FLOAT, s.IsChurned))) / COUNT(*) AS v
FROM dbo.FactSubscription s JOIN dbo.DimPlan p ON p.PlanID = s.PlanID GROUP BY p.PlanName
"@ 0.000001

Grouped "Cuts" "ever-churn rate by segment" @"
EVALUATE SUMMARIZECOLUMNS ( DimCustomer[Segment], "v", [Churn Rate by Group] )
"@ @"
SELECT c.Segment, CONVERT(FLOAT, SUM(CONVERT(FLOAT, s.IsChurned))) / COUNT(*) AS v
FROM dbo.FactSubscription s JOIN dbo.DimCustomer c ON c.CustomerID = s.CustomerID GROUP BY c.Segment
"@ 0.000001

Grouped "Cuts" "customers by country" @"
EVALUATE SUMMARIZECOLUMNS ( DimCustomer[Country], "v", [Customers] )
"@ @"
SELECT c.Country, COUNT(DISTINCT m.CustomerID) AS v
FROM dbo.FactSubscriptionMonth m JOIN dbo.DimCustomer c ON c.CustomerID = m.CustomerID
WHERE m.MonthStart = $ASOFM GROUP BY c.Country
"@ 0

Grouped "Cuts" "ever-churn rate by acquisition channel" @"
EVALUATE SUMMARIZECOLUMNS ( DimCustomer[AcquisitionSource], "v", [Churn Rate by Group] )
"@ @"
SELECT c.AcquisitionSource, CONVERT(FLOAT, SUM(CONVERT(FLOAT, s.IsChurned))) / COUNT(*) AS v
FROM dbo.FactSubscription s JOIN dbo.DimCustomer c ON c.CustomerID = s.CustomerID GROUP BY c.AcquisitionSource
"@ 0.000001

# -- 2g. usage, support and billing ------------------------------------------
# [Usage Customers] counts the customers seen in the PERIOD, so with no date filter
# it is every customer ever observed. Coverage at a moment is a separate measure and
# is checked separately, below.
Scalar "Usage" "usage customers, all months" "[Usage Customers]" `
    "(SELECT COUNT(DISTINCT CustomerID) FROM dbo.FactUsageMonthly)" 0
Scalar "Usage" "usage customers in the as-of month" `
    "CALCULATE ( [Usage Customers], DimDate[MonthStart] = DATE ( 2026, 8, 1 ) )" `
    "(SELECT COUNT(DISTINCT CustomerID) FROM dbo.FactUsageMonthly WHERE MonthStart = $ASOFM)" 0
Scalar "Usage" "usage coverage at the as-of month" "[Usage Coverage %]" @"
(SELECT CONVERT(FLOAT, (SELECT COUNT(DISTINCT CustomerID) FROM dbo.FactUsageMonthly WHERE MonthStart = $ASOFM))
      / (SELECT COUNT(DISTINCT CustomerID) FROM dbo.FactSubscriptionMonth WHERE MonthStart = $ASOFM))
"@ 0.000001
Scalar "Usage" "seat utilisation at the as-of month" "[Seat Utilisation %]" @"
(SELECT CONVERT(FLOAT, SUM(ActiveUsers)) / SUM(LicensedSeats) FROM dbo.FactUsageMonthly WHERE MonthStart = $ASOFM)
"@ 0.000001
Scalar "Usage" "feature adoption, all months" "[Feature Adoption %]" `
    "(SELECT AVG(CONVERT(FLOAT, FeatureAdoptionRate)) FROM dbo.FactUsageMonthly)" 0.000001

Scalar "Support" "tickets" "[Tickets]" "(SELECT COUNT(*) FROM dbo.FactSupportTicket)" 0
Scalar "Support" "mean time to resolve, resolved only" "[Mean Time To Resolve (Hours)]" `
    "(SELECT AVG(CONVERT(FLOAT, ResolutionHours)) FROM dbo.FactSupportTicket WHERE IsResolved = 1)" 0.0001
Scalar "Support" "urgent ticket share" "[Urgent Ticket Share]" @"
(SELECT CONVERT(FLOAT, SUM(CASE WHEN Severity IN ('High','Critical') THEN 1 ELSE 0 END)) / COUNT(*)
 FROM dbo.FactSupportTicket)
"@ 0.000001
Scalar "Support" "unresolved share" "[Unresolved Share]" @"
(SELECT CONVERT(FLOAT, SUM(CASE WHEN IsResolved = 0 THEN 1 ELSE 0 END)) / COUNT(*) FROM dbo.FactSupportTicket)
"@ 0.000001
Grouped "Support" "tickets by severity" @"
EVALUATE SUMMARIZECOLUMNS ( DimSeverity[SeverityName], "v", [Tickets] )
"@ @"
SELECT Severity, COUNT(*) AS v FROM dbo.FactSupportTicket GROUP BY Severity
"@ 0

Scalar "Billing" "invoices" "[Invoices]" "(SELECT COUNT(*) FROM dbo.FactInvoice)" 0
Scalar "Billing" "failed invoices" "[Failed Invoices]" "(SELECT COUNT(*) FROM dbo.FactInvoice WHERE IsFailed = 1)" 0
Scalar "Billing" "payment failure rate" "[Payment Failure Rate]" `
    "(SELECT CONVERT(FLOAT, SUM(CONVERT(FLOAT, IsFailed))) / COUNT(*) FROM dbo.FactInvoice)" 0.000001
Scalar "Billing" "invoiced amount" "[Invoiced Amount]" "(SELECT SUM(InvoiceAmount) FROM dbo.FactInvoice)" 0.01
Scalar "Billing" "collected amount" "[Collected Amount]" `
    "(SELECT SUM(InvoiceAmount) FROM dbo.FactInvoice WHERE IsFailed = 0)" 0.01
Scalar "Billing" "median days to pay" "[Median Days To Pay]" @"
(SELECT DISTINCT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CONVERT(FLOAT, DaysToPay)) OVER ()
 FROM dbo.FactInvoice WHERE IsFailed = 0)
"@ 0.01

# -- 2h. unit economics (the modelled ones state their assumption) ------------
Scalar "Economics" "acquisition spend" "[Acquisition Spend]" "(SELECT SUM(AcquisitionCost) FROM dbo.FactAcquisition)" 0.01
Scalar "Economics" "blended CAC" "[CAC (Blended)]" `
    "(SELECT CONVERT(FLOAT, SUM(AcquisitionCost)) / COUNT(*) FROM dbo.FactAcquisition)" 0.0001
Scalar "Economics" "median CAC" "[CAC (Median)]" @"
(SELECT DISTINCT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CONVERT(FLOAT, AcquisitionCost)) OVER ()
 FROM dbo.FactAcquisition)
"@ 0.01
Scalar "Economics" "gross margin assumption comes from ModelConfig" "[Gross Margin Assumption]" `
    "(SELECT CONVERT(FLOAT, ConfigValue) FROM dbo.ModelConfig WHERE ConfigKey = 'GrossMarginAssumption')" 0.000001
Scalar "Economics" "gross profit per account = ARPA x margin" "[Gross Profit per Account]" @"
(SELECT (CONVERT(FLOAT, SUM(MRR)) / COUNT(DISTINCT CustomerID))
      * (SELECT CONVERT(FLOAT, ConfigValue) FROM dbo.ModelConfig WHERE ConfigKey = 'GrossMarginAssumption')
 FROM dbo.FactSubscriptionMonth WHERE MonthStart = $ASOFM)
"@ 0.0001

# -- 2i. the churn-driver evidence -------------------------------------------
Grouped "Drivers" "driver correlations" @"
EVALUATE SUMMARIZECOLUMNS ( ChurnDriverStrength[Driver], "v", [Driver Correlation] )
"@ @"
SELECT Driver, CONVERT(FLOAT, Correlation) AS v FROM analytics.vw_ChurnDriverStrength
"@ 0.0001

# -- 2j. the calculation group -----------------------------------------------
Grouped "CalcGroup" "MRR under each time comparison, Aug 2026" @"
EVALUATE
SUMMARIZECOLUMNS (
    'Time Comparison'[Comparison],
    TREATAS ( { DATE ( 2026, 8, 1 ) }, DimDate[MonthStart] ),
    "v", [MRR]
)
"@ @"
WITH s AS (SELECT MonthStart, SUM(MRR) AS mrr FROM dbo.FactSubscriptionMonth GROUP BY MonthStart)
SELECT x.Comparison, x.v FROM (
  SELECT 'Selected period' AS Comparison, (SELECT mrr FROM s WHERE MonthStart = '2026-08-01') AS v
  UNION ALL SELECT 'Prior month', (SELECT mrr FROM s WHERE MonthStart = '2026-07-01')
  UNION ALL SELECT 'Month over month',
        (SELECT mrr FROM s WHERE MonthStart = '2026-08-01') - (SELECT mrr FROM s WHERE MonthStart = '2026-07-01')
  UNION ALL SELECT 'Month over month %',
        CONVERT(FLOAT, (SELECT mrr FROM s WHERE MonthStart = '2026-08-01') - (SELECT mrr FROM s WHERE MonthStart = '2026-07-01'))
        / (SELECT mrr FROM s WHERE MonthStart = '2026-07-01')
  UNION ALL SELECT 'Prior year', (SELECT mrr FROM s WHERE MonthStart = '2025-08-01')
  UNION ALL SELECT 'Year over year %',
        CONVERT(FLOAT, (SELECT mrr FROM s WHERE MonthStart = '2026-08-01') - (SELECT mrr FROM s WHERE MonthStart = '2025-08-01'))
        / (SELECT mrr FROM s WHERE MonthStart = '2025-08-01')
) x
"@ 0.000001

# -- 2k. the field parameter --------------------------------------------------
$d = Dax "EVALUATE ROW ( ""n"", COUNTROWS ( 'Customer Cut' ) )"
Check "FieldParam" "Customer Cut offers six cuts" $d.Rows[0][0] 6 0
$d = Dax "EVALUATE SELECTCOLUMNS ( 'Customer Cut', ""c"", 'Customer Cut'[Customer Cut] ) ORDER BY [c]"
Check "FieldParam" "Customer Cut resolves its fields" $d.Rows.Count 6 0

# -- 2l. the data-quality view feeds the model -------------------------------
Grouped "DQ" "data-quality metrics" @"
EVALUATE SUMMARIZECOLUMNS ( DataQualityMetric[Metric], "v", [DQ Metric Value] )
"@ @"
SELECT Metric, CONVERT(FLOAT, MetricValue) AS v FROM analytics.vw_DataQualityMetric
"@ 0.000001

# ------------------------------------------------------------- 3. security ---
Write-Host "`n== 3. SECURITY: the role's default and its mapping logic ==" -ForegroundColor Yellow

# The secure default: connect AS THE ROLE with no user identity. An unmapped
# caller must see nothing at all, which is what "deny by default" means.
$roleConn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection(
    "Data Source=localhost:$($script:port);Initial Catalog=$($script:cat);Roles=Country Access")
$roleConn.Open()
$d = Dax "EVALUATE ROW ( ""c"", COALESCE ( COUNTROWS ( VALUES ( DimCustomer[Country] ) ), 0 ), ""m"", COALESCE ( [MRR], 0 ), ""n"", COALESCE ( [Customers], 0 ) )" $roleConn
Check "Security" "unmapped user sees no countries"  $d.Rows[0][0] 0 0
Check "Security" "unmapped user sees no MRR"        $d.Rows[0][1] 0 0.01
Check "Security" "unmapped user sees no customers"  $d.Rows[0][2] 0 0
$roleConn.Close()

# Each mapped user's scope, evaluated through the role's own filter expression,
# and what they would see compared with SQL. EffectiveUserName cannot be used:
# the synthetic addresses are not Windows accounts on this machine.
$users = (Sql "SELECT UserEmail, [Role], Country FROM dbo.SecurityUserAccess ORDER BY UserEmail")
foreach ($u in $users.Rows) {
    $email = $u[0]; $country = $u[2]
    $d = Dax @"
EVALUATE
VAR UserScope = CALCULATETABLE ( VALUES ( SecurityUserAccess[Country] ), SecurityUserAccess[UserEmail] = "$email" )
VAR VisibleCountries = FILTER ( ALL ( DimCustomer[Country] ), "ALL" IN UserScope || DimCustomer[Country] IN UserScope )
RETURN
ROW (
    "countries", COUNTROWS ( VisibleCountries ),
    "mrr", CALCULATE ( [MRR], TREATAS ( VisibleCountries, DimCustomer[Country] ) )
)
"@
    $expectedCountries = if ($country -eq "ALL") { 6 } else { 1 }
    Check "Security" "$email sees countries" $d.Rows[0][0] $expectedCountries 0
    $where = if ($country -eq "ALL") { "1 = 1" } else { "c.Country = '$country'" }
    $e = (Sql @"
SELECT SUM(m.MRR) FROM dbo.FactSubscriptionMonth m
JOIN dbo.DimCustomer c ON c.CustomerID = m.CustomerID
WHERE m.MonthStart = $ASOFM AND $where
"@).Rows[0][0]
    Check "Security" "$email sees the right MRR" $d.Rows[0][1] ([double]$e) 0.01
}

# ---------------------------------------------------------------- report ---
$conn.Close(); $sql.Close()
$script:rows | Export-Csv -NoTypeInformation -Path (Join-Path $PSScriptRoot "reconcile_results.csv")
$byArea = $script:rows | Group-Object Area | Sort-Object Name
foreach ($g in $byArea) {
    $f = @($g.Group | Where-Object Result -eq "FAIL").Count
    $colour = if ($f) { "Red" } else { "Green" }
    Write-Host ("  {0,-12} {1,5} passed  {2,3} failed" -f $g.Name, ($g.Count - $f), $f) -ForegroundColor $colour
}
Write-Host ("`nRECONCILIATION: {0} of {1} checks passed" -f $script:pass, ($script:pass + $script:fail)) -ForegroundColor Cyan
if ($script:fail) { exit 1 }
exit 0
