<#
    A rendered page proves a visual draws. These tests prove the page still tells the
    truth when a reader USES it: each interactive state is reproduced as the query that
    state produces, and compared with independently written SQL.

    What is covered:
      slicers            payer, facility, specialty, status, age band - alone and paired
      filter travel      a dimension filter reaching EVERY fact, not just the claim
                         header: lines by payer, denials by specialty, cash by payer,
                         AR movement by facility type. This is the defect that took
                         longest to find in the previous project in this series.
      calculation groups every Date Basis clock against the SQL that joins on that
                         clock, and both groups applied TOGETHER - the precedence is
                         the point
      the identities     the four-bucket identity inside a payer, a facility type, a
                         specialty and a month. An identity that closes only at the
                         grand total is not an identity
      the data boundary  nothing is reported past the as-of month, whatever is selected
      field parameter    the ten cuts the Breakdown parameter offers
      cross-filtering    a denial reason filters denials and NOT claims

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
if (-not $cat) { throw "No live Power BI model. Open HealthcareRCM.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;Initial Catalog=$cat")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=HealthcareRCMBI;Integrated Security=True;TrustServerCertificate=True")
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
}$ASOFEND = "(SELECT EOMONTH(CONVERT(DATE, ConfigValue, 23)) FROM dim.ModelConfig WHERE ConfigKey = 'AsOfDate')"

# ------------------------------------------------------------------ slicers ---
Write-Host "`n== slicers ==" -ForegroundColor Yellow
$slicers = @(
    @{ n = "payer = Medicare";          dax = 'DimPayer[PayerName] = "Medicare"';        where = "p.PayerName = 'Medicare'" },
    @{ n = "payer = Self Pay";          dax = 'DimPayer[PayerName] = "Self Pay"';        where = "p.PayerName = 'Self Pay'" },
    @{ n = "facility type = Hospital";  dax = 'DimFacility[FacilityType] = "Hospital"';  where = "f.FacilityType = 'Hospital'" },
    @{ n = "state = NSW";               dax = 'DimFacility[State] = "NSW"';              where = "f.[State] = 'NSW'" },
    @{ n = "specialty = Cardiology";    dax = 'DimProvider[Specialty] = "Cardiology"';   where = "pr.Specialty = 'Cardiology'" },
    @{ n = "status = Denied";           dax = 'DimClaimStatus[ClaimStatus] = "Denied"';  where = "s.ClaimStatus = 'Denied'" },
    @{ n = "age band = 75 and over";    dax = 'DimPatient[AgeBand] = "75 and over"';     where = "b.AgeBandKey = 5" }
)
foreach ($s in $slicers) {
    $a = (Dax "EVALUATE ROW ( ""v"", CALCULATE ( [Allowed], $($s.dax) ) )").Rows[0][0]
    $e = (Sql @"
SELECT SUM(c.AllowedAmount) FROM fact.FactClaim c
JOIN dim.DimPayer p        ON p.PayerKey = c.PayerKey
JOIN dim.DimFacility f     ON f.FacilityKey = c.FacilityKey
JOIN dim.DimProvider pr    ON pr.ProviderKey = c.ProviderKey
JOIN dim.DimClaimStatus s  ON s.ClaimStatusKey = c.ClaimStatusKey
JOIN dim.DimBeneficiary b  ON b.BeneficiaryKey = c.BeneficiaryKey
WHERE $($s.where)
"@).Rows[0][0]
    Check "allowed with $($s.n)" $a ([double]$e) 0.01
}

# Two at once. A filter that only works alone is not a filter.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Allowed], DimPayer[PayerName] = "Medicare", DimFacility[FacilityType] = "Hospital" ) )').Rows[0][0]
$e = (Sql @"
SELECT SUM(c.AllowedAmount) FROM fact.FactClaim c
JOIN dim.DimPayer p ON p.PayerKey = c.PayerKey
JOIN dim.DimFacility f ON f.FacilityKey = c.FacilityKey
WHERE p.PayerName = 'Medicare' AND f.FacilityType = 'Hospital'
"@).Rows[0][0]
Check "allowed with payer AND facility type together" $a ([double]$e) 0.01

# ------------------------------------------------ the filter that must travel ---
# THE test this model was designed around. Each of these reads a measure from a
# DIFFERENT fact than the dimension is usually thought to belong to. If any fact were
# missing its own key, the filter would stop at the claim header and leave the other
# table whole - a full numerator over a shrinking denominator, which reads as a
# plausible number and is wrong.
Write-Host "`n== a filter reaches every fact, not just the claim header ==" -ForegroundColor Yellow
$travel = @(
    @{ n = "claim LINES by payer";        m = "[Claim Lines]";  dax = 'DimPayer[PayerName] = "Bupa"'
       sql = "SELECT COUNT(*) FROM fact.FactClaimLine l JOIN dim.DimPayer p ON p.PayerKey = l.PayerKey WHERE p.PayerName = 'Bupa'" },
    @{ n = "claim LINES by specialty";    m = "[Claim Lines]";  dax = 'DimProvider[Specialty] = "Oncology"'
       sql = "SELECT COUNT(*) FROM fact.FactClaimLine l JOIN dim.DimProvider pr ON pr.ProviderKey = l.ProviderKey WHERE pr.Specialty = 'Oncology'" },
    @{ n = "DENIALS by specialty";        m = "[Denials]";      dax = 'DimProvider[Specialty] = "Oncology"'
       sql = "SELECT COUNT(*) FROM fact.FactDenial n JOIN dim.DimProvider pr ON pr.ProviderKey = n.ProviderKey WHERE pr.Specialty = 'Oncology'" },
    @{ n = "DENIALS by facility type";    m = "[Denials]";      dax = 'DimFacility[FacilityType] = "Clinic"'
       sql = "SELECT COUNT(*) FROM fact.FactDenial n JOIN dim.DimFacility f ON f.FacilityKey = n.FacilityKey WHERE f.FacilityType = 'Clinic'" },
    @{ n = "CASH by payer";               m = "[Cash Received]"; dax = 'DimPayer[PayerName] = "NIB"'
       sql = "SELECT SUM(pay.PaymentAmount) FROM fact.FactPayment pay JOIN dim.DimPayer p ON p.PayerKey = pay.PayerKey WHERE p.PayerName = 'NIB'" },
    @{ n = "AR MOVEMENT by facility type"; m = "[AR Movement]"; dax = 'DimFacility[FacilityType] = "Imaging Centre"'
       sql = "SELECT SUM(m.Amount) FROM fact.FactARMovement m JOIN dim.DimFacility f ON f.FacilityKey = m.FacilityKey WHERE f.FacilityType = 'Imaging Centre'" }
)
foreach ($t in $travel) {
    $a = (Dax "EVALUATE ROW ( ""v"", CALCULATE ( $($t.m), $($t.dax) ) )").Rows[0][0]
    $e = (Sql $t.sql).Rows[0][0]
    Check $t.n $a ([double]$e) 0.01
}

# The receivable is a STOCK read from the snapshot, and it has to obey a slicer too.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Open AR], DimPayer[PayerName] = "HCF" ) )').Rows[0][0]
$e = (Sql @"
SELECT SUM(s.ARAmount) FROM fact.FactARSnapshot s
JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
JOIN dim.DimPayer p ON p.PayerKey = s.PayerKey
WHERE d.[Date] = $ASOFEND AND p.PayerName = 'HCF'
"@).Rows[0][0]
Check "open AR with payer = HCF" $a ([double]$e) 0.01

# --------------------------------------------------------- calculation groups ---
Write-Host "`n== calculation groups ==" -ForegroundColor Yellow
# DATE BASIS: the same measure on four clocks, each checked against the SQL that joins
# on that clock's own date column.
$bases = @(
    @{ n = "Service date";      col = "ServiceDateKey" },
    @{ n = "Submission date";   col = "SubmittedDateKey" },
    @{ n = "Adjudication date"; col = "ProcessedDateKey" },
    @{ n = "Resolution date";   col = "ResolvedDateKey" }
)
foreach ($b in $bases) {
    $a = (Dax @"
EVALUATE
ROW ( "v", CALCULATE ( [Claims], 'Date Basis'[Basis] = "$($b.n)", DimDate[MonthKey] = 202607 ) )
"@).Rows[0][0]
    $e = (Sql "SELECT COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.$($b.col) WHERE d.MonthKey = 202607").Rows[0][0]
    Check "date basis '$($b.n)' in Jul 2026" $a ([double]$e) 0
}

# TIME COMPARISON, and then the two groups TOGETHER. The precedence is the point:
# Time Comparison outranks Date Basis, so "prior month on submission date" has to mean
# the month before, measured on submission - not the submission-date version of last
# month's service figure.
$a = (Dax @"
EVALUATE
ROW ( "v", CALCULATE ( [Claims], 'Time Comparison'[Comparison] = "Prior month",
                       'Date Basis'[Basis] = "Submission date", DimDate[MonthKey] = 202607 ) )
"@).Rows[0][0]
$e = (Sql "SELECT COUNT(*) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.SubmittedDateKey WHERE d.MonthKey = 202606").Rows[0][0]
Check "prior month AND submission basis together" $a ([double]$e) 0

$a = (Dax @"
EVALUATE
ROW ( "v", CALCULATE ( [Allowed], 'Time Comparison'[Comparison] = "Trailing 12 months", DimDate[MonthKey] = 202608 ) )
"@).Rows[0][0]
$e = (Sql @"
SELECT SUM(c.AllowedAmount) FROM fact.FactClaim c JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey
WHERE d.MonthKey BETWEEN 202509 AND 202608
"@).Rows[0][0]
Check "trailing twelve months to Aug 2026" $a ([double]$e) 0.01

$a = (Dax @"
EVALUATE
ROW ( "v", CALCULATE ( [Allowed], 'Time Comparison'[Comparison] = "Month over month %", DimDate[MonthKey] = 202608 ) )
"@).Rows[0][0]
$e = (Sql @"
WITH M AS (SELECT d.MonthKey, SUM(c.AllowedAmount) v FROM fact.FactClaim c
           JOIN dim.DimDate d ON d.DateKey = c.ServiceDateKey GROUP BY d.MonthKey)
SELECT ((SELECT v FROM M WHERE MonthKey = 202608) - (SELECT v FROM M WHERE MonthKey = 202607))
       / (SELECT v FROM M WHERE MonthKey = 202607)
"@).Rows[0][0]
Check "month over month % in Aug 2026" $a ([double]$e) 0.000001

# A comparison with nothing to compare against must be BLANK, not the whole figure
# reported as growth.
$a = (Dax @"
EVALUATE
ROW ( "v", CALCULATE ( [Allowed], 'Time Comparison'[Comparison] = "Prior month", DimDate[MonthKey] = 202301 ) )
"@).Rows[0][0]
Check "prior month in the FIRST month is blank" $a $null 0

# ---------------------------------------------------------- the data boundary ---
Write-Host "`n== the data boundary ==" -ForegroundColor Yellow
# Nothing may be reported past the as-of month, whatever is selected. A stock that
# ignores this draws today's receivable flat into next year and calls it a forecast.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Open AR], DimDate[MonthKey] = 202612 ) )').Rows[0][0]
Check "open AR beyond the as-of month is blank" $a $null 0
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Days in AR], DimDate[MonthKey] = 202612 ) )').Rows[0][0]
Check "days in AR beyond the as-of month is blank" $a $null 0
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Claims], DimDate[MonthKey] = 202612 ) )').Rows[0][0]
Check "claims in a month with no service is blank" $a $null 0

# The receivable at the as-of month end, selected explicitly, is the same figure the
# report shows with nothing selected - because the measure caps at the as-of month.
$unfiltered = (Dax 'EVALUATE ROW ( "v", [Open AR] )').Rows[0][0]
$explicit = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Open AR], DimDate[MonthKey] = 202611 ) )').Rows[0][0]
Check "open AR unfiltered = open AR at the as-of month" $unfiltered ([double]$explicit) 0.01

# ------------------------------------------------------------ the identities ---
Write-Host "`n== the identities hold under a slice ==" -ForegroundColor Yellow
# An identity that only closes at the grand total is not an identity. These check it
# inside a payer, inside a facility type, and inside a month.
foreach ($slice in @('DimPayer[PayerName] = "Medibank"', 'DimFacility[FacilityType] = "Day Surgery"',
                     'DimDate[MonthKey] = 202405', 'DimProvider[Specialty] = "Radiology"')) {
    $a = (Dax "EVALUATE ROW ( ""v"", CALCULATE ( [Allowed Identity Gap], $slice ) )").Rows[0][0]
    Check "the allowed identity holds under $slice" $a 0 0.005
}
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [AR Roll-Forward Check], DimDate[MonthKey] = 202405 ) )').Rows[0][0]
Check "the AR roll-forward holds in May 2024" $a 0 0.01

# ----------------------------------------------------------- field parameter ---
Write-Host "`n== the field parameter ==" -ForegroundColor Yellow
# Every field the Breakdown parameter offers must resolve to a real column with the
# expected number of distinct values. NOT covered here, and said rather than implied:
# whether Power BI substitutes the chosen column INSIDE a visual. That happens when the
# visual's query is built, not in a query this script can write, so it is proven by
# rendering the page and reading the axis - see Validation/evidence/.
$cuts = @(
    @{ n = "Payer";             tbl = "DimPayer";        col = "PayerName";        sql = "SELECT COUNT(DISTINCT PayerName) FROM dim.DimPayer" },
    @{ n = "Payer type";        tbl = "DimPayer";        col = "PayerType";        sql = "SELECT COUNT(DISTINCT PayerType) FROM dim.DimPayer" },
    @{ n = "Facility";          tbl = "DimFacility";     col = "FacilityName";     sql = "SELECT COUNT(DISTINCT FacilityName) FROM dim.DimFacility" },
    @{ n = "Facility type";     tbl = "DimFacility";     col = "FacilityType";     sql = "SELECT COUNT(DISTINCT FacilityType) FROM dim.DimFacility" },
    @{ n = "Specialty";         tbl = "DimProvider";     col = "Specialty";        sql = "SELECT COUNT(DISTINCT Specialty) FROM dim.DimProvider" },
    @{ n = "State";             tbl = "DimFacility";     col = "State";            sql = "SELECT COUNT(DISTINCT [State]) FROM dim.DimFacility" },
    @{ n = "Denial reason";     tbl = "DimDenialReason"; col = "DenialReason";     sql = "SELECT COUNT(DISTINCT DenialReason) FROM dim.DimDenialReason" },
    @{ n = "Reason category";   tbl = "DimDenialReason"; col = "ReasonCategory";   sql = "SELECT COUNT(DISTINCT ReasonCategory) FROM dim.DimDenialReason" },
    @{ n = "Patient age band";  tbl = "DimPatient";      col = "AgeBand";          sql = "SELECT COUNT(DISTINCT AgeBand) FROM dim.DimAgeBand" },
    @{ n = "Chronic risk band"; tbl = "DimPatient";      col = "ChronicRiskBand";  sql = "SELECT COUNT(DISTINCT ChronicRiskBand) FROM dim.DimBeneficiary" }
)
foreach ($c in $cuts) {
    $a = (Dax "EVALUATE ROW ( ""v"", COUNTROWS ( VALUES ( $($c.tbl)[$($c.col)] ) ) )").Rows[0][0]
    $e = (Sql $c.sql).Rows[0][0]
    Check "cut '$($c.n)' resolves to $($c.tbl)[$($c.col)]" $a ([double]$e) 0
}
$a = (Dax 'EVALUATE ROW ( "v", COUNTROWS ( Breakdown ) )').Rows[0][0]
Check "the Breakdown parameter offers 10 cuts" $a 10 0

# ------------------------------------------------------------ cross-filtering ---
Write-Host "`n== cross-filtering ==" -ForegroundColor Yellow
# Selecting a bar on one visual has to reach the others on the page. Selecting a denial
# REASON must filter the denial count, and must NOT change the claim count - a reason
# is a property of a denial, not of a claim, and a bidirectional relationship here
# would quietly make it look like one.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Denials], DimDenialReason[DenialReason] = "Timely Filing" ) )').Rows[0][0]
$e = (Sql "SELECT COUNT(*) FROM fact.FactDenial n JOIN dim.DimDenialReason r ON r.DenialReasonKey = n.DenialReasonKey WHERE r.DenialReason = 'Timely Filing'").Rows[0][0]
Check "selecting a denial reason filters the denials" $a ([double]$e) 0

$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Claims], DimDenialReason[DenialReason] = "Timely Filing" ) )').Rows[0][0]
$e = (Sql "SELECT COUNT(*) FROM fact.FactClaim").Rows[0][0]
Check "and does NOT filter the claim count" $a ([double]$e) 0

# Selecting an ageing bucket filters the receivable but not the billed total: a bucket
# is a property of an OPEN claim at a month end.
$a = (Dax 'EVALUATE ROW ( "v", CALCULATE ( [Open AR], DimARBucket[ARBucket] = "365+" ) )').Rows[0][0]
$e = (Sql @"
SELECT SUM(s.ARAmount) FROM fact.FactARSnapshot s
JOIN dim.DimDate d ON d.DateKey = s.SnapshotDateKey
JOIN dim.DimARBucket b ON b.ARBucketKey = s.ARBucketKey
WHERE d.[Date] = $ASOFEND AND b.ARBucket = '365+'
"@).Rows[0][0]
Check "selecting the 365+ bucket filters the receivable" $a ([double]$e) 0.01
$conn.Close(); $sql.Close()
Write-Host ""
$colour = if ($script:fail) { "Red" } else { "Green" }
Write-Host ("INTERACTIONS: {0} of {1} checks passed" -f $script:pass, ($script:pass + $script:fail)) -ForegroundColor $colour
if ($script:fail) { exit 1 }
exit 0
