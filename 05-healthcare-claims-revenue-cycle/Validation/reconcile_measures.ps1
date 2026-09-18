<#
    Live validation of the semantic model, run with Power BI Desktop open and refreshed.

    Step 1  SWEEP      every measure is evaluated alone. One broken measure poisons the
                       whole model script and Power BI then STRIPS it from visuals and
                       saves the stripped report, so nothing else is trusted until this
                       passes. Grand-total values go to Validation/measure_values.csv.
    Step 2  RECONCILE  every measure is compared with an independently written SQL query
                       against HealthcareRCMBI. Independently written matters: the DAX and
                       the SQL are different routes to the same number, so agreement is
                       evidence rather than a tautology.
    Step 3  SECURITY   the role is tested for its secure default (an unmapped user sees
                       nothing) and its mapping logic is evaluated for all 82 users -
                       including that a facility-scoped user sees that facility's
                       providers and no others, because provider and facility are one
                       hierarchy here.

    AS OF: every expected value states the world on the as-of date (2026-11-03). Open
    AR is a STOCK read at a month end, so its SQL counterpart reads one month of the
    snapshot and never sums a range - and the days-in-AR window is capped at the last
    SUBMISSION date, because claims stop arriving two months before the cash does.

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
if (-not $script:cat) { throw "No live Power BI model. Open HealthcareRCM.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$($script:port);Initial Catalog=$($script:cat)")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=HealthcareRCMBI;Integrated Security=True;TrustServerCertificate=True")
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

# The anchors every point-in-time expectation reads. AR is a STOCK, so its SQL
# counterpart reads ONE month end and never sums a range.
$ASOFEND = "(SELECT EOMONTH(CONVERT(DATE, ConfigValue, 23)) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate')"
# Claims stop being submitted two months before the last payment arrives, so any rate
# expressed as days of business divides by a window that ends HERE, not at the as-of
# date - otherwise it divides a full receivable by seven days of submissions.
$LASTSUB = "(SELECT MAX(d.[Date]) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey)"

# ---------------------------------------------------------------- 1. sweep ---
Write-Host "`n== 1. SWEEP: every measure evaluated alone ==" -ForegroundColor Yellow
$tmdl = Join-Path $PSScriptRoot "..\PowerBI\HealthcareRCM.SemanticModel\definition\tables\_Measures.tmdl"
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

# -- 2a. the money chain, and the identity it has to close --------------------
Scalar "Money" "billed" "[Billed]" "(SELECT SUM(BilledAmount) FROM fact.FactClaim)" 0.01
Scalar "Money" "allowed" "[Allowed]" "(SELECT SUM(AllowedAmount) FROM fact.FactClaim)" 0.01
Scalar "Money" "collected" "[Collected]" "(SELECT SUM(PaidAmount) FROM fact.FactClaim)" 0.01
Scalar "Money" "contractual adjustment" "[Contractual Adjustment]" `
    "(SELECT SUM(BilledAmount - AllowedAmount) FROM fact.FactClaim)" 0.01
Scalar "Money" "patient responsibility" "[Patient Responsibility]" `
    "(SELECT SUM(AllowedAmount - PaidAmount) FROM fact.FactClaim WHERE ClaimStatusKey = 1)" 0.01
Scalar "Money" "denied amount" "[Denied Amount]" `
    "(SELECT SUM(AllowedAmount) FROM fact.FactClaim WHERE ClaimStatusKey = 3)" 0.01
Scalar "Money" "open AR on the claim header" "[Open AR (Claim Basis)]" `
    "(SELECT SUM(AllowedAmount) FROM fact.FactClaim WHERE ClaimStatusKey = 2)" 0.01
# The identity, from the OTHER side: SQL adds the four buckets and the model must agree.
Scalar "Money" "the four buckets sum to allowed" "[Allowed Buckets Total]" `
    "(SELECT SUM(PaidAmount) + SUM(CASE WHEN ClaimStatusKey = 1 THEN AllowedAmount - PaidAmount ELSE 0 END)
            + SUM(CASE WHEN ClaimStatusKey = 2 THEN AllowedAmount ELSE 0 END)
            + SUM(CASE WHEN ClaimStatusKey = 3 THEN AllowedAmount ELSE 0 END) FROM fact.FactClaim)" 0.01
Scalar "Money" "the identity gap is zero" "[Allowed Identity Gap]" "(SELECT 0.0)" 0.005
Scalar "Money" "line charges reconcile to billed" "[Line Charges]" `
    "(SELECT SUM(ChargeAmount) FROM fact.FactClaimLine)" 0.05
Scalar "Money" "cash on the payment fact" "[Cash Received]" `
    "(SELECT SUM(PaymentAmount) FROM fact.FactPayment)" 0.01
Scalar "Money" "average billed per claim" "[Average Billed per Claim]" `
    "(SELECT CONVERT(FLOAT, SUM(BilledAmount)) / COUNT(*) FROM fact.FactClaim)" 0.0001
Scalar "Money" "average allowed per claim" "[Average Allowed per Claim]" `
    "(SELECT CONVERT(FLOAT, SUM(AllowedAmount)) / COUNT(*) FROM fact.FactClaim)" 0.0001
Scalar "Money" "average collected per paid claim" "[Average Collected per Paid Claim]" `
    "(SELECT CONVERT(FLOAT, SUM(PaidAmount)) / COUNT(*) FROM fact.FactClaim WHERE ClaimStatusKey = 1)" 0.0001

# -- 2b. volume ---------------------------------------------------------------
Scalar "Volume" "claims" "[Claims]" "(SELECT COUNT(*) FROM fact.FactClaim)" 0
Scalar "Volume" "claim lines" "[Claim Lines]" "(SELECT COUNT(*) FROM fact.FactClaimLine)" 0
Scalar "Volume" "lines per claim" "[Lines per Claim]" `
    "(SELECT CONVERT(FLOAT, (SELECT COUNT(*) FROM fact.FactClaimLine)) / (SELECT COUNT(*) FROM fact.FactClaim))" 0.0001
Scalar "Volume" "patients treated (from claims, not the dimension)" "[Patients Treated]" `
    "(SELECT COUNT(DISTINCT BeneficiaryKey) FROM fact.FactClaim)" 0
Scalar "Volume" "providers billing" "[Providers Billing]" `
    "(SELECT COUNT(DISTINCT ProviderKey) FROM fact.FactClaim)" 0
Scalar "Volume" "facilities billing" "[Facilities Billing]" `
    "(SELECT COUNT(DISTINCT FacilityKey) FROM fact.FactClaim)" 0
Scalar "Volume" "claims per patient" "[Claims per Patient]" `
    "(SELECT CONVERT(FLOAT, COUNT(*)) / COUNT(DISTINCT BeneficiaryKey) FROM fact.FactClaim)" 0.0001
Scalar "Volume" "claims per provider" "[Claims per Provider]" `
    "(SELECT CONVERT(FLOAT, COUNT(*)) / COUNT(DISTINCT ProviderKey) FROM fact.FactClaim)" 0.0001
Scalar "Volume" "paid claims" "[Paid Claims]" "(SELECT COUNT(*) FROM fact.FactClaim WHERE ClaimStatusKey = 1)" 0
Scalar "Volume" "pending claims" "[Pending Claims]" "(SELECT COUNT(*) FROM fact.FactClaim WHERE ClaimStatusKey = 2)" 0
Scalar "Volume" "denied claims" "[Denied Claims]" "(SELECT COUNT(*) FROM fact.FactClaim WHERE ClaimStatusKey = 3)" 0

# -- 2c. the rates. Every quotient is computed in FLOAT in SQL, because SQL Server
#        rounds a DECIMAL / DECIMAL result to as few as six places.
Scalar "Rates" "allowed rate %" "[Allowed Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(AllowedAmount)) / SUM(BilledAmount) FROM fact.FactClaim)" 0.000001
Scalar "Rates" "contractual adjustment %" "[Contractual Adjustment %]" `
    "(SELECT CONVERT(FLOAT, SUM(BilledAmount - AllowedAmount)) / SUM(BilledAmount) FROM fact.FactClaim)" 0.000001
Scalar "Rates" "gross collection rate %" "[Gross Collection Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(PaidAmount)) / SUM(BilledAmount) FROM fact.FactClaim)" 0.000001
# The one a revenue-cycle team is measured on: RESOLVED claims only.
Scalar "Rates" "net collection rate % (resolved only)" "[Net Collection Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(PaidAmount)) / SUM(CASE WHEN ClaimStatusKey <> 2 THEN AllowedAmount ELSE 0 END)
      FROM fact.FactClaim)" 0.000001
Scalar "Rates" "net collection rate % (all claims)" "[Net Collection Rate (All Claims) %]" `
    "(SELECT CONVERT(FLOAT, SUM(PaidAmount)) / SUM(AllowedAmount) FROM fact.FactClaim)" 0.000001
Scalar "Rates" "patient responsibility %" "[Patient Responsibility %]" `
    "(SELECT CONVERT(FLOAT, SUM(AllowedAmount - PaidAmount)) / SUM(AllowedAmount)
      FROM fact.FactClaim WHERE ClaimStatusKey = 1)" 0.000001
Scalar "Rates" "paid claim rate %" "[Paid Claim Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN ClaimStatusKey = 1 THEN 1 ELSE 0 END)) / COUNT(*) FROM fact.FactClaim)" 0.000001
Scalar "Rates" "pending rate %" "[Pending Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN ClaimStatusKey = 2 THEN 1 ELSE 0 END)) / COUNT(*) FROM fact.FactClaim)" 0.000001

# -- 2d. denials --------------------------------------------------------------
Scalar "Denials" "denial rate %" "[Denial Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(CONVERT(INT, IsDenied))) / COUNT(*) FROM fact.FactClaim)" 0.000001
Scalar "Denials" "denial rate by VALUE %" "[Denial Rate (Value) %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN ClaimStatusKey = 3 THEN AllowedAmount ELSE 0 END)) / SUM(AllowedAmount)
      FROM fact.FactClaim)" 0.000001
# First-pass acceptance IS 1 minus the denial rate here - the SQL says so the same way.
Scalar "Denials" "first-pass acceptance %" "[First-Pass Acceptance %]" `
    "(SELECT 1.0 - CONVERT(FLOAT, SUM(CONVERT(INT, IsDenied))) / COUNT(*) FROM fact.FactClaim)" 0.000001
Scalar "Denials" "clean claim rate = first pass" "[Clean Claim Rate %]" `
    "(SELECT 1.0 - CONVERT(FLOAT, SUM(CONVERT(INT, IsDenied))) / COUNT(*) FROM fact.FactClaim)" 0.000001
Scalar "Denials" "denials" "[Denials]" "(SELECT COUNT(*) FROM fact.FactDenial)" 0
Scalar "Denials" "denied value at allowed" "[Denied Value]" "(SELECT SUM(DeniedAllowed) FROM fact.FactDenial)" 0.01
Scalar "Denials" "denied value at billed" "[Denied Value at Billed]" "(SELECT SUM(DeniedBilled) FROM fact.FactDenial)" 0.01
Scalar "Denials" "self pay denial rate %" "[Self Pay Denial Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
      FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey WHERE p.IsSelfPay = 1)" 0.000001
Scalar "Denials" "insured denial rate %" "[Insured Denial Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
      FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey WHERE p.IsSelfPay = 0)" 0.000001
Scalar "Denials" "self pay gap in points" "[Self Pay Gap (pp)]" `
    "(SELECT 100.0 * ((SELECT CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
                       FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey WHERE p.IsSelfPay = 0)
                    - (SELECT CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
                       FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey WHERE p.IsSelfPay = 1)))" 0.0001
Scalar "Denials" "denials written off" "[Denials Written Off]" `
    "(SELECT COUNT(*) FROM fact.FactDenial n JOIN dim.DimDenialStatus s ON s.DenialStatusKey = n.DenialStatusKey
      WHERE s.IsTerminal = 1)" 0
Scalar "Denials" "denials still open %" "[Denials Still Open %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN s.IsTerminal = 0 THEN 1 ELSE 0 END)) / COUNT(*)
      FROM fact.FactDenial n JOIN dim.DimDenialStatus s ON s.DenialStatusKey = n.DenialStatusKey)" 0.000001
Scalar "Denials" "preventable at registration %" "[Preventable at Registration %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN r.ReasonCategory = 'Front-end' THEN 1 ELSE 0 END)) / COUNT(*)
      FROM fact.FactDenial n JOIN dim.DimDenialReason r ON r.DenialReasonKey = n.DenialReasonKey)" 0.000001
# Zero by construction, and it has to STAY zero: this is the check that would fire
# if a denied claim ever acquired a payment.
Scalar "Denials" "denial recovery rate % is zero" "[Denial Recovery Rate %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN ClaimStatusKey = 3 THEN PaidAmount ELSE 0 END))
            / SUM(CASE WHEN ClaimStatusKey = 3 THEN AllowedAmount ELSE 0 END) FROM fact.FactClaim)" 0.000001

# -- 2e. the receivable. A STOCK: the SQL reads ONE month end, never a range. --
Scalar "AR" "open AR at the as-of month end" "[Open AR]" `
    "(SELECT SUM(s.ARAmount) FROM fact.FactARSnapshot s
      JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.[Date] = $ASOFEND)" 0.01
# ... and it must equal what the claim header says, by a completely different route.
Scalar "AR" "the snapshot agrees with the claim header" "[Open AR]" `
    "(SELECT SUM(AllowedAmount) FROM fact.FactClaim WHERE ClaimStatusKey = 2)" 0.01
Scalar "AR" "claims in AR" "[AR Claims]" `
    "(SELECT COUNT(*) FROM fact.FactARSnapshot s
      JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.[Date] = $ASOFEND)" 0
Scalar "AR" "average AR per claim" "[Average AR per Claim]" `
    "(SELECT CONVERT(FLOAT, SUM(s.ARAmount)) / COUNT(*) FROM fact.FactARSnapshot s
      JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.[Date] = $ASOFEND)" 0.0001
# Weighted by DOLLARS, not by claim: a big old receivable has to move this more than
# a small fresh one.
Scalar "AR" "AR weighted average age" "[AR Weighted Age (Days)]" `
    "(SELECT CONVERT(FLOAT, SUM(s.ARAmount * s.AgeDays)) / SUM(s.ARAmount) FROM fact.FactARSnapshot s
      JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.[Date] = $ASOFEND)" 0.0001
Scalar "AR" "AR median age" "[AR Median Age (Days)]" `
    "(SELECT DISTINCT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CONVERT(FLOAT, s.AgeDays)) OVER ()
      FROM fact.FactARSnapshot s JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.[Date] = $ASOFEND)" 0.01
Scalar "AR" "AR past the filing limit" "[AR Past Filing Limit]" `
    "(SELECT SUM(s.ARAmount) FROM fact.FactARSnapshot s
      JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
      JOIN dim.DimARBucket b ON b.ARBucketKey = s.ARBucketKey
      WHERE d.[Date] = $ASOFEND AND b.IsPastFiling = 1)" 0.01
Scalar "AR" "share of AR past the filing limit" "[AR Past Filing %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN b.IsPastFiling = 1 THEN s.ARAmount ELSE 0 END)) / SUM(s.ARAmount)
      FROM fact.FactARSnapshot s JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
      JOIN dim.DimARBucket b ON b.ARBucketKey = s.ARBucketKey WHERE d.[Date] = $ASOFEND)" 0.000001
Scalar "AR" "opening AR (the previous month end)" "[AR Opening]" `
    "(SELECT SUM(s.ARAmount) FROM fact.FactARSnapshot s JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
      WHERE d.[Date] = EOMONTH($ASOFEND, -1))" 0.01
# Days in AR: the window is CAPPED at the last submission date, because claims stop
# being submitted two months before the last payment arrives.
Scalar "AR" "days in AR" "[Days in AR]" `
    "(SELECT CONVERT(FLOAT, (SELECT SUM(s.ARAmount) FROM fact.FactARSnapshot s
        JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey WHERE d.[Date] = $ASOFEND))
      / ((SELECT SUM(c.AllowedAmount) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey
          WHERE d.[Date] > DATEADD(DAY, -91, $LASTSUB) AND d.[Date] <= $LASTSUB) / 91.0))" 0.05

# -- 2f. the AR ledger, and the identity it closes with the snapshot ----------
Scalar "ARMove" "everything that entered AR" "[AR In (Submitted)]" `
    "(SELECT SUM(Amount) FROM fact.FactARMovement WHERE ARMovementTypeKey = 1)" 0.01
Scalar "ARMove" "AR leaving as cash" "[AR Out (Collected)]" `
    "(SELECT SUM(Amount) FROM fact.FactARMovement WHERE ARMovementTypeKey = 2)" 0.01
Scalar "ARMove" "AR leaving as patient responsibility" "[AR Out (Patient)]" `
    "(SELECT SUM(Amount) FROM fact.FactARMovement WHERE ARMovementTypeKey = 3)" 0.01
Scalar "ARMove" "AR leaving as a denial" "[AR Out (Denied)]" `
    "(SELECT SUM(Amount) FROM fact.FactARMovement WHERE ARMovementTypeKey = 4)" 0.01
Scalar "ARMove" "net movement equals the closing balance" "[AR Movement]" `
    "(SELECT SUM(Amount) FROM fact.FactARMovement)" 0.01
Scalar "ARMove" "the roll-forward gap is zero" "[AR Roll-Forward Check]" "(SELECT 0.0)" 0.01

# -- 2g. timeliness -----------------------------------------------------------
Scalar "Clock" "days to submit" "[Days to Submit]" `
    "(SELECT AVG(CONVERT(FLOAT, DaysToSubmit)) FROM fact.FactClaim)" 0.0001
Scalar "Clock" "days to adjudicate" "[Days to Adjudicate]" `
    "(SELECT AVG(CONVERT(FLOAT, DaysToProcess)) FROM fact.FactClaim)" 0.0001
Scalar "Clock" "days to resolve" "[Days to Resolve]" `
    "(SELECT AVG(CONVERT(FLOAT, DaysToResolve)) FROM fact.FactClaim WHERE DaysToResolve IS NOT NULL)" 0.0001
Scalar "Clock" "days to cash (payment fact)" "[Days to Cash]" `
    "(SELECT AVG(CONVERT(FLOAT, DaysToPay)) FROM fact.FactPayment)" 0.0001
# The claim-basis version has to agree with the payment-basis one at the grand total,
# or the two are not the same quantity and the trend chart is lying.
Scalar "Clock" "days to cash (claim basis) agrees" "[Days to Cash (Claim Basis)]" `
    "(SELECT AVG(CONVERT(FLOAT, DaysToPay)) FROM fact.FactPayment)" 0.0001
Scalar "Clock" "days from adjudication to cash" "[Days Adjudication to Cash]" `
    "(SELECT AVG(CONVERT(FLOAT, DaysToResolve - DaysToProcess)) FROM fact.FactClaim WHERE ClaimStatusKey = 1)" 0.0001
Scalar "Clock" "median days to cash" "[Median Days to Cash]" `
    "(SELECT DISTINCT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CONVERT(FLOAT, DaysToPay)) OVER ()
      FROM fact.FactPayment)" 0.01
Scalar "Clock" "submitted within 3 days %" "[Submitted within 3 Days %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN DaysToSubmit <= 3 THEN 1 ELSE 0 END)) / COUNT(*) FROM fact.FactClaim)" 0.000001
Scalar "Clock" "adjudicated within 30 days %" "[Adjudicated within 30 Days %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN DaysToProcess <= 30 THEN 1 ELSE 0 END)) / COUNT(*) FROM fact.FactClaim)" 0.000001
Scalar "Clock" "paid within 45 days %" "[Paid within 45 Days %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN DaysToPay <= 45 THEN 1 ELSE 0 END)) / COUNT(*) FROM fact.FactPayment)" 0.000001
Scalar "Clock" "longest days to cash" "[Longest Days to Cash]" "(SELECT MAX(DaysToPay) FROM fact.FactPayment)" 0

# -- 2h. the evidence measures ------------------------------------------------
Scalar "Method" "strongest signal (Cramer's V)" "[Strongest Signal]" `
    "(SELECT MAX(CramersV) FROM analytics.vw_DenialSignalStrength)" 0.0001
Scalar "Method" "and it is the payer" "[Strongest Signal Dimension]" `
    "(SELECT TOP 1 Dimension FROM analytics.vw_DenialSignalStrength ORDER BY CramersV DESC)" 0
Scalar "Method" "dimensions tested" "[Dimensions Tested]" `
    "(SELECT COUNT(*) FROM analytics.vw_DenialSignalStrength)" 0
Scalar "Method" "dimensions with any signal" "[Dimensions with Signal]" `
    "(SELECT COUNT(*) FROM analytics.vw_DenialSignalStrength WHERE SignalVerdict = 'Signal')" 0
Scalar "Method" "providers measured" "[Providers Measured]" `
    "(SELECT COUNT(*) FROM analytics.vw_ProviderDenialChance)" 0
Scalar "Method" "providers beyond 2 standard errors" "[Providers Beyond 2 SE]" `
    "(SELECT COUNT(*) FROM analytics.vw_ProviderDenialChance WHERE ChanceBand <> 'Within chance')" 0
Scalar "Method" "share beyond 2 SE" "[Providers Beyond 2 SE %]" `
    "(SELECT CONVERT(FLOAT, SUM(CASE WHEN ChanceBand <> 'Within chance' THEN 1 ELSE 0 END)) / COUNT(*)
      FROM analytics.vw_ProviderDenialChance)" 0.000001
Scalar "Method" "the most extreme provider" "[Largest Provider Z-Score]" `
    "(SELECT MAX(ABS(ZScore)) FROM analytics.vw_ProviderDenialChance)" 0.001
Scalar "Method" "the group denial rate the providers are compared against" "[Group Denial Rate]" `
    "(SELECT MAX(GroupRate) FROM analytics.vw_ProviderDenialChance)" 0.000001
Scalar "Method" "findings recomputed each refresh" "[Findings Recorded]" `
    "(SELECT COUNT(*) FROM analytics.vw_DataQualityMetric)" 0
Scalar "Method" "calendar days the build had to add" "[Calendar Days Added]" `
    "(SELECT COUNT(*) FROM dim.DimDate WHERE InSuppliedCalendar = 0)" 0
Scalar "Method" "claims adjudicated outside the supplied calendar" "[Claims Outside Supplied Calendar]" `
    "(SELECT COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ProcessedDateKey
      WHERE d.InSuppliedCalendar = 0)" 0

# -- 2i. the stated assumptions, read from ModelConfig not typed into a measure
Scalar "Config" "currency" "[Currency]" `
    "(SELECT ConfigValue FROM dim.ModelConfig WHERE ConfigKey = 'Currency')" 0
Scalar "Config" "AR carried at" "[AR Carried At]" `
    "(SELECT ConfigValue FROM dim.ModelConfig WHERE ConfigKey = 'ARCarriedAt')" 0
Scalar "Config" "timely filing days" "[Timely Filing Days]" `
    "(SELECT CONVERT(INT, ConfigValue) FROM dim.ModelConfig WHERE ConfigKey = 'TimelyFilingDays')" 0
# Compared as a formatted string on both sides: DAX returns a datetime and SQL a date,
# so the raw values render differently and would fail a correct result.
Scalar "Config" "the last submission date, which caps the DSO window" `
    "FORMAT ( [Last Submission Date], ""yyyy-mm-dd"" )" `
    "(SELECT CONVERT(NVARCHAR(10), $LASTSUB, 23))" 0

# ============================== GROUPED CHECKS ===============================
# Every DAX query below projects EXACTLY one key and one value with SELECTCOLUMNS.
# SUMMARIZECOLUMNS alone returns the grouping column plus anything it needed to get
# there, and the extra column silently becomes part of the row key.

Grouped "Money" "allowed by service month" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDate[MonthKey], "v", [Allowed] ),
    "k", DimDate[MonthKey], "v", [v]
)
"@ @"
SELECT d.MonthKey, SUM(c.AllowedAmount)
FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey
GROUP BY d.MonthKey ORDER BY d.MonthKey
"@ 0.01

Grouped "Money" "collected by service month" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDate[MonthKey], "v", [Collected] ),
    "k", DimDate[MonthKey], "v", [v]
)
"@ @"
SELECT d.MonthKey, SUM(c.PaidAmount)
FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey
GROUP BY d.MonthKey HAVING SUM(c.PaidAmount) <> 0 ORDER BY d.MonthKey
"@ 0.01

Grouped "Volume" "claims by service month" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDate[MonthKey], "v", [Claims] ),
    "k", DimDate[MonthKey], "v", [v]
)
"@ @"
SELECT d.MonthKey, COUNT(*)
FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey
GROUP BY d.MonthKey ORDER BY d.MonthKey
"@ 0

# The stock, month by month. This is the one that would catch an AR measure quietly
# summing across months instead of reading a single month end.
Grouped "AR" "open AR at each month end" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDate[MonthKey], "v", [Open AR] ),
    "k", DimDate[MonthKey], "v", [v]
)
"@ @"
SELECT d.MonthKey, SUM(s.ARAmount)
FROM fact.FactARSnapshot s JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
GROUP BY d.MonthKey ORDER BY d.MonthKey
"@ 0.01

Grouped "AR" "AR by ageing bucket" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimARBucket[ARBucket], "v", [Open AR] ),
    "k", DimARBucket[ARBucket], "v", [v]
)
"@ @"
SELECT b.ARBucket, SUM(s.ARAmount)
FROM fact.FactARSnapshot s
JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
JOIN dim.DimARBucket b ON b.ARBucketKey = s.ARBucketKey
WHERE d.[Date] = $ASOFEND
GROUP BY b.ARBucket ORDER BY b.ARBucket
"@ 0.01

Grouped "AR" "AR by payer" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimPayer[PayerName], "v", [Open AR] ),
    "k", DimPayer[PayerName], "v", [v]
)
"@ @"
SELECT p.PayerName, SUM(s.ARAmount)
FROM fact.FactARSnapshot s
JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
JOIN dim.DimPayer p ON p.PayerKey = s.PayerKey
WHERE d.[Date] = $ASOFEND
GROUP BY p.PayerName ORDER BY p.PayerName
"@ 0.01

Grouped "ARMove" "AR movement by type" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimARMovementType[MovementType], "v", [AR Movement] ),
    "k", DimARMovementType[MovementType], "v", [v]
)
"@ @"
SELECT t.MovementType, SUM(m.Amount)
FROM fact.FactARMovement m JOIN dim.DimARMovementType t ON t.ARMovementTypeKey = m.ARMovementTypeKey
GROUP BY t.MovementType ORDER BY t.MovementType
"@ 0.01

Grouped "Denials" "denials by reason" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDenialReason[DenialReason], "v", [Denials] ),
    "k", DimDenialReason[DenialReason], "v", [v]
)
"@ @"
SELECT r.DenialReason, COUNT(*)
FROM fact.FactDenial n JOIN dim.DimDenialReason r ON r.DenialReasonKey = n.DenialReasonKey
GROUP BY r.DenialReason ORDER BY r.DenialReason
"@ 0

Grouped "Denials" "denied value by reason category" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDenialReason[ReasonCategory], "v", [Denied Value] ),
    "k", DimDenialReason[ReasonCategory], "v", [v]
)
"@ @"
SELECT r.ReasonCategory, SUM(n.DeniedAllowed)
FROM fact.FactDenial n JOIN dim.DimDenialReason r ON r.DenialReasonKey = n.DenialReasonKey
GROUP BY r.ReasonCategory ORDER BY r.ReasonCategory
"@ 0.01

Grouped "Denials" "denials by workflow state" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDenialStatus[DenialStatus], "v", [Denials] ),
    "k", DimDenialStatus[DenialStatus], "v", [v]
)
"@ @"
SELECT s.DenialStatus, COUNT(*)
FROM fact.FactDenial n JOIN dim.DimDenialStatus s ON s.DenialStatusKey = n.DenialStatusKey
GROUP BY s.DenialStatus ORDER BY s.DenialStatus
"@ 0

# The finding itself, reconciled: Self Pay apart, the payers do not differ.
Grouped "Denials" "denial rate by payer" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimPayer[PayerName], "v", [Denial Rate %] ),
    "k", DimPayer[PayerName], "v", [v]
)
"@ @"
SELECT p.PayerName, CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
FROM fact.FactClaim c JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey
GROUP BY p.PayerName ORDER BY p.PayerName
"@ 0.000001

Grouped "Denials" "denial rate by facility type" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimFacility[FacilityType], "v", [Denial Rate %] ),
    "k", DimFacility[FacilityType], "v", [v]
)
"@ @"
SELECT f.FacilityType, CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
FROM fact.FactClaim c JOIN dim.DimFacility f ON f.FacilityKey = c.FacilityKey
GROUP BY f.FacilityType ORDER BY f.FacilityType
"@ 0.000001

Grouped "Denials" "denial rate by specialty" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimProvider[Specialty], "v", [Denial Rate %] ),
    "k", DimProvider[Specialty], "v", [v]
)
"@ @"
SELECT pr.Specialty, CONVERT(FLOAT, SUM(CONVERT(INT, c.IsDenied))) / COUNT(*)
FROM fact.FactClaim c JOIN dim.DimProvider pr ON pr.ProviderKey = c.ProviderKey
GROUP BY pr.Specialty ORDER BY pr.Specialty
"@ 0.000001

Grouped "Volume" "claims by adjudication status" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimClaimStatus[ClaimStatus], "v", [Claims] ),
    "k", DimClaimStatus[ClaimStatus], "v", [v]
)
"@ @"
SELECT s.ClaimStatus, COUNT(*)
FROM fact.FactClaim c JOIN dim.DimClaimStatus s ON s.ClaimStatusKey = c.ClaimStatusKey
GROUP BY s.ClaimStatus ORDER BY s.ClaimStatus
"@ 0

# The LINE table carries its own payer key. If it did not, this check would show a
# whole numerator against a shrinking denominator - which is the defect it exists for.
Grouped "Lines" "claim lines by payer" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimPayer[PayerName], "v", [Claim Lines] ),
    "k", DimPayer[PayerName], "v", [v]
)
"@ @"
SELECT p.PayerName, COUNT(*)
FROM fact.FactClaimLine l JOIN dim.DimPayer p ON p.PayerKey = l.PayerKey
GROUP BY p.PayerName ORDER BY p.PayerName
"@ 0

Grouped "Lines" "claim lines by service line" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimProcedure[ServiceLine], "v", [Claim Lines] ),
    "k", DimProcedure[ServiceLine], "v", [v]
)
"@ @"
SELECT pr.ServiceLine, COUNT(*)
FROM fact.FactClaimLine l JOIN dim.DimProcedure pr ON pr.ProcedureKey = l.ProcedureKey
GROUP BY pr.ServiceLine ORDER BY pr.ServiceLine
"@ 0

Grouped "Lines" "claim lines by ICD-10 category" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimDiagnosis[DiagnosisCode], "v", [Claim Lines] ),
    "k", DimDiagnosis[DiagnosisCode], "v", [v]
)
"@ @"
SELECT dg.DiagnosisCode, COUNT(*)
FROM fact.FactClaimLine l JOIN dim.DimDiagnosis dg ON dg.DiagnosisKey = l.DiagnosisKey
GROUP BY dg.DiagnosisCode ORDER BY dg.DiagnosisCode
"@ 0

Grouped "Clock" "days to cash by payer" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimPayer[PayerName], "v", [Days to Cash] ),
    "k", DimPayer[PayerName], "v", [v]
)
"@ @"
SELECT p.PayerName, AVG(CONVERT(FLOAT, pay.DaysToPay))
FROM fact.FactPayment pay JOIN dim.DimPayer p ON p.PayerKey = pay.PayerKey
GROUP BY p.PayerName ORDER BY p.PayerName
"@ 0.0001

Grouped "Clock" "days to cash by remittance method" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DimPaymentMethod[PaymentMethod], "v", [Days to Cash] ),
    "k", DimPaymentMethod[PaymentMethod], "v", [v]
)
"@ @"
SELECT m.PaymentMethod, AVG(CONVERT(FLOAT, pay.DaysToPay))
FROM fact.FactPayment pay JOIN dim.DimPaymentMethod m ON m.PaymentMethodKey = pay.PaymentMethodKey
GROUP BY m.PaymentMethod ORDER BY m.PaymentMethod
"@ 0.0001

Grouped "Method" "signal strength by dimension" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DenialSignal[Dimension], "v", [Signal Strength] ),
    "k", DenialSignal[Dimension], "v", [v]
)
"@ @"
SELECT Dimension, CramersV FROM analytics.vw_DenialSignalStrength ORDER BY Dimension
"@ 0.0001

Grouped "Method" "provider count by denial-rate band" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( ProviderChance[RateBand], "v", [Providers Measured] ),
    "k", ProviderChance[RateBand], "v", [v]
)
"@ @"
SELECT RateBand, COUNT(*) FROM analytics.vw_ProviderDenialChance GROUP BY RateBand ORDER BY RateBand
"@ 0

Grouped "Method" "the audit findings" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS ( DataQualityMetric[Metric], "v", SUM ( DataQualityMetric[MetricValue] ) ),
    "k", DataQualityMetric[Metric], "v", [v]
)
"@ @"
SELECT Metric, MetricValue FROM analytics.vw_DataQualityMetric ORDER BY Metric
"@ 0.0001

# -- the calculation groups ---------------------------------------------------
# DATE BASIS: the same measure read on four different clocks. Each one must match the
# SQL that joins on that clock's own date column - which is the whole claim the
# calculation group makes.
Grouped "CalcGroup" "claims in Aug 2026 under each date basis" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS (
        'Date Basis'[Basis],
        TREATAS ( { 202608 }, DimDate[MonthKey] ),
        "v", [Claims]
    ),
    "k", 'Date Basis'[Basis], "v", [v]
)
"@ @"
SELECT 'Service date', COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey WHERE d.MonthKey = 202608
UNION ALL SELECT 'Submission date', COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey WHERE d.MonthKey = 202608
UNION ALL SELECT 'Adjudication date', COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ProcessedDateKey WHERE d.MonthKey = 202608
UNION ALL SELECT 'Resolution date', COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ResolvedDateKey WHERE d.MonthKey = 202608
"@ 0

# TIME COMPARISON: the same measure shifted. Prior month and prior year are computed
# in SQL by reading those months directly, not by subtracting anything.
Grouped "CalcGroup" "allowed in Aug 2026 under each time comparison" @"
EVALUATE
SELECTCOLUMNS (
    SUMMARIZECOLUMNS (
        'Time Comparison'[Comparison],
        TREATAS ( { 202608 }, DimDate[MonthKey] ),
        "v", [Allowed]
    ),
    "k", 'Time Comparison'[Comparison], "v", [v]
)
"@ @"
WITH M AS (
    SELECT d.MonthKey, SUM(c.AllowedAmount) AS v
    FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey
    GROUP BY d.MonthKey
)
SELECT 'Selected period', (SELECT v FROM M WHERE MonthKey = 202608)
UNION ALL SELECT 'Prior month', (SELECT v FROM M WHERE MonthKey = 202607)
UNION ALL SELECT 'Month over month', (SELECT v FROM M WHERE MonthKey = 202608) - (SELECT v FROM M WHERE MonthKey = 202607)
UNION ALL SELECT 'Month over month %', ((SELECT v FROM M WHERE MonthKey = 202608) - (SELECT v FROM M WHERE MonthKey = 202607))
                                        / (SELECT v FROM M WHERE MonthKey = 202607)
UNION ALL SELECT 'Prior year', (SELECT v FROM M WHERE MonthKey = 202508)
UNION ALL SELECT 'Trailing 12 months', (SELECT SUM(v) FROM M WHERE MonthKey BETWEEN 202509 AND 202608)
"@ 0.01

# ------------------------------------------------------------- 3. security ---
Write-Host "`n== 3. SECURITY: the role's default and its mapping logic ==" -ForegroundColor Yellow

# The secure default first: a user with no mapping row sees NOTHING. If this passes
# only because the expression happens to return everything, the whole role is a hole.
$d = Dax @"
EVALUATE
VAR UserFacilities = CALCULATETABLE ( VALUES ( SecurityUserAccess[FacilityID] ),
                                      SecurityUserAccess[UserEmail] = "nobody@health.demo" )
VAR VisibleFacilities = FILTER ( ALL ( DimFacility[FacilityID] ),
                                 "ALL" IN UserFacilities || DimFacility[FacilityID] IN UserFacilities )
RETURN
ROW (
    "facilities", COALESCE ( COUNTROWS ( VisibleFacilities ), 0 ),
    "allowed", COALESCE ( CALCULATE ( [Allowed], TREATAS ( VisibleFacilities, DimFacility[FacilityID] ) ), 0 )
)
"@
Check "Security" "an unmapped user sees no facilities" $d.Rows[0][0] 0 0
Check "Security" "an unmapped user sees no money" $d.Rows[0][1] 0 0.01

# Then every mapped user's scope, evaluated through the role's own filter expression
# and compared with SQL. EffectiveUserName cannot be used here: the synthetic
# addresses are not Windows accounts on this machine.
$users = (Sql "SELECT UserEmail, [Role], FacilityID, ProviderID FROM dim.SecurityUserAccess ORDER BY UserEmail")
foreach ($u in $users.Rows) {
    $email = $u[0]; $fac = $u[2]
    $d = Dax @"
EVALUATE
VAR UserFacilities = CALCULATETABLE ( VALUES ( SecurityUserAccess[FacilityID] ),
                                      SecurityUserAccess[UserEmail] = "$email" )
VAR VisibleFacilities = FILTER ( ALL ( DimFacility[FacilityID] ),
                                 "ALL" IN UserFacilities || DimFacility[FacilityID] IN UserFacilities )
RETURN
ROW (
    "facilities", COUNTROWS ( VisibleFacilities ),
    "allowed", CALCULATE ( [Allowed], TREATAS ( VisibleFacilities, DimFacility[FacilityID] ) )
)
"@
    $expectedFacilities = if ($fac -eq "ALL") { 30 } else { 1 }
    Check "Security" "$email sees facilities" $d.Rows[0][0] $expectedFacilities 0
    $where = if ($fac -eq "ALL") { "1 = 1" } else { "f.FacilityID = '$fac'" }
    $e = (Sql @"
SELECT SUM(c.AllowedAmount) FROM fact.FactClaim c
JOIN dim.DimFacility f ON f.FacilityKey = c.FacilityKey
WHERE $where
"@).Rows[0][0]
    Check "Security" "$email sees the right allowed amount" $d.Rows[0][1] ([double]$e) 0.01
}

# Provider and facility are ONE hierarchy: a facility-scoped user must see that
# facility's providers and no others, or the provider slicer lists 500 names with
# nothing behind them.
$oneFac = (Sql "SELECT TOP 1 FacilityID FROM dim.SecurityUserAccess WHERE FacilityID <> 'ALL' ORDER BY FacilityID").Rows[0][0]
$email = (Sql "SELECT TOP 1 UserEmail FROM dim.SecurityUserAccess WHERE FacilityID = '$oneFac'").Rows[0][0]
$d = Dax @"
EVALUATE
VAR UserFacilities = CALCULATETABLE ( VALUES ( SecurityUserAccess[FacilityID] ),
                                      SecurityUserAccess[UserEmail] = "$email" )
VAR VisibleProviders = FILTER ( ALL ( DimProvider[ProviderID], DimProvider[FacilityID] ),
                                "ALL" IN UserFacilities || DimProvider[FacilityID] IN UserFacilities )
RETURN ROW ( "providers", COUNTROWS ( VisibleProviders ) )
"@
$e = (Sql "SELECT COUNT(*) FROM dim.DimProvider WHERE FacilityID = '$oneFac'").Rows[0][0]
Check "Security" "a facility manager sees only that facility's providers" $d.Rows[0][0] ([double]$e) 0
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
