<#
    Live validation of the semantic model, run with Power BI Desktop open and refreshed.

    Step 1  SWEEP      every measure is evaluated alone. One broken measure poisons the
                       whole model script (project 1: 'Failed to resolve name SYNTAXERROR'),
                       so nothing else is trusted until this passes. Grand-total values are
                       written to Validation/measure_values.csv for the measure dictionary.
    Step 2  RECONCILE  every measure is compared with an independently written SQL query
                       against MarketingAttributionBI - scalar totals, per-channel results
                       for all five attribution models, date-role measures and slicing.
    Step 3  REPORT     every figure a report visual shows, at the grain the visual shows it,
                       against SQL (Phase 4). Includes the finance tie-out: under EVERY model,
                       attributed revenue by booking month equals revenue booked that month.
    Step 4  SECURITY   the Regional Marketing role is tested for its secure default.

    AS OF (PROJECT_STATE D33): every expected value counts only what happened on or
    before the as-of date - opportunities opened, revenue booked - exactly as the model
    does. SQL computes it from the dbo tables and their IsAfterAsOf flags, never from the
    analytics views the model reads.

    SQL expected values that divide are computed in FLOAT: SQL Server rounds a
    DECIMAL / DECIMAL quotient to as few as 6 decimal places, which would fail a
    correct DAX result (it did, for ROAS, on the first run).

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
if (-not $script:cat) { throw "No live Power BI model. Open OmnichannelAttribution.pbip first." }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$($script:port);Initial Catalog=$($script:cat)")
$conn.Open()
$sql = New-Object System.Data.SqlClient.SqlConnection("Server=$SqlServer;Database=MarketingAttributionBI;Integrated Security=True;TrustServerCertificate=True")
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
    if (-not $ok) { Write-Host ("  [FAIL] {0,-10} {1,-58} expected {2} got {3}" -f $area, $name, $expected, $actual) -ForegroundColor Red }
}
function Scalar($area, $name, $daxExpr, $sqlExpr, $tol) {
    $a = (Dax "EVALUATE ROW ( ""v"", $daxExpr )").Rows[0][0]
    $e = (Sql "SELECT $sqlExpr").Rows[0][0]
    if ($e -is [string]) { Check $area $name "$a" $e 0 } else { Check $area $name $a ([double]$e) $tol }
}
# A row's key is every column but the last, joined; the last column is the value.
# This lets a check compare a visual's full grain - quarter x channel, segment x group.
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

$ASOF = "(SELECT CONVERT(DATE, ConfigValue, 23) FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate')"
$ASOFJOIN = "CROSS JOIN (SELECT CONVERT(DATE, ConfigValue, 23) AS a FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate') k"
$WON = "(SELECT COUNT(*) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0)"
$OPPS = "(SELECT COUNT(*) FROM dbo.FactOpportunity WHERE IsAfterAsOf = 0)"
$SPEND = "(SELECT SUM(CAST(SpendUSD AS FLOAT)) FROM dbo.FactAdSpend)"
$REV = "(SELECT SUM(CAST(RevenueUSD AS FLOAT)) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0)"
$PB = "c.ModelKey = 4 AND c.RevenueDate IS NOT NULL AND c.IsRevenueAfterAsOf = 0"   # default model, booked by the as-of date
# Stage each lead had reached by the as-of date, written from the dbo tables.
$STAGE = "(SELECT CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN 5 WHEN o.OpportunityID IS NOT NULL AND o.IsAfterAsOf = 0 THEN 4 WHEN l.StageRank >= 4 THEN 3 ELSE l.StageRank END AS rk FROM dbo.FactLead l LEFT JOIN dbo.FactOpportunity o ON o.LeadID = l.LeadID LEFT JOIN dbo.FactRevenue r ON r.OpportunityID = o.OpportunityID) x"

# -------------------------------------------------------------- 1. sweep ---
Write-Host "`n== 1. SWEEP: every measure evaluated alone ==" -ForegroundColor Yellow
$tmdl = Join-Path $PSScriptRoot "..\PowerBI\OmnichannelAttribution.SemanticModel\definition\tables\_Measures.tmdl"
$names = @(); foreach ($ln in (Get-Content -LiteralPath $tmdl)) { if ($ln -match "^\tmeasure '([^']+)'") { $names += $Matches[1] } elseif ($ln -match "^\tmeasure (\S+) =") { $names += $Matches[1] } }
$swept = 0; $errs = @(); $values = @()
foreach ($n in $names) {
    try {
        $v = (Dax ("EVALUATE ROW ( ""v"", [" + $n.Replace("]", "]]") + "] )")).Rows[0][0]
        if ($v -is [datetime]) { $v = $v.ToString("yyyy-MM-dd") }
        $values += [pscustomobject]@{ Measure = $n; Value = $(if ($v -is [System.DBNull]) { "" } else { "$v" }) }
        $swept++
    } catch { $errs += "$n :: $($_.Exception.Message)" }
}
Check "Sweep" "measures evaluating without error" $swept $names.Count 0
$errs | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
if ($errs.Count) { Write-Host "Sweep failed - reconciliation skipped: nothing is trustworthy until every measure evaluates." -ForegroundColor Red; exit 1 }
$values | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $PSScriptRoot "measure_values.csv")

# ---------------------------------------------------------- 2. reconcile ---
Write-Host "`n== 2. RECONCILE: DAX vs independent SQL ==" -ForegroundColor Yellow
Scalar "Controls" "As Of Date"               'FORMAT ( [As Of Date], "yyyy-mm-dd" )' "(SELECT ConfigValue FROM dbo.ModelConfig WHERE ConfigKey = 'AsOfDate')" 0
Scalar "Controls" "Attribution Model In Use (default)" '[Attribution Model In Use]' "(SELECT ConfigValue FROM dbo.ModelConfig WHERE ConfigKey = 'DefaultAttributionModel')" 0
Scalar "Controls" "Reporting Currency"       '[Reporting Currency]' "(SELECT ConfigValue FROM dbo.ModelConfig WHERE ConfigKey = 'ReportingCurrency')" 0
Scalar "Controls" "Report Context line"      '[Report Context]' "'Data as of ' + FORMAT($ASOF, 'd MMM yyyy', 'en-US') + '  |  Attribution: ' + (SELECT ConfigValue FROM dbo.ModelConfig WHERE ConfigKey = 'DefaultAttributionModel') + '  |  USD at planning FX'" 0
Scalar "Controls" "Conversion Window Days (longest lead-to-revenue)" '[Conversion Window Days]' "MAX(DATEDIFF(DAY, l.CreatedDate, r.RevenueDate)) FROM dbo.FactRevenue r JOIN dbo.FactLead l ON l.LeadID = r.LeadID" 0

Scalar "Media" "Spend USD"            '[Spend USD]'            "SUM(SpendUSD) FROM dbo.FactAdSpend" 0.01
Scalar "Media" "Paid Media Spend USD" '[Paid Media Spend USD]' "SUM(a.SpendUSD) FROM dbo.FactAdSpend a JOIN dbo.DimChannel ch ON ch.ChannelID = a.ChannelID WHERE ch.IsPaidMedia = 1" 0.01
Scalar "Media" "Impressions"          '[Impressions]'          "SUM(CAST(Impressions AS BIGINT)) FROM dbo.FactAdSpend" 0
Scalar "Media" "Clicks"               '[Clicks]'               "SUM(CAST(Clicks AS BIGINT)) FROM dbo.FactAdSpend" 0
Scalar "Media" "CTR"                  '[CTR]'                  "SUM(CAST(Clicks AS FLOAT)) / SUM(CAST(Impressions AS FLOAT)) FROM dbo.FactAdSpend" 0.000000001
Scalar "Media" "CPC USD"              '[CPC USD]'              "SUM(CAST(SpendUSD AS FLOAT)) / SUM(CAST(Clicks AS FLOAT)) FROM dbo.FactAdSpend" 0.000001
Scalar "Media" "CPM USD"              '[CPM USD]'              "1000 * SUM(CAST(SpendUSD AS FLOAT)) / SUM(CAST(Impressions AS FLOAT)) FROM dbo.FactAdSpend" 0.000001
$PAID = "FROM dbo.FactAdSpend a JOIN dbo.DimChannel ch ON ch.ChannelID = a.ChannelID WHERE ch.IsPaidMedia = 1"
Scalar "Media" "Paid CTR"             '[Paid CTR]'             "SUM(CAST(a.Clicks AS FLOAT)) / SUM(CAST(a.Impressions AS FLOAT)) $PAID" 0.000000001
Scalar "Media" "Paid CPC USD"         '[Paid CPC USD]'         "SUM(CAST(a.SpendUSD AS FLOAT)) / SUM(CAST(a.Clicks AS FLOAT)) $PAID" 0.000001
Scalar "Media" "Paid CPM USD"         '[Paid CPM USD]'         "1000 * SUM(CAST(a.SpendUSD AS FLOAT)) / SUM(CAST(a.Impressions AS FLOAT)) $PAID" 0.000001
Scalar "Media" "Spend Share % (total = 1)" '[Spend Share %]'   "1.0" 0.000000001
Scalar "Media" "Click-to-Lead %"      '[Click-to-Lead %]'      "CAST((SELECT COUNT(*) FROM dbo.FactLead) AS FLOAT) / (SELECT SUM(CAST(Clicks AS FLOAT)) FROM dbo.FactAdSpend)" 0.000000001

Scalar "Funnel" "Leads"          '[Leads]'          "COUNT(*) FROM dbo.FactLead" 0
Scalar "Funnel" "MQLs"           '[MQLs]'           "COUNT(*) FROM dbo.FactLead WHERE ReachedMQL = 1" 0
Scalar "Funnel" "SQLs"           '[SQLs]'           "COUNT(*) FROM dbo.FactLead WHERE ReachedSQL = 1" 0
Scalar "Funnel" "Opportunities (opened by the as-of date)" '[Opportunities]' "COUNT(*) FROM dbo.FactOpportunity WHERE IsAfterAsOf = 0" 0
Scalar "Funnel" "Customers (booked by the as-of date)"      '[Customers]'     "COUNT(*) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0" 0
Scalar "Funnel" "Lead to Customer %" '[Lead to Customer %]' "CAST($WON AS FLOAT) / (SELECT COUNT(*) FROM dbo.FactLead)" 0.000000001
Scalar "Funnel" "Opportunity to Customer %" '[Opportunity to Customer %]' "CAST($WON AS FLOAT) / $OPPS" 0.000000001
Scalar "Funnel" "Win Rate % (closed by the as-of date)" '[Win Rate %]' "CAST($WON AS FLOAT) / ($WON + (SELECT COUNT(*) FROM dbo.FactOpportunity WHERE Status = 'Closed Lost' AND IsAfterAsOf = 0))" 0.000000001
Scalar "Funnel" "Cohort Revenue USD" '[Cohort Revenue USD]' "SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0" 0.01

Scalar "Revenue" "Revenue USD (booked by the as-of date)" '[Revenue USD]' "SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0" 0.01
Scalar "Revenue" "Post-Period Revenue USD" '[Post-Period Revenue USD]' "SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 1" 0.01
Scalar "Revenue" "Deals Won"               '[Deals Won]'               "COUNT(*) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0" 0
Scalar "Revenue" "Average Deal Size USD"   '[Average Deal Size USD]'   "AVG(CAST(RevenueUSD AS FLOAT)) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0" 0.000001
Scalar "Revenue" "Opportunities Created"   '[Opportunities Created]'   "COUNT(*) FROM dbo.FactOpportunity WHERE IsAfterAsOf = 0" 0
Scalar "Revenue" "Open Pipeline USD (open on the as-of date)" '[Open Pipeline USD]' "SUM(o.OpportunityValue) FROM dbo.FactOpportunity o LEFT JOIN dbo.FactRevenue r ON r.OpportunityID = o.OpportunityID AND r.IsAfterAsOf = 0 WHERE o.IsAfterAsOf = 0 AND o.Status <> 'Closed Lost' AND r.RevenueID IS NULL" 0.01
Scalar "Revenue" "Avg Days Lead to Opportunity"   '[Avg Days Lead to Opportunity]'   "AVG(CAST(DATEDIFF(DAY, l.CreatedDate, o.CreatedDate) AS FLOAT)) FROM dbo.FactOpportunity o JOIN dbo.FactLead l ON l.LeadID = o.LeadID WHERE o.IsAfterAsOf = 0" 0.000001
Scalar "Revenue" "Avg Days Opportunity to Revenue" '[Avg Days Opportunity to Revenue]' "AVG(CAST(DATEDIFF(DAY, o.CreatedDate, r.RevenueDate) AS FLOAT)) FROM dbo.FactRevenue r JOIN dbo.FactOpportunity o ON o.OpportunityID = r.OpportunityID WHERE r.IsAfterAsOf = 0" 0.000001
$YTD  = "(SELECT SUM(CAST(r.RevenueUSD AS FLOAT)) FROM dbo.FactRevenue r $ASOFJOIN WHERE r.RevenueDate BETWEEN DATEFROMPARTS(YEAR(k.a), 1, 1) AND k.a)"
$PYTD = "(SELECT SUM(CAST(r.RevenueUSD AS FLOAT)) FROM dbo.FactRevenue r $ASOFJOIN WHERE r.RevenueDate BETWEEN DATEFROMPARTS(YEAR(k.a) - 1, 1, 1) AND DATEADD(YEAR, -1, k.a))"
Scalar "Revenue" "Revenue YTD USD"      '[Revenue YTD USD]'      $YTD 0.01
Scalar "Revenue" "Revenue PYTD USD"     '[Revenue PYTD USD]'     $PYTD 0.01
Scalar "Revenue" "Revenue YTD vs PY %"  '[Revenue YTD vs PY %]'  "($YTD - $PYTD) / $PYTD" 0.000000001

Scalar "Attrib" "Attributed Revenue USD (default model) = revenue booked" '[Attributed Revenue USD]' "SUM(AttributedRevenueUSD) FROM dbo.FactAttributionCredit c WHERE $PB" 0.01
Scalar "Attrib" "Attributed Leads = one per lead" '[Attributed Leads]' "SUM(CreditWeight) FROM dbo.FactAttributionCredit c WHERE c.ModelKey = 4" 0.000001
Scalar "Attrib" "Attributed Customers = one per customer" '[Attributed Customers]' "SUM(CreditWeight) FROM dbo.FactAttributionCredit c WHERE $PB" 0.000001
Scalar "Attrib" "Last Touch Revenue USD" '[Last Touch Revenue USD]' "SUM(AttributedRevenueUSD) FROM dbo.FactAttributionCredit WHERE ModelKey = 2 AND IsRevenueAfterAsOf = 0" 0.01
Scalar "Attrib" "Credit Shift vs Last Touch (total = 0)" '[Credit Shift vs Last Touch USD]' "(SELECT SUM(AttributedRevenueUSD) FROM dbo.FactAttributionCredit WHERE ModelKey = 4 AND IsRevenueAfterAsOf = 0) - (SELECT SUM(AttributedRevenueUSD) FROM dbo.FactAttributionCredit WHERE ModelKey = 2 AND IsRevenueAfterAsOf = 0)" 0.01
Scalar "Attrib" "ROAS" '[ROAS]' "(SELECT SUM(CAST(AttributedRevenueUSD AS FLOAT)) FROM dbo.FactAttributionCredit WHERE ModelKey = 4 AND IsRevenueAfterAsOf = 0) / $SPEND" 0.000000001
Scalar "Attrib" "Revenue-to-Spend Index (total = 1)" '[Revenue-to-Spend Index]' "1.0" 0.000000001
Scalar "Attrib" "Attribution Sensitivity % at total = 0 (every model conserves revenue)" '[Attribution Sensitivity %]' "0.0" 0.0000001

Scalar "Cost" "CPL USD"                  '[CPL USD]'                  "$SPEND / (SELECT COUNT(*) FROM dbo.FactLead)" 0.000001
Scalar "Cost" "Cost per MQL USD"         '[Cost per MQL USD]'         "$SPEND / (SELECT COUNT(*) FROM dbo.FactLead WHERE ReachedMQL = 1)" 0.000001
Scalar "Cost" "Cost per SQL USD"         '[Cost per SQL USD]'         "$SPEND / (SELECT COUNT(*) FROM dbo.FactLead WHERE ReachedSQL = 1)" 0.000001
Scalar "Cost" "Cost per Opportunity USD" '[Cost per Opportunity USD]' "$SPEND / $OPPS" 0.000001
Scalar "Cost" "CPA USD (attributed)"     '[CPA USD]'                  "$SPEND / (SELECT SUM(CAST(CreditWeight AS FLOAT)) FROM dbo.FactAttributionCredit c WHERE $PB)" 0.000001
Scalar "Cost" "CAC USD (blended)"        '[CAC USD]'                  "$SPEND / $WON" 0.000001

Scalar "Journey" "Touchpoints"             '[Touchpoints]'             "COUNT(*) FROM dbo.FactTouchpoint" 0
Scalar "Journey" "Avg Touches per Journey" '[Avg Touches per Journey]' "AVG(CAST(n AS FLOAT)) FROM (SELECT COUNT(*) n FROM dbo.FactTouchpoint GROUP BY LeadID) x" 0.000000001
Scalar "Journey" "Multi-Channel Journey %" '[Multi-Channel Journey %]' "AVG(CASE WHEN dc > 1 THEN CAST(1 AS FLOAT) ELSE CAST(0 AS FLOAT) END) FROM (SELECT COUNT(DISTINCT ChannelID) dc FROM dbo.FactTouchpoint GROUP BY LeadID) x" 0.000000001
Scalar "Journey" "Avg Days First Touch to Lead" '[Avg Days First Touch to Lead]' "AVG(CAST(d AS FLOAT)) FROM (SELECT MAX(DATEDIFF(DAY, t.TouchDate, l.CreatedDate)) d FROM dbo.FactTouchpoint t JOIN dbo.FactLead l ON l.LeadID = t.LeadID GROUP BY t.LeadID) x" 0.000001

Scalar "DQ" "Campaign Aliases"   '[Campaign Aliases]'   "COUNT(*) FROM dbo.CampaignAlias" 0
Scalar "DQ" "Aliases Resolved (Power Query rules vs supplied mapping)" '[Aliases Resolved]' "COUNT(*) FROM dbo.CampaignAlias" 0
Scalar "DQ" "Alias Mismatches"   '[Alias Mismatches]'   "0" 0
Scalar "DQ" "Alias Resolution Target %" '[Alias Resolution Target %]' "1.0" 0
Scalar "DQ" "Stale Stage Labels" '[Stale Stage Labels]' "COUNT(*) FROM dbo.FactLead WHERE IsStageLabelStale = 1" 0
Scalar "DQ" "Journeys With Contradicting Sequence" '[Journeys With Contradicting Sequence]' "COUNT(*) FROM dbo.FactLead WHERE SequenceContradictsDate = 1" 0
Scalar "DQ" "Spend Lines Before Campaign Start" '[Spend Lines Before Campaign Start]' "COUNT(*) FROM dbo.FactAdSpend WHERE IsBeforeCampaignStart = 1" 0
Scalar "DQ" "Post-Period Opportunities" '[Post-Period Opportunities]' "COUNT(*) FROM dbo.FactOpportunity WHERE IsAfterAsOf = 1" 0
Scalar "DQ" "Post-Period Bookings"      '[Post-Period Bookings]'      "COUNT(*) FROM dbo.FactRevenue WHERE IsAfterAsOf = 1" 0
Scalar "DQ" "Clicks per Lead"           '[Clicks per Lead]'           "(SELECT SUM(CAST(Clicks AS FLOAT)) FROM dbo.FactAdSpend) / (SELECT COUNT(*) FROM dbo.FactLead)" 0.000001
Scalar "DQ" "Spend to Revenue Ratio"    '[Spend to Revenue Ratio]'    "$SPEND / $REV" 0.000000001

$chJoin = "JOIN dbo.DimChannel ch ON ch.ChannelID = c.ChannelID"
Grouped "Slice" "Spend USD by channel" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], "v", [Spend USD] )' "SELECT ch.ChannelName, SUM(c.SpendUSD) FROM dbo.FactAdSpend c $chJoin GROUP BY ch.ChannelName" 0.01
Grouped "Slice" "Leads by lead-source channel" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], "v", [Leads] )' "SELECT ch.ChannelName, COUNT(*) FROM dbo.FactLead c $chJoin GROUP BY ch.ChannelName" 0
Grouped "Slice" "Spend USD by region" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[Region], "v", [Spend USD] )' "SELECT cp.Region, SUM(a.SpendUSD) FROM dbo.FactAdSpend a JOIN dbo.DimCampaign cp ON cp.CampaignID = a.CampaignID GROUP BY cp.Region" 0.01
foreach ($k in 1..5) {
    Grouped "Attrib" "model $k attributed revenue by channel" "EVALUATE CALCULATETABLE ( SUMMARIZECOLUMNS ( DimCampaign[ChannelName], ""v"", [Attributed Revenue USD] ), DimAttributionModel[ModelKey] = $k )" "SELECT ch.ChannelName, SUM(c.AttributedRevenueUSD) FROM dbo.FactAttributionCredit c $chJoin WHERE c.ModelKey = $k AND c.IsRevenueAfterAsOf = 0 GROUP BY ch.ChannelName" 0.01
}
Grouped "Attrib" "each model on an axis re-divides revenue booked" 'EVALUATE SUMMARIZECOLUMNS ( DimAttributionModel[ModelName], "v", [Attributed Revenue USD] )' "SELECT m.ModelName, SUM(c.AttributedRevenueUSD) FROM dbo.FactAttributionCredit c JOIN dbo.DimAttributionModel m ON m.ModelKey = c.ModelKey WHERE c.IsRevenueAfterAsOf = 0 GROUP BY m.ModelName" 0.01
Grouped "Attrib" "default model by channel = Position-Based" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], "v", [Attributed Revenue USD] )' "SELECT ch.ChannelName, SUM(c.AttributedRevenueUSD) FROM dbo.FactAttributionCredit c $chJoin WHERE $PB GROUP BY ch.ChannelName" 0.01
Grouped "Dates" "Revenue USD by booking year (inactive relationship)" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[Year], "v", [Revenue USD] )' "SELECT YEAR(RevenueDate), SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0 GROUP BY YEAR(RevenueDate)" 0.01
Grouped "Dates" "Leads by creation year (active relationship)" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[Year], "v", [Leads] )' "SELECT YEAR(CreatedDate), COUNT(*) FROM dbo.FactLead GROUP BY YEAR(CreatedDate)" 0
Grouped "Dates" "Opportunities Created by year (inactive relationship)" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[Year], "v", [Opportunities Created] )' "SELECT YEAR(CreatedDate), COUNT(*) FROM dbo.FactOpportunity WHERE IsAfterAsOf = 0 GROUP BY YEAR(CreatedDate)" 0
Grouped "DQ" "aliases by resolution status" 'EVALUATE SUMMARIZECOLUMNS ( CampaignAliasResolution[ResolutionStatus], "v", [Campaign Aliases] )' "SELECT 'Resolved', COUNT(*) FROM dbo.CampaignAlias" 0

Grouped "Funnel" "Funnel Stage Leads by stage (reached by the as-of date)" 'EVALUATE SUMMARIZECOLUMNS ( DimFunnelStage[StageName], "v", [Funnel Stage Leads] )' "SELECT s.StageName, (SELECT COUNT(*) FROM $STAGE WHERE x.rk >= s.StageRank) FROM dbo.DimFunnelStage s" 0
Grouped "Funnel" "Conversion From Previous Stage % by stage" 'EVALUATE SUMMARIZECOLUMNS ( DimFunnelStage[StageName], "v", [Conversion From Previous Stage %] )' "SELECT s.StageName, CAST((SELECT COUNT(*) FROM $STAGE WHERE x.rk >= s.StageRank) AS FLOAT) / (SELECT COUNT(*) FROM $STAGE WHERE x.rk >= s.StageRank - 1) FROM dbo.DimFunnelStage s WHERE s.StageRank > 1" 0.000000001
Grouped "Revenue" "Revenue PY USD by year (blank after the as-of date)" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[Year], "v", [Revenue PY USD] )' "SELECT YEAR(RevenueDate) + 1, SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0 AND YEAR(RevenueDate) + 1 <= YEAR($ASOF) GROUP BY YEAR(RevenueDate) + 1" 0.01
Grouped "Attrib" "Attribution Sensitivity % by campaign" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[CampaignID], "v", [Attribution Sensitivity %] )' "SELECT CampaignID, (MAX(Rev) - MIN(Rev)) / AVG(Rev) FROM (SELECT CampaignID, ModelKey, SUM(CAST(AttributedRevenueUSD AS FLOAT)) AS Rev FROM dbo.FactAttributionCredit WHERE RevenueDate IS NOT NULL AND IsRevenueAfterAsOf = 0 GROUP BY CampaignID, ModelKey) x GROUP BY CampaignID HAVING AVG(Rev) > 0" 0.000001

# ------------------------------------------------- 3. every report figure ---
Write-Host "`n== 3. REPORT: each visual's figures at the visual's own grain ==" -ForegroundColor Yellow
$YM = "YEAR({0}) * 100 + MONTH({0})"
$RVM = $YM -f "RevenueDate"

# Finance tie-out: every model re-divides each month's booked revenue, nothing more.
foreach ($k in 1..5) {
    Grouped "TieOut" "model $k attributed revenue by booking month = revenue booked" "EVALUATE CALCULATETABLE ( SUMMARIZECOLUMNS ( DimDate[YearMonth], ""v"", [Attributed Revenue USD] ), DimAttributionModel[ModelKey] = $k )" "SELECT $RVM, SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0 GROUP BY $RVM" 0.05
}

# Executive
Grouped "Exec" "KPI indicator: cumulative YTD revenue by month" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], "v", [Revenue Cumulative YTD USD] )' "SELECT d.YearMonth, (SELECT SUM(CAST(r.RevenueUSD AS FLOAT)) FROM dbo.FactRevenue r WHERE r.RevenueDate BETWEEN DATEFROMPARTS(YEAR(k.a), 1, 1) AND CASE WHEN EOMONTH(d.MonthStart) < k.a THEN EOMONTH(d.MonthStart) ELSE k.a END) FROM (SELECT DISTINCT YearMonth, MonthStart FROM dbo.DimDate) d $ASOFJOIN WHERE YEAR(d.MonthStart) = YEAR(k.a) AND d.MonthStart <= k.a" 0.01
Grouped "Exec" "KPI goal: cumulative PYTD revenue by month" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], "v", [Revenue Cumulative PYTD USD] )' "SELECT d.YearMonth, (SELECT SUM(CAST(r.RevenueUSD AS FLOAT)) FROM dbo.FactRevenue r WHERE r.RevenueDate BETWEEN DATEFROMPARTS(YEAR(k.a) - 1, 1, 1) AND DATEADD(YEAR, -1, CASE WHEN EOMONTH(d.MonthStart) < k.a THEN EOMONTH(d.MonthStart) ELSE k.a END)) FROM (SELECT DISTINCT YearMonth, MonthStart FROM dbo.DimDate) d $ASOFJOIN WHERE YEAR(d.MonthStart) = YEAR(k.a) AND d.MonthStart <= k.a" 0.01
Grouped "Exec" "leads by creation month" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], "v", [Leads] )' ("SELECT $YM, COUNT(*) FROM dbo.FactLead GROUP BY $YM" -f "CreatedDate") 0
Grouped "Exec" "lead-to-customer by cohort month, mature cohorts only" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], "v", [Lead to Customer % (Mature Cohorts)] )' ("SELECT $YM, CAST(SUM(CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) FROM dbo.FactLead l LEFT JOIN dbo.FactRevenue r ON r.LeadID = l.LeadID GROUP BY $YM HAVING EOMONTH(MIN(l.CreatedDate)) <= DATEADD(DAY, -(SELECT MAX(DATEDIFF(DAY, l2.CreatedDate, r2.RevenueDate)) FROM dbo.FactRevenue r2 JOIN dbo.FactLead l2 ON l2.LeadID = r2.LeadID), $ASOF)" -f "l.CreatedDate") 0.000000001
Grouped "Exec" "revenue booked by month" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], "v", [Revenue USD] )' "SELECT $RVM, SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0 GROUP BY $RVM" 0.01
Grouped "Exec" "revenue same month last year" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], "v", [Revenue PY USD] )' "SELECT $RVM + 100, SUM(RevenueUSD) FROM dbo.FactRevenue WHERE IsAfterAsOf = 0 AND DATEADD(YEAR, 1, DATEFROMPARTS(YEAR(RevenueDate), MONTH(RevenueDate), 1)) <= $ASOF GROUP BY $RVM + 100" 0.01
Grouped "Exec" "channel cost by channel group" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelGroup], "v", [Spend USD] )' "SELECT ch.ChannelGroup, SUM(c.SpendUSD) FROM dbo.FactAdSpend c $chJoin GROUP BY ch.ChannelGroup" 0.01

# Channels & budget
Grouped "Channels" "treemap: channel cost by region x channel" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[Region], DimCampaign[ChannelName], "v", [Spend USD] )' "SELECT cp.Region, ch.ChannelName, SUM(c.SpendUSD) FROM dbo.FactAdSpend c JOIN dbo.DimCampaign cp ON cp.CampaignID = c.CampaignID $chJoin GROUP BY cp.Region, ch.ChannelName" 0.01
Grouped "Channels" "share of channel cost by channel" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], "v", [Spend Share %] )' "SELECT ch.ChannelName, SUM(CAST(c.SpendUSD AS FLOAT)) / $SPEND FROM dbo.FactAdSpend c $chJoin GROUP BY ch.ChannelName" 0.000000001
Grouped "Channels" "share of attributed revenue by channel" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], "v", [Attributed Revenue Share %] )' "SELECT ch.ChannelName, SUM(CAST(c.AttributedRevenueUSD AS FLOAT)) / (SELECT SUM(CAST(AttributedRevenueUSD AS FLOAT)) FROM dbo.FactAttributionCredit c WHERE $PB) FROM dbo.FactAttributionCredit c $chJoin WHERE $PB GROUP BY ch.ChannelName" 0.000000001
Grouped "Channels" "ribbon: attributed revenue by complete quarter x channel" 'EVALUATE CALCULATETABLE ( SUMMARIZECOLUMNS ( DimDate[QuarterLabel], DimCampaign[ChannelName], "v", [Attributed Revenue USD] ), DimDate[IsQuarterComplete] = TRUE () )' "SELECT CONCAT(YEAR(c.RevenueDate), ' Q', DATEPART(QUARTER, c.RevenueDate)), ch.ChannelName, SUM(c.AttributedRevenueUSD) FROM dbo.FactAttributionCredit c $chJoin WHERE $PB AND EOMONTH(DATEFROMPARTS(YEAR(c.RevenueDate), DATEPART(QUARTER, c.RevenueDate) * 3, 1)) <= $ASOF GROUP BY CONCAT(YEAR(c.RevenueDate), ' Q', DATEPART(QUARTER, c.RevenueDate)), ch.ChannelName" 0.01
Grouped "Channels" "small multiples: CPL by month x region" 'EVALUATE SUMMARIZECOLUMNS ( DimDate[YearMonth], DimCampaign[Region], "v", [CPL USD] )' ("SELECT s.ym, s.Region, s.sp / l.n FROM (SELECT $YM AS ym, cp.Region, SUM(CAST(a.SpendUSD AS FLOAT)) sp FROM dbo.FactAdSpend a JOIN dbo.DimCampaign cp ON cp.CampaignID = a.CampaignID GROUP BY $YM, cp.Region) s JOIN (SELECT $($YM -f 'f.CreatedDate') AS ym, cp.Region, COUNT(*) n FROM dbo.FactLead f JOIN dbo.DimCampaign cp ON cp.CampaignID = f.CampaignID GROUP BY $($YM -f 'f.CreatedDate'), cp.Region) l ON l.ym = s.ym AND l.Region = s.Region" -f "a.[Date]") 0.000001

# Funnel & pipeline
Grouped "Funnel" "heatmap colour: lead-to-customer z by segment x channel group" 'EVALUATE SUMMARIZECOLUMNS ( FactLeadFunnel[Segment], DimCampaign[ChannelGroup], "v", [Lead to Customer z vs Portfolio] )' "WITH c AS (SELECT l.Segment, ch.ChannelGroup, COUNT(*) n, SUM(CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN 1.0 ELSE 0 END) w FROM dbo.FactLead l JOIN dbo.DimCampaign cp ON cp.CampaignID = l.CampaignID JOIN dbo.DimChannel ch ON ch.ChannelID = cp.ChannelID LEFT JOIN dbo.FactRevenue r ON r.LeadID = l.LeadID GROUP BY l.Segment, ch.ChannelGroup), t AS (SELECT CAST(SUM(w) AS FLOAT) / SUM(n) p0 FROM c) SELECT c.Segment, c.ChannelGroup, (CAST(c.w AS FLOAT) / c.n - t.p0) / SQRT(t.p0 * (1 - t.p0) / c.n) FROM c CROSS JOIN t" 0.000001
Grouped "Funnel" "heatmap value: lead-to-customer by segment x channel group" 'EVALUATE SUMMARIZECOLUMNS ( FactLeadFunnel[Segment], DimCampaign[ChannelGroup], "v", [Lead to Customer %] )' "SELECT l.Segment, ch.ChannelGroup, AVG(CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN CAST(1 AS FLOAT) ELSE CAST(0 AS FLOAT) END) FROM dbo.FactLead l JOIN dbo.DimCampaign cp ON cp.CampaignID = l.CampaignID JOIN dbo.DimChannel ch ON ch.ChannelID = cp.ChannelID LEFT JOIN dbo.FactRevenue r ON r.LeadID = l.LeadID GROUP BY l.Segment, ch.ChannelGroup" 0.000000001
$COLOUR = "CASE WHEN {0} >= 3 THEN '#4E9A1E' WHEN {0} >= 2 THEN '#2A5518' WHEN {0} <= -3 THEN '#8A2E24' WHEN {0} <= -2 THEN '#4A1F1A' ELSE '#0A120A' END"
Grouped "Funnel" "heatmap colour: unshaded unless beyond chance" 'EVALUATE SUMMARIZECOLUMNS ( FactLeadFunnel[Segment], DimCampaign[ChannelGroup], "v", [Heatmap Signal Colour] )' ("WITH c AS (SELECT l.Segment, ch.ChannelGroup, COUNT(*) n, SUM(CASE WHEN r.RevenueID IS NOT NULL AND r.IsAfterAsOf = 0 THEN 1.0 ELSE 0 END) w FROM dbo.FactLead l JOIN dbo.DimCampaign cp ON cp.CampaignID = l.CampaignID JOIN dbo.DimChannel ch ON ch.ChannelID = cp.ChannelID LEFT JOIN dbo.FactRevenue r ON r.LeadID = l.LeadID GROUP BY l.Segment, ch.ChannelGroup), t AS (SELECT CAST(SUM(w) AS FLOAT) / SUM(n) p0 FROM c), z AS (SELECT c.Segment, c.ChannelGroup, (CAST(c.w AS FLOAT) / c.n - t.p0) / SQRT(t.p0 * (1 - t.p0) / c.n) z FROM c CROSS JOIN t) SELECT Segment, ChannelGroup, " + ($COLOUR -f "z") + " FROM z") 0
Grouped "Funnel" "days from opportunity to close (deals booked by the as-of date)" 'EVALUATE SUMMARIZECOLUMNS ( FactLeadFunnel[DaysOpportunityToRevenue], "v", [Customers] )' "SELECT DATEDIFF(DAY, o.CreatedDate, r.RevenueDate), COUNT(*) FROM dbo.FactRevenue r JOIN dbo.FactOpportunity o ON o.OpportunityID = r.OpportunityID WHERE r.IsAfterAsOf = 0 GROUP BY DATEDIFF(DAY, o.CreatedDate, r.RevenueDate)" 0

# Attribution
Grouped "Attrib" "five models: revenue share by channel x model" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], DimAttributionModel[ModelName], "v", [Attributed Revenue Share %] )' "SELECT ch.ChannelName, m.ModelName, SUM(CAST(c.AttributedRevenueUSD AS FLOAT)) / MAX(t.tot) FROM dbo.FactAttributionCredit c $chJoin JOIN dbo.DimAttributionModel m ON m.ModelKey = c.ModelKey JOIN (SELECT ModelKey, SUM(CAST(AttributedRevenueUSD AS FLOAT)) tot FROM dbo.FactAttributionCredit WHERE IsRevenueAfterAsOf = 0 GROUP BY ModelKey) t ON t.ModelKey = c.ModelKey WHERE c.IsRevenueAfterAsOf = 0 GROUP BY ch.ChannelName, m.ModelName" 0.000000001
Grouped "Attrib" "matrix: attributed revenue by channel x model" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], DimAttributionModel[ModelName], "v", [Attributed Revenue USD] )' "SELECT ch.ChannelName, m.ModelName, SUM(c.AttributedRevenueUSD) FROM dbo.FactAttributionCredit c $chJoin JOIN dbo.DimAttributionModel m ON m.ModelKey = c.ModelKey WHERE c.IsRevenueAfterAsOf = 0 GROUP BY ch.ChannelName, m.ModelName" 0.01
Grouped "Attrib" "waterfall: credit shift vs Last Touch by channel (default model)" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], "v", [Credit Shift vs Last Touch USD] )' "SELECT ch.ChannelName, SUM(CASE WHEN c.ModelKey = 4 THEN c.AttributedRevenueUSD ELSE 0 END) - SUM(CASE WHEN c.ModelKey = 2 THEN c.AttributedRevenueUSD ELSE 0 END) FROM dbo.FactAttributionCredit c $chJoin WHERE c.IsRevenueAfterAsOf = 0 GROUP BY ch.ChannelName" 0.01

# Journeys - expected values from the touchpoints themselves, not FactLead's stored counts
$JRN = "(SELECT t.LeadID, COUNT(*) AS n, COUNT(DISTINCT t.ChannelID) AS dc FROM dbo.FactTouchpoint t GROUP BY t.LeadID) j"
Grouped "Journeys" "leads by journey length x channels in journey" 'EVALUATE SUMMARIZECOLUMNS ( FactLeadFunnel[TouchCount], FactLeadFunnel[DistinctChannels], "v", [Leads] )' "SELECT j.n, j.dc, COUNT(*) FROM $JRN GROUP BY j.n, j.dc" 0
Grouped "Journeys" "leads by channels in journey" 'EVALUATE SUMMARIZECOLUMNS ( FactLeadFunnel[DistinctChannels], "v", [Leads] )' "SELECT j.dc, COUNT(*) FROM $JRN GROUP BY j.dc" 0
Grouped "Journeys" "touches by days before lead creation" 'EVALUATE SUMMARIZECOLUMNS ( FactTouchpoint[DaysBeforeLead], "v", [Touchpoints] )' "SELECT DATEDIFF(DAY, t.TouchDate, l.CreatedDate), COUNT(*) FROM dbo.FactTouchpoint t JOIN dbo.FactLead l ON l.LeadID = t.LeadID GROUP BY DATEDIFF(DAY, t.TouchDate, l.CreatedDate)" 0
Grouped "Journeys" "touches by channel x journey position" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[ChannelName], FactTouchpoint[PositionBand], "v", [Touchpoints] )' "SELECT ch.ChannelName, CASE WHEN x.n = 1 THEN 'Only touch' WHEN x.k = 1 THEN 'First' WHEN x.k = x.n THEN 'Last' ELSE 'Middle' END, COUNT(*) FROM (SELECT t.ChannelID, ROW_NUMBER() OVER (PARTITION BY t.LeadID ORDER BY t.TouchDate, t.SourceTouchSequence) k, COUNT(*) OVER (PARTITION BY t.LeadID) n FROM dbo.FactTouchpoint t) x JOIN dbo.DimChannel ch ON ch.ChannelID = x.ChannelID GROUP BY ch.ChannelName, CASE WHEN x.n = 1 THEN 'Only touch' WHEN x.k = 1 THEN 'First' WHEN x.k = x.n THEN 'Last' ELSE 'Middle' END" 0

# Campaigns - the signal test recomputed from the credit rows, NOT from the stored dispersion
$ZSQL = "WITH sp AS (SELECT CampaignID, SUM(CAST(SpendUSD AS FLOAT)) s FROM dbo.FactAdSpend GROUP BY CampaignID), y AS (SELECT c.CampaignID, c.LeadID, SUM(CAST(c.AttributedRevenueUSD AS FLOAT)) v FROM dbo.FactAttributionCredit c WHERE $PB GROUP BY c.CampaignID, c.LeadID), d AS (SELECT SUM(v * v) / SUM(v) disp, SUM(v) tot FROM y WHERE v > 0), cr AS (SELECT CampaignID, SUM(v) r FROM y GROUP BY CampaignID), z AS (SELECT sp.CampaignID, (ISNULL(cr.r, 0) - sp.s / SUM(sp.s) OVER () * d.tot) / SQRT(sp.s / SUM(sp.s) OVER () * d.tot * d.disp) AS z FROM sp LEFT JOIN cr ON cr.CampaignID = sp.CampaignID CROSS JOIN d)"
Grouped "Campaigns" "Campaign Index z by campaign" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[CampaignID], "v", [Campaign Index z] )' "$ZSQL SELECT CampaignID, z FROM z" 0.000001
Grouped "Campaigns" "Campaign Index Signal: campaigns per class" 'EVALUATE GROUPBY ( ADDCOLUMNS ( VALUES ( DimCampaign[CampaignID] ), "@s", [Campaign Index Signal] ), [@s], "n", SUMX ( CURRENTGROUP (), 1 ) )' "$ZSQL SELECT CASE WHEN z >= 3 THEN 'Clearly above' WHEN z >= 2 THEN 'Possibly above' WHEN z <= -3 THEN 'Clearly below' WHEN z <= -2 THEN 'Possibly below' ELSE 'Within noise' END, COUNT(*) FROM z GROUP BY CASE WHEN z >= 3 THEN 'Clearly above' WHEN z >= 2 THEN 'Possibly above' WHEN z <= -3 THEN 'Clearly below' WHEN z <= -2 THEN 'Possibly below' ELSE 'Within noise' END" 0
Grouped "Campaigns" "scorecard colour by campaign: unshaded unless beyond chance" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[CampaignID], "v", [Campaign Signal Colour] )' ("$ZSQL SELECT CampaignID, " + ($COLOUR -f "z") + " FROM z") 0
Grouped "Campaigns" "attributed customers by campaign" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[CampaignID], "v", [Attributed Customers] )' "SELECT c.CampaignID, SUM(CAST(c.CreditWeight AS FLOAT)) FROM dbo.FactAttributionCredit c WHERE $PB GROUP BY c.CampaignID" 0.000001
Grouped "Campaigns" "Revenue-to-Spend Index by campaign" 'EVALUATE SUMMARIZECOLUMNS ( DimCampaign[CampaignID], "v", [Revenue-to-Spend Index] )' "WITH sp AS (SELECT CampaignID, SUM(CAST(SpendUSD AS FLOAT)) s FROM dbo.FactAdSpend GROUP BY CampaignID), cr AS (SELECT c.CampaignID, SUM(CAST(c.AttributedRevenueUSD AS FLOAT)) r FROM dbo.FactAttributionCredit c WHERE $PB GROUP BY c.CampaignID) SELECT sp.CampaignID, (cr.r / SUM(cr.r) OVER ()) / (sp.s / SUM(sp.s) OVER ()) FROM sp JOIN cr ON cr.CampaignID = sp.CampaignID" 0.000000001

# Data & method
Grouped "Method" "aliases by naming style" 'EVALUATE SUMMARIZECOLUMNS ( CampaignAliasResolution[AliasStyle], "v", [Campaign Aliases] )' "SELECT RIGHT(RawCampaignKey, CHARINDEX('_', REVERSE(RawCampaignKey)) - 1), COUNT(*) FROM dbo.CampaignAlias GROUP BY RIGHT(RawCampaignKey, CHARINDEX('_', REVERSE(RawCampaignKey)) - 1)" 0
Grouped "Method" "FX planning rate by currency" 'EVALUATE SUMMARIZECOLUMNS ( FxRate[CurrencyCode], "v", MAX ( FxRate[RateToUSD] ) )' "SELECT CurrencyCode, RateToUSD FROM dbo.FxRate" 0.000001

# ----------------------------------------------------------- 4. security ---
Write-Host "`n== 4. SECURITY: Regional Marketing role ==" -ForegroundColor Yellow
# Connecting AS the role, the engine applies the filter with the real Windows
# identity, which is not in SecurityUserAccess: the secure default must hide everything.
try {
    $rc = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$($script:port);Initial Catalog=$($script:cat);Roles=Regional Marketing")
    $rc.Open()
    $n = (Dax 'EVALUATE ROW ( "v", COUNTROWS ( DimCampaign ) + 0 )' $rc).Rows[0][0]
    $s = (Dax 'EVALUATE ROW ( "v", [Spend USD] + 0 )' $rc).Rows[0][0]
    $rc.Close()
    Check "Security" "unmapped user under role sees 0 campaigns (engine-enforced)" $n 0 0
    Check "Security" "unmapped user under role sees 0 spend (filter reaches facts)" $s 0 0
} catch { Check "Security" "connect as role: $($_.Exception.Message)" 0 1 0 }
# The filter predicate itself, evaluated for each mapped user with the email substituted.
$users = Sql "SELECT UserEmail, Region FROM dbo.SecurityUserAccess"
foreach ($u in $users.Rows) {
    $email = $u[0]; $region = $u[1]
    $daxN = (Dax ("EVALUATE ROW ( ""v"", VAR UserRegions = CALCULATETABLE ( VALUES ( SecurityUserAccess[Region] ), SecurityUserAccess[UserEmail] = ""$email"" ) RETURN COUNTROWS ( FILTER ( DimCampaign, ""ALL"" IN UserRegions || DimCampaign[Region] IN UserRegions ) ) )")).Rows[0][0]
    $sqlN = (Sql ("SELECT COUNT(*) FROM dbo.DimCampaign WHERE '$region' = 'ALL' OR Region = '$region'")).Rows[0][0]
    Check "Security" "role predicate for $email ($region)" $daxN $sqlN 0
}

$conn.Close(); $sql.Close()
Write-Host ("`nRESULT: {0} passed, {1} failed, {2} total" -f $script:pass, $script:fail, ($script:pass + $script:fail)) -ForegroundColor Cyan
$script:rows | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $PSScriptRoot "reconcile_results.csv")
$script:rows | Group-Object Area | ForEach-Object {
    $p = @($_.Group | Where-Object Result -eq "PASS").Count     # @() - PS 5.1 has no .Count on one object
    Write-Host ("  {0,-9} {1,4} / {2}" -f $_.Name, $p, $_.Count)
}
if ($script:fail -gt 0) { exit 1 }
exit 0
