"""
Phase 3 - the semantic model, written as code.

Generates the whole PBIP semantic model (TMDL) from the specification below: tables,
columns, relationships, measures, two calculation groups, a field parameter, the row-
level security role and the model manifest. Nothing is authored by clicking in Power
BI Desktop, so the model is reviewable in Git and a genuine Ctrl+S leaves it untouched.

Everything reads from the analytics schema of HealthcareRCMBI. See Documentation/
semantic_model.md for the shape and Documentation/dax_measure_dictionary.md for the
measures.

Usage:  python Python/02_generate_semantic_model.py
"""
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NAME = "HealthcareRCM"
PBI = ROOT / "PowerBI"
SCAFFOLD = PBI / "scaffold"
SM = PBI / f"{NAME}.SemanticModel"
RP = PBI / f"{NAME}.Report"
DEF = SM / "definition"
NS = uuid.UUID("b17d3a90-6c24-4f58-8e31-2a95c7d0e6f4")   # fixed: deterministic tags

BOOL_FMT = '"""TRUE"";""TRUE"";""FALSE"""'
MONEY = "\\$#,0.00"
MONEY0 = "\\$#,0"
PCT1 = "0.0%"
PCT2 = "0.00%"
NUM0 = "#,0"
NUM1 = "#,0.0"


def tag(*parts):
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name):
    """TMDL quotes a name only when it has to."""
    return name if name.replace("_", "").isalnum() else f"'{name}'"


# --------------------------------------------------------------------- spec ---
@dataclass
class Col:
    name: str
    dtype: str                      # string | int64 | double | dateTime | boolean
    fmt: str = None
    hidden: bool = False
    summarize: str = "none"
    sort_by: str = None
    desc: str = None
    category: str = None
    key: bool = False


@dataclass
class Table:
    name: str
    source: str                     # analytics view name
    desc: str
    cols: list
    hidden: bool = False
    category: str = None
    hierarchies: list = field(default_factory=list)   # (name, [level columns])


def S(n, **k): return Col(n, "string", **k)
def I(n, **k): return Col(n, "int64", **k)
def D(n, **k): return Col(n, "double", **k)
def T(n, **k): return Col(n, "dateTime", **k)
def B(n, **k): return Col(n, "boolean", **k)


MEASURES_TABLE_M = """let
    Source = #table(type table [Placeholder = text], {})
in
    Source"""

# Every fact carries its own foreign keys, so the key columns repeat table after
# table. They are all hidden: a reader never picks a surrogate key off a field list.
TABLES = [
    # =================================================================== date ===
    Table("DimDate", "vw_DimDate",
          "The calendar, GENERATED in SQL rather than loaded. The supplied dim_date.csv was built to the service "
          "date range and stops on 2026-08-31, but a claim is submitted after it is performed, adjudicated after "
          "that and paid after that - 4,807 dates fall past the end of it and would have joined to a blank date. "
          "This one runs 2022-01-01 to 2026-12-31 with no gaps. Marked as the date table. The financial year is "
          "Australian: July to June, labelled by the year it ends in.",
          [I("DateKey", hidden=True, desc="yyyymmdd. The join key every fact uses."),
           # A table marked dataCategory: Time must carry isKey on the DATE column, not
           # on the integer it happens to join by - that is what makes DATEADD and
           # DATESINPERIOD work at all.
           T("Date", key=True, desc="The model date. Unique and contiguous."),
           I("Year", fmt="0"),
           I("MonthNo", fmt="0", hidden=True),
           S("MonthName", sort_by="MonthNo"),
           S("MonthShort", sort_by="MonthNo", desc="Three-letter month, for a narrow axis."),
           I("MonthKey", fmt="0", hidden=True, desc="yyyymm. Sort key for MonthLabel."),
           T("MonthStart", desc="First day of the month."),
           T("MonthEnd", hidden=True, desc="The AR snapshot lands on this date."),
           S("MonthLabel", sort_by="MonthKey", desc="'Jan 2023'."),
           I("Quarter", fmt="0", hidden=True),
           S("QuarterLabel"),
           I("ISOWeek", fmt="0", hidden=True),
           S("DayName", sort_by="DayNumberOfWeek"),
           I("DayNumberOfWeek", fmt="0", hidden=True),
           B("IsWeekend", hidden=True),
           I("FinancialYearStart", fmt="0", hidden=True),
           S("FinancialYear", desc="FY23 runs 1 July 2022 to 30 June 2023."),
           S("FinancialQuarter"),
           I("FinancialMonthNo", fmt="0", hidden=True, desc="1 = July."),
           B("IsMonthEnd", hidden=True),
           I("MonthOffset", fmt="0",
             desc="Months from the as-of month: 0 = November 2026, so -11 to 0 is the trailing twelve months. A "
                  "measure filters this integer instead of rebuilding a date range."),
           B("InSuppliedCalendar",
             desc="FALSE for the days this build had to add because the supplied calendar stopped at the last "
                  "service date. Kept so the gap is visible in the data rather than silently patched.")],
          category="Time"),

    # ============================================================= dimensions ===
    Table("DimPatient", "vw_DimBeneficiary",
          "One row per beneficiary. 1,034 of the 30,000 never appear on a claim, so every patient count in the "
          "model is taken from the claims and never from this table. Age is stated AT THE AS-OF DATE and labelled "
          "that way; age at the time of treatment is carried on the claim instead.",
          [I("BeneficiaryKey", hidden=True, key=True),
           S("BeneficiaryID", desc="The patient identifier as it arrives. Synthetic."),
           T("DateOfBirth", hidden=True),
           I("AgeAtAsOf", fmt="0", summarize="none", desc="Age in whole years at the as-of date, 2026-11-03."),
           I("AgeBandKey", fmt="0", hidden=True),
           S("AgeBand", sort_by="AgeBandKey"),
           S("Gender"),
           S("State", category="StateOrProvince", desc="The patient's state of residence."),
           S("ChronicRiskBand", sort_by="RiskBandOrder",
             desc="The source's own risk stratification. It does not separate denial rates (7.73% to 7.90%)."),
           I("RiskBandOrder", fmt="0", hidden=True)]),

    Table("DimProvider", "vw_DimProvider",
          "One row per billing provider. Every provider belongs to exactly one facility and 100% of claims are "
          "billed at the provider's own facility, so the facility attributes are carried here too: provider and "
          "facility are ONE hierarchy, which is what lets row-level security filter this table directly.",
          [I("ProviderKey", hidden=True, key=True),
           S("ProviderID", hidden=True),
           S("ProviderName"),
           S("Specialty"),
           S("FacilityID", hidden=True, desc="Read by the security role."),
           S("FacilityName", desc="The provider's own facility."),
           S("FacilityType"),
           S("State", category="StateOrProvince")],
          hierarchies=[("Facility to provider", ["State", "FacilityName", "Specialty", "ProviderName"])]),

    Table("DimFacility", "vw_DimFacility",
          "One row per facility. Thirty of them, four types.",
          [I("FacilityKey", hidden=True, key=True),
           S("FacilityID", hidden=True, desc="Read by the security role."),
           S("FacilityName"),
           S("FacilityType"),
           S("State", category="StateOrProvince")],
          hierarchies=[("State to facility", ["State", "FacilityType", "FacilityName"])]),

    Table("DimPayer", "vw_DimPayer",
          "Six payers: Medicare, four private insurers and Self Pay. PayerType and IsSelfPay exist because the "
          "Self Pay split is the ONLY real denial signal in this data - Self Pay denies at 2.95% against 8.79% "
          "for the insurers, while the five insurers sit within 0.66 points of one another.",
          [I("PayerKey", hidden=True, key=True),
           S("PayerID", hidden=True),
           S("PayerName"),
           S("PayerType", desc="Government, private health insurer, or self-funded patient."),
           B("IsSelfPay", desc="TRUE for the one payer whose denial rate is genuinely different.")]),

    Table("DimClaimStatus", "vw_DimClaimStatus",
          "Paid, Pending or Denied. Mutually exclusive and complete: a paid claim has exactly one payment and no "
          "denial, a denied claim exactly one denial and no payment, a pending claim neither.",
          [I("ClaimStatusKey", hidden=True, key=True),
           S("ClaimStatus", sort_by="StatusOrder"),
           I("StatusOrder", fmt="0", hidden=True),
           B("IsResolved", desc="Paid or denied. A pending claim in this file is never resolved."),
           B("IsOpenAR", desc="TRUE for Pending: the claims carried as a receivable."),
           S("Definition", desc="What the status means here, shown on the method page.")]),

    Table("DimDenialReason", "vw_DimDenialReason",
          "The seven denial reasons, grouped the way a denials team is organised: front-end failures preventable "
          "at registration, coding failures at charge capture, clinical failures needing the record, and process "
          "failures in the billing office. The reason mix is uniform across payers, so it is reported as a "
          "WORKLOAD PROFILE - what the team has to work - and never as a root cause.",
          [I("DenialReasonKey", hidden=True, key=True),
           S("DenialReason"),
           S("ReasonCategory", sort_by="CategoryOrder"),
           I("CategoryOrder", fmt="0", hidden=True),
           S("PreventableAt", desc="The step in the cycle where this denial could have been avoided.")]),

    Table("DimDenialStatus", "vw_DimDenialStatus",
          "Open, Appealed, Corrected or Written Off. These are WORKFLOW STATES, not outcomes: no denied claim in "
          "this file was ever paid, including every one marked Corrected or Appealed. Nothing in the model reads "
          "any of them as a recovery.",
          [I("DenialStatusKey", hidden=True, key=True),
           S("DenialStatus", sort_by="StatusOrder"),
           I("StatusOrder", fmt="0", hidden=True),
           B("IsTerminal", desc="TRUE for Written Off - the only status that admits the money is gone."),
           S("Definition")]),

    Table("DimProcedure", "vw_DimProcedure",
          "Ten CPT codes with their published meanings and the usual departmental grouping. The charge in this "
          "source is drawn INDEPENDENTLY of the code - every code averages between $391.76 and $397.46 - so this "
          "dimension carries volume and mix faithfully and revenue not at all. No measure ranks a procedure by money.",
          [I("ProcedureKey", hidden=True, key=True),
           S("ProcedureCode"),
           S("ProcedureName"),
           S("ProcedureLabel", desc="Code and name together, for a chart axis."),
           S("ServiceLine", desc="Imaging, Pathology, Office visits, Cardiac or Procedural."),
           S("SettingHint", desc="Where this procedure is normally performed.")]),

    Table("DimDiagnosis", "vw_DimDiagnosis",
          "Ten ICD-10 three-character categories with their chapter. IsChronicCondition marks the five on a "
          "standard chronic disease register, so the diagnosis mix can be checked against the patient's own "
          "risk band - a claim the source makes that the model can test.",
          [I("DiagnosisKey", hidden=True, key=True),
           S("DiagnosisCode"),
           S("DiagnosisName"),
           S("DiagnosisLabel", desc="Code and name together, for a chart axis."),
           S("ICD10Chapter"),
           B("IsChronicCondition")]),

    Table("DimPaymentMethod", "vw_DimPaymentMethod",
          "EFT, card or cheque. Evenly split and unrelated to anything else measured here.",
          [I("PaymentMethodKey", hidden=True, key=True),
           S("PaymentMethod", sort_by="MethodOrder"),
           I("MethodOrder", fmt="0", hidden=True),
           B("IsElectronic")]),

    Table("DimARBucket", "vw_DimARBucket",
          "The standard ageing ladder. 365+ is its own bucket because that is the outer edge of a payer "
          "timely-filing window: past it a claim is not a receivable, it is a write-off waiting to be recognised.",
          [I("ARBucketKey", hidden=True, key=True),
           S("ARBucket", sort_by="ARBucketKey", desc="Days outstanding since submission."),
           I("MinDays", fmt="0", hidden=True),
           I("MaxDays", fmt="0", hidden=True),
           B("IsPastFiling", desc="TRUE for 365+: beyond any payer's filing window.")]),

    Table("DimARMovementType", "vw_DimARMovementType",
          "The four ways a receivable moves: in on submission, out as cash, out as patient responsibility, out "
          "as a denial. Direction is +1 or -1 so a waterfall reads correctly without a sign convention in DAX.",
          [I("ARMovementTypeKey", hidden=True, key=True),
           S("MovementType", sort_by="MovementOrder"),
           I("MovementOrder", fmt="0", hidden=True),
           I("Direction", fmt="0", hidden=True),
           S("Definition")]),

    # ================================================================== facts ===
    Table("FactClaim", "vw_FactClaim",
          "One row per claim, 100,000 of them. The four money columns are the point of the model: every dollar "
          "the payer allowed sits in exactly one of PaidAmount, PatientResponsibility, OpenARAmount or "
          "DeniedAmount, so allowed = the sum of the four on EVERY row and therefore at every level of every "
          "aggregation. FOUR relationships reach the calendar - service, submission, adjudication and resolution "
          "- of which service is active and the rest are switched on by the Date Basis calculation group.",
          [I("ClaimKey", hidden=True, key=True),
           S("ClaimID", desc="Degenerate key. Carried on every fact for drill-through, because the facts are "
                             "deliberately not related to one another."),
           I("BeneficiaryKey", hidden=True), I("ProviderKey", hidden=True),
           I("FacilityKey", hidden=True), I("PayerKey", hidden=True),
           I("ClaimStatusKey", hidden=True),
           # Deliberately NOT related to DimARBucket: it is null on every resolved claim,
           # and a nullable key gives the dimension a blank member that then draws as a
           # phantom row on the ageing ladder. The ageing is read from the snapshot.
           I("ARBucketKey", hidden=True),
           I("ServiceDateKey", hidden=True, desc="Active date relationship: when care was delivered."),
           I("SubmittedDateKey", hidden=True, desc="Inactive. The payer's clock starts here."),
           I("ProcessedDateKey", hidden=True, desc="Inactive. When the payer adjudicated."),
           I("ResolvedDateKey", hidden=True, desc="Inactive. Cash or denial date; blank while pending."),
           D("BilledAmount", fmt=MONEY, hidden=True, summarize="sum"),
           D("AllowedAmount", fmt=MONEY, hidden=True, summarize="sum"),
           D("PaidAmount", fmt=MONEY, hidden=True, summarize="sum"),
           D("ContractualAdjustment", fmt=MONEY, hidden=True, summarize="sum"),
           D("PatientResponsibility", fmt=MONEY, hidden=True, summarize="sum"),
           D("OpenARAmount", fmt=MONEY, hidden=True, summarize="sum"),
           D("DeniedAmount", fmt=MONEY, hidden=True, summarize="sum"),
           I("DaysToSubmit", fmt="0", hidden=True, summarize="sum"),
           I("DaysToProcess", fmt="0", hidden=True, summarize="sum"),
           I("DaysToResolve", fmt="0", hidden=True, summarize="sum"),
           I("DaysOutstanding", fmt="0", hidden=True, summarize="sum",
             desc="Pending claims only, measured at the as-of date."),
           I("PatientAgeAtService", fmt="0", hidden=True, summarize="sum"),
           I("LineCount", fmt="0", hidden=True, summarize="sum"),
           B("IsPaid", hidden=True), B("IsPending", hidden=True), B("IsDenied", hidden=True),
           B("IsFirstPassAccepted", hidden=True,
             desc="Not denied. With no resubmission chain in the source this is the denial rate written the "
                  "other way up, and the report says so rather than implying a second measurement.")]),

    Table("FactClaimLine", "vw_FactClaimLine",
          "One row per procedure line, 249,905 of them. ChargeAmount is the ONLY money here and it sums to the "
          "claim header's billed amount, so the line table carries mix and volume without becoming a second "
          "source of truth. No measure adds line charges to header amounts.",
          [I("ClaimLineKey", hidden=True, key=True),
           S("ClaimLineID", hidden=True),
           S("ClaimID", hidden=True),
           I("ProcedureKey", hidden=True), I("DiagnosisKey", hidden=True),
           I("BeneficiaryKey", hidden=True), I("ProviderKey", hidden=True),
           I("FacilityKey", hidden=True), I("PayerKey", hidden=True),
           I("ClaimStatusKey", hidden=True), I("ServiceDateKey", hidden=True),
           D("ChargeAmount", fmt=MONEY, hidden=True, summarize="sum")]),

    Table("FactPayment", "vw_FactPayment",
          "One row per remittance, 69,111 of them - exactly one per paid claim. There are no partial payments, "
          "no takebacks and no secondary payer, so days-to-pay is a single clean event. PaymentAmount is the "
          "SAME money as FactClaim[PaidAmount] seen on the cash date instead of the service date; the two are "
          "never added together.",
          [I("PaymentKey", hidden=True, key=True),
           S("PaymentID", hidden=True), S("ClaimID", hidden=True),
           I("PaymentDateKey", hidden=True, desc="Active: when the cash arrived."),
           I("SubmittedDateKey", hidden=True, desc="Inactive."),
           I("PaymentMethodKey", hidden=True), I("BeneficiaryKey", hidden=True),
           I("ProviderKey", hidden=True), I("FacilityKey", hidden=True), I("PayerKey", hidden=True),
           D("PaymentAmount", fmt=MONEY, hidden=True, summarize="sum"),
           D("AllowedAmount", fmt=MONEY, hidden=True, summarize="sum"),
           I("DaysToPay", fmt="0", hidden=True, summarize="sum")]),

    Table("FactDenial", "vw_FactDenial",
          "One row per denial, 7,824 of them - exactly one per denied claim. Carries the allowed amount so the "
          "denied value can be sliced by reason without reaching back to the claim header.",
          [I("DenialKey", hidden=True, key=True),
           S("DenialID", hidden=True), S("ClaimID", hidden=True),
           I("DenialDateKey", hidden=True, desc="Active. Always equal to the adjudication date in this file."),
           I("SubmittedDateKey", hidden=True, desc="Inactive."),
           I("DenialReasonKey", hidden=True), I("DenialStatusKey", hidden=True),
           I("BeneficiaryKey", hidden=True), I("ProviderKey", hidden=True),
           I("FacilityKey", hidden=True), I("PayerKey", hidden=True),
           D("DeniedAllowed", fmt=MONEY, hidden=True, summarize="sum"),
           D("DeniedBilled", fmt=MONEY, hidden=True, summarize="sum"),
           I("DaysToDeny", fmt="0", hidden=True, summarize="sum")]),

    Table("FactARSnapshot", "vw_FactARSnapshot",
          "A STOCK: one row per claim per month end that the claim was still outstanding - 670,151 rows across "
          "47 month ends. This is what makes an ageing possible at all, because a receivable's age is a property "
          "of a date, not of the claim. Carried at the allowed amount and aged from the submission date, which "
          "is the clock a payer is held to.",
          [I("ARSnapshotKey", hidden=True, key=True),
           I("SnapshotDateKey", hidden=True, desc="Always a month end."),
           S("ClaimID", hidden=True),
           I("BeneficiaryKey", hidden=True), I("ProviderKey", hidden=True),
           I("FacilityKey", hidden=True), I("PayerKey", hidden=True), I("ARBucketKey", hidden=True),
           I("AgeDays", fmt="0", hidden=True, summarize="sum"),
           D("ARAmount", fmt=MONEY, hidden=True, summarize="sum")]),

    Table("FactARMovement", "vw_FactARMovement",
          "A FLOW: one row per event that moved the receivable, 246,040 of them, signed so a waterfall reads "
          "without a sign convention in DAX. With the snapshot it closes an identity in every month - "
          "AR(m) = AR(m-1) + submitted - collected - patient responsibility - denied. A snapshot alone can drift "
          "unnoticed; a ledger alone cannot be aged.",
          [I("ARMovementKey", hidden=True, key=True),
           S("ClaimID", hidden=True),
           I("ARMovementTypeKey", hidden=True), I("MovementDateKey", hidden=True),
           I("BeneficiaryKey", hidden=True), I("ProviderKey", hidden=True),
           I("FacilityKey", hidden=True), I("PayerKey", hidden=True),
           D("Amount", fmt=MONEY, hidden=True, summarize="sum", desc="Signed: positive into AR, negative out."),
           D("AbsAmount", fmt=MONEY, hidden=True, summarize="sum")]),

    # ======================================================= analysis tables ===
    Table("DenialSignal", "vw_DenialSignalStrength",
          "DISCONNECTED on purpose. For each of the ten candidate dimensions, a chi-square test of independence "
          "against the denied flag, computed in SQL on every refresh. Cramer's V is used rather than the raw "
          "chi-square because it is comparable across dimensions with different value counts. Payer scores "
          "0.0813; the next highest is facility at 0.0145. It is disconnected because it is a statement ABOUT "
          "the claims, not a slice of them - filtering it by payer would be meaningless.",
          [S("Dimension", key=True),
           I("DistinctValues", fmt="0", hidden=True),
           D("LowestRatePct", fmt=NUM1, summarize="sum", desc="Denial rate in the dimension's lowest value, in percent."),
           D("HighestRatePct", fmt=NUM1, summarize="sum"),
           D("SpreadPP", fmt=NUM1, summarize="sum", desc="Percentage points between highest and lowest."),
           D("ChiSquare", fmt=NUM1, summarize="sum"),
           I("DegreesOfFreedom", fmt="0", hidden=True),
           D("CramersV", fmt="0.0000", summarize="sum",
             desc="0 to 1. The stated rule is that below 0.02 there is no usable signal, applied to every "
                  "dimension including the one that passes."),
           S("SignalVerdict")]),

    Table("ProviderChance", "vw_ProviderDenialChance",
          "DISCONNECTED on purpose. Every provider's denial rate next to the binomial standard error for that "
          "provider's own claim count. A 500-row league table running 3% to 14% is the first thing anyone asks "
          "for and is entirely noise: 23 providers sit beyond two standard errors, which is 4.6% against the "
          "4.55% a normal distribution predicts, and the most extreme is z = 3.3, about the maximum 500 draws "
          "produce. Disconnected because the group rate it compares against is computed over all claims; "
          "filtering it would silently change the baseline.",
          [I("ProviderKey", hidden=True, key=True),
           S("ProviderID", hidden=True),
           S("ProviderName"),
           S("Specialty"),
           S("FacilityName"),
           I("Claims", fmt=NUM0, summarize="sum"),
           I("Denials", fmt=NUM0, summarize="sum"),
           D("DenialRate", fmt=PCT2, summarize="average"),
           D("GroupRate", fmt=PCT2, summarize="average", desc="The denial rate across all claims."),
           D("StandardError", fmt="0.0000", summarize="average",
             desc="Binomial standard error at this provider's claim count."),
           D("ZScore", fmt=NUM1, summarize="average",
             desc="Standard errors from the group rate. Beyond 2 is what 4.55% of providers do by chance."),
           S("ChanceBand"),
           S("RateBand", sort_by="RateBandSort", desc="Two-point bands, so 500 providers draw as a distribution."),
           I("RateBandSort", fmt="0", hidden=True)]),

    Table("DataQualityMetric", "vw_DataQualityMetric",
          "DISCONNECTED. The Phase 1 findings as data, recomputed on every refresh. A finding written into a "
          "text box goes stale the moment the source changes; one computed from the source cannot.",
          [I("MetricOrder", fmt="0", hidden=True, key=True),
           S("Category"),
           S("Metric", sort_by="MetricOrder"),
           D("MetricValue", fmt=NUM0, summarize="sum"),
           S("ValueFormat", hidden=True, desc="The format string this metric should be shown in."),
           S("Interpretation", desc="What the number means, and what follows from it.")]),

    # ================================================== security and config ===
    Table("SecurityUserAccess", "vw_SecurityUserAccess",
          "The RLS mapping table, hidden. 82 grants across four roles. 'ALL' is kept as a literal so the role "
          "expression tests for it with one comparison rather than scanning 30 facility rows per user.",
          [S("UserEmail", key=True), S("Role"), S("FacilityID"), S("ProviderID"), S("ScopeLabel")],
          hidden=True),

    Table("ModelConfig", "vw_ModelConfig",
          "Every stated assumption, hidden, read by measures rather than typed into them. The as-of date, the "
          "currency, the timely-filing window and the basis AR is carried at all live here, so an assumption "
          "can be found and changed in one place - and printed on the page it is standing on.",
          [S("ConfigKey", key=True), S("ConfigValue"), S("Notes")],
          hidden=True),

    Table("_Measures", MEASURES_TABLE_M,
          "Measures only - no data. A single home for every measure keeps them out of the tables they happen to "
          "read, so a reader browsing FactClaim sees columns and a reader browsing measures sees measures.",
          [S("Placeholder", hidden=True)]),
]

# fromColumn is the MANY side, toColumn the ONE side.
#
# Note what is NOT here: there is no relationship between FactClaim and FactClaimLine,
# or between any two facts. With the dimensions conformed, a header-to-line
# relationship would give the engine two paths from DimPayer to the line table.
# ClaimID is a degenerate key on every fact for drill-through instead.
RELATIONSHIPS = [
    # --- claims. Four dates: service is active, the other three are switched on by
    #     the Date Basis calculation group, so one fact answers "when was the care
    #     delivered", "when did the payer's clock start", "when was it adjudicated"
    #     and "when did it resolve" without four copies of the table.
    ("FactClaim.ServiceDateKey", "DimDate.DateKey", True),
    ("FactClaim.SubmittedDateKey", "DimDate.DateKey", False),
    ("FactClaim.ProcessedDateKey", "DimDate.DateKey", False),
    ("FactClaim.ResolvedDateKey", "DimDate.DateKey", False),
    ("FactClaim.BeneficiaryKey", "DimPatient.BeneficiaryKey", True),
    ("FactClaim.ProviderKey", "DimProvider.ProviderKey", True),
    ("FactClaim.FacilityKey", "DimFacility.FacilityKey", True),
    ("FactClaim.PayerKey", "DimPayer.PayerKey", True),
    ("FactClaim.ClaimStatusKey", "DimClaimStatus.ClaimStatusKey", True),

    # --- lines. Their own keys, not a hop through the header.
    ("FactClaimLine.ServiceDateKey", "DimDate.DateKey", True),
    ("FactClaimLine.ProcedureKey", "DimProcedure.ProcedureKey", True),
    ("FactClaimLine.DiagnosisKey", "DimDiagnosis.DiagnosisKey", True),
    ("FactClaimLine.BeneficiaryKey", "DimPatient.BeneficiaryKey", True),
    ("FactClaimLine.ProviderKey", "DimProvider.ProviderKey", True),
    ("FactClaimLine.FacilityKey", "DimFacility.FacilityKey", True),
    ("FactClaimLine.PayerKey", "DimPayer.PayerKey", True),
    ("FactClaimLine.ClaimStatusKey", "DimClaimStatus.ClaimStatusKey", True),

    # --- payments. Active on the CASH date: a payment page is about when money arrived.
    ("FactPayment.PaymentDateKey", "DimDate.DateKey", True),
    ("FactPayment.SubmittedDateKey", "DimDate.DateKey", False),
    ("FactPayment.PaymentMethodKey", "DimPaymentMethod.PaymentMethodKey", True),
    ("FactPayment.BeneficiaryKey", "DimPatient.BeneficiaryKey", True),
    ("FactPayment.ProviderKey", "DimProvider.ProviderKey", True),
    ("FactPayment.FacilityKey", "DimFacility.FacilityKey", True),
    ("FactPayment.PayerKey", "DimPayer.PayerKey", True),

    # --- denials. Active on the denial date.
    ("FactDenial.DenialDateKey", "DimDate.DateKey", True),
    ("FactDenial.SubmittedDateKey", "DimDate.DateKey", False),
    ("FactDenial.DenialReasonKey", "DimDenialReason.DenialReasonKey", True),
    ("FactDenial.DenialStatusKey", "DimDenialStatus.DenialStatusKey", True),
    ("FactDenial.BeneficiaryKey", "DimPatient.BeneficiaryKey", True),
    ("FactDenial.ProviderKey", "DimProvider.ProviderKey", True),
    ("FactDenial.FacilityKey", "DimFacility.FacilityKey", True),
    ("FactDenial.PayerKey", "DimPayer.PayerKey", True),

    # --- the AR stock. The date is the SNAPSHOT date, always a month end.
    ("FactARSnapshot.SnapshotDateKey", "DimDate.DateKey", True),
    ("FactARSnapshot.ARBucketKey", "DimARBucket.ARBucketKey", True),
    ("FactARSnapshot.BeneficiaryKey", "DimPatient.BeneficiaryKey", True),
    ("FactARSnapshot.ProviderKey", "DimProvider.ProviderKey", True),
    ("FactARSnapshot.FacilityKey", "DimFacility.FacilityKey", True),
    ("FactARSnapshot.PayerKey", "DimPayer.PayerKey", True),

    # --- the AR flow.
    ("FactARMovement.MovementDateKey", "DimDate.DateKey", True),
    ("FactARMovement.ARMovementTypeKey", "DimARMovementType.ARMovementTypeKey", True),
    ("FactARMovement.BeneficiaryKey", "DimPatient.BeneficiaryKey", True),
    ("FactARMovement.ProviderKey", "DimProvider.ProviderKey", True),
    ("FactARMovement.FacilityKey", "DimFacility.FacilityKey", True),
    ("FactARMovement.PayerKey", "DimPayer.PayerKey", True),
]

RLS_ROLE = "Facility Access"

# Provider and facility are ONE hierarchy here - every provider bills only at their own
# facility - so a facility-scoped user is filtered on the facility dimension AND on the
# provider dimension's own FacilityID. Filtering only the facility would leave every one
# of the 500 provider names visible in a slicer with no data behind them.
FACILITY_SCOPE = """VAR UserFacilities =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[FacilityID] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
RETURN
    "ALL" IN UserFacilities || DimFacility[FacilityID] IN UserFacilities"""

PROVIDER_SCOPE = """VAR UserFacilities =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[FacilityID] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
VAR UserProviders =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[ProviderID] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
RETURN
    ( "ALL" IN UserFacilities || DimProvider[FacilityID] IN UserFacilities )
        && ( "ALL" IN UserProviders || DimProvider[ProviderID] IN UserProviders )"""

RLS_FILTERS = {
    "DimFacility": FACILITY_SCOPE,
    "DimProvider": PROVIDER_SCOPE,
    # The provider-level chance table is disconnected, so no relationship carries the
    # facility filter to it. It is filtered directly, or a facility manager would read
    # the whole group's provider distribution.
    "ProviderChance": """VAR UserFacilities =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[FacilityID] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
VAR UserProviders =
    CALCULATETABLE (
        VALUES ( SecurityUserAccess[ProviderID] ),
        SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()
    )
VAR ScopedFacilities =
    CALCULATETABLE (
        VALUES ( DimProvider[FacilityName] ),
        REMOVEFILTERS ( ),
        DimProvider[FacilityID] IN UserFacilities
    )
RETURN
    ( "ALL" IN UserFacilities || ProviderChance[FacilityName] IN ScopedFacilities )
        && ( "ALL" IN UserProviders || ProviderChance[ProviderID] IN UserProviders )""",
    # A user may see only their own mapping row.
    "SecurityUserAccess": "SecurityUserAccess[UserEmail] = USERPRINCIPALNAME ()",
}

# DimPatient is deliberately NOT filtered. A patient may be treated at more than one
# facility, so a patient-level filter would be wrong in both directions - and it is
# unnecessary, because the facility filter already restricts every claim a scoped user
# can see.

PARAMETERS = [
    ("SqlServer", "localhost\\SQLEXPRESS",
     "SQL Server instance hosting HealthcareRCMBI. The only place the server is named."),
    ("SqlDatabase", "HealthcareRCMBI", "Database holding the analytics views."),
]


# ----------------------------------------------------------------- rendering ---
def desc_lines(text, indent):
    return [f"{indent}/// {text}"] if text else []


def render_column(t, c):
    L = desc_lines(c.desc, "\t") + [f"\tcolumn {q(c.name)}", f"\t\tdataType: {c.dtype}"]
    if c.hidden:
        L.append("\t\tisHidden")
    if c.key:
        L.append("\t\tisKey")
    fmt = c.fmt or {"dateTime": "yyyy-mm-dd", "boolean": BOOL_FMT}.get(c.dtype)
    if fmt:
        L.append(f"\t\tformatString: {fmt}")
    L.append(f"\t\tlineageTag: {tag(t.name, 'column', c.name)}")
    if c.category:
        L.append(f"\t\tdataCategory: {c.category}")
    L += [f"\t\tsummarizeBy: {c.summarize}", f"\t\tsourceColumn: {c.name}"]
    if c.sort_by:
        L.append(f"\t\tsortByColumn: {q(c.sort_by)}")
    L += ["", "\t\tannotation SummarizationSetBy = Automatic"]
    if c.dtype == "dateTime":
        L += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    return L + [""]


def render_measure(t, m):
    L = desc_lines(m["desc"], "\t")
    body = m["dax"].strip("\n").split("\n")
    if len(body) == 1:
        L.append(f"\tmeasure {q(m['name'])} = {body[0]}")
    else:
        L.append(f"\tmeasure {q(m['name'])} =")
        L += ["\t\t\t" + b if b else "" for b in body]
    if m.get("fmt"):                       # Power BI's order: format string, then hidden
        L.append(f"\t\tformatString: {m['fmt']}")
    if m.get("hidden"):
        L.append("\t\tisHidden")
    if m.get("folder"):
        L.append(f"\t\tdisplayFolder: {m['folder']}")
    L.append(f"\t\tlineageTag: {tag(t.name, 'measure', m['name'])}")
    return L + [""]


def partition_m(t):
    if t.source.startswith("vw_"):
        step = f"analytics_{t.source}"
        m = ("let\n"
             "    Source = Sql.Database(SqlServer, SqlDatabase),\n"
             f"    {step} = Source{{[Schema=\"analytics\",Item=\"{t.source}\"]}}[Data]\n"
             "in\n"
             f"    {step}")
    else:
        m = t.source
    return m.split("\n")


def render_table(t, measures):
    L = desc_lines(t.desc, "") + [f"table {q(t.name)}"]
    if t.hidden:
        L.append("\tisHidden")
    L.append(f"\tlineageTag: {tag(t.name)}")
    if t.category:
        L.append(f"\tdataCategory: {t.category}")
    L.append("")
    for m in measures:
        L += render_measure(t, m)
    for c in t.cols:
        L += render_column(t, c)
    for hname, levels in t.hierarchies:
        L += [f"\thierarchy {q(hname)}", f"\t\tlineageTag: {tag(t.name, 'hierarchy', hname)}", ""]
        for lv in levels:
            L += [f"\t\tlevel {q(lv)}", f"\t\t\tlineageTag: {tag(t.name, 'hierarchy', hname, lv)}",
                  f"\t\t\tcolumn: {q(lv)}", ""]
    L += [f"\tpartition {q(t.name)} = m", "\t\tmode: import", "\t\tsource ="]
    L += ["\t\t\t\t" + x if x else "" for x in partition_m(t)]
    L += ["", "\tannotation PBI_NavigationStepName = Navigation", "", "\tannotation PBI_ResultType = Table", ""]
    return L



def render_field_parameter(fp):
    """A field parameter table. Three columns by convention - the label, the field
    reference, and the sort order - and the middle one carries the extended
    property that tells Power BI it holds fields rather than text. Written as a
    CALCULATED partition, because the rows are NAMEOF() references resolved by the
    engine, not data read from SQL."""
    name = fp["name"]
    L = desc_lines(fp["desc"], "") + [f"table {q(name)}", f"\tlineageTag: {tag(name)}", ""]
    L += [f"\tcolumn {q(name)}", "\t\tdataType: string",
          f"\t\tlineageTag: {tag(name, 'column', name)}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: [Value1]",
          f"\t\tsortByColumn: {q(name + ' Order')}", "",
          "\t\tannotation SummarizationSetBy = Automatic", ""]
    L += [f"\tcolumn {q(name + ' Fields')}", "\t\tdataType: string", "\t\tisHidden",
          f"\t\tlineageTag: {tag(name, 'column', name + ' Fields')}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: [Value2]", "",
          # A blank line before extendedProperty, exactly as before a calculation
          # item's formatStringDefinition: Power BI inserts one on save.
          "\t\textendedProperty ParameterMetadata =",
          "\t\t\t\t{",
          '\t\t\t\t  "version": 3,',
          '\t\t\t\t  "kind": 2',
          "\t\t\t\t}", "",
          "\t\tannotation SummarizationSetBy = Automatic", ""]
    L += [f"\tcolumn {q(name + ' Order')}", "\t\tdataType: int64", "\t\tisHidden",
          "\t\tformatString: 0",
          f"\t\tlineageTag: {tag(name, 'column', name + ' Order')}",
          "\t\tsummarizeBy: sum", "\t\tsourceColumn: [Value3]", "",
          "\t\tannotation SummarizationSetBy = Automatic", ""]
    rows = [f'\t\t\t\t    ("{label}", NAMEOF(\'{tbl}\'[{col}]), {i}),'
            for i, (label, tbl, col) in enumerate(fp["fields"])]
    rows[-1] = rows[-1].rstrip(",")
    L += [f"\tpartition {q(name)} = calculated", "\t\tmode: import", "\t\tsource =",
          "\t\t\t\t{"] + rows + ["\t\t\t\t}", ""]
    L += [f"\tannotation PBI_Id = {uuid.uuid5(NS, 'fieldparam/' + name).hex}", ""]
    return L


def render_calc_group(g):
    """A calculation group table: the group, its items, and the Name / Ordinal
    columns Power BI expects. Item expressions sit one level below the item, and
    the order the items are written IS the reporting order: an explicit `ordinal:`
    only repeats it, and Power BI strips it out again on the next save."""
    L = desc_lines(g["desc"], "") + [f"table {q(g['name'])}", f"\tlineageTag: {tag(g['name'])}", "",
                                     "\tcalculationGroup", f"\t\tprecedence: {g['precedence']}", ""]
    for item, desc, dax, fmt in g["items"]:
        L += desc_lines(desc, "\t\t")
        body = dax.strip("\n").split("\n")
        if len(body) == 1:
            # A one-line expression stays on the item's own line: Power BI only
            # breaks to a continuation when the expression needs more than one.
            L += [f"\t\tcalculationItem {q(item)} = {body[0].strip()}"]
        else:
            L += [f"\t\tcalculationItem {q(item)} ="]
            L += ["\t\t\t\t" + b if b else "" for b in body]
        if fmt:
            # A format-string definition must be ONE line: TMDL expects any
            # continuation indented a level deeper, and a multi-line value here
            # fails the parser with "Unexpected line type: Other".
            L += ["", f"\t\t\tformatStringDefinition = {' '.join(fmt.split())}"]   # after a blank line, as Power BI writes it
        L.append("")
    L += [f"\tcolumn {q(g['column'])}", "\t\tdataType: string", f"\t\tlineageTag: {tag(g['name'], 'column', g['column'])}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: Name", "\t\tsortByColumn: Ordinal", "",
          "\t\tannotation SummarizationSetBy = Automatic", "",
          "\tcolumn Ordinal", "\t\tdataType: int64", "\t\tisHidden", "\t\tformatString: 0",
          f"\t\tlineageTag: {tag(g['name'], 'column', 'Ordinal')}", "\t\tsummarizeBy: sum", "\t\tsourceColumn: Ordinal",
          "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    return L


def write(path, lines):
    """TMDL exactly as Power BI saves it: CRLF, and the file ends with one blank
    line, so a Power BI save of an unchanged model is a no-op in Git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip("\n") + "\n\n"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def write_json(path, obj):
    """JSON as Power BI saves it: two-space indent, CRLF, no final newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=2).replace("\n", "\r\n").encode("utf-8"))


def main():
    from model_measures import CALC_GROUPS, FIELD_PARAMETERS, MEASURES

    names = [t.name for t in TABLES]
    # Calculation groups and field parameters are tables too: they must appear in
    # model.tmdl's ref list and its query order, or Power BI loads the folder
    # without them and the report silently loses a slicer.
    group_names = [g["name"] for g in CALC_GROUPS] + [f["name"] for f in FIELD_PARAMETERS]

    tdir = DEF / "tables"
    if tdir.exists():
        shutil.rmtree(tdir)
    for t in TABLES:
        write(tdir / f"{t.name}.tmdl", render_table(t, MEASURES if t.name == "_Measures" else []))
    for g in CALC_GROUPS:
        write(tdir / f"{g['name']}.tmdl", render_calc_group(g))
    for fp in FIELD_PARAMETERS:
        write(tdir / f"{fp['name']}.tmdl", render_field_parameter(fp))

    rel = []
    for f, to, active in RELATIONSHIPS:
        rel += [f"relationship {tag('rel', f, to)}"]
        if not active:
            rel.append("\tisActive: false")
        rel += [f"\tfromColumn: {f}", f"\ttoColumn: {to}", ""]
    write(DEF / "relationships.tmdl", rel)

    ex = []
    for n, v, d in PARAMETERS:
        ex += [f"/// {d}",
               f'expression {n} = "{v}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
               f"\tlineageTag: {tag('expression', n)}", "", "\tannotation PBI_ResultType = Text", ""]
    write(DEF / "expressions.tmdl", ex)

    rdir = DEF / "roles"
    if rdir.exists():
        shutil.rmtree(rdir)
    ro = ["/// Dynamic security from the user's email. A facility manager sees one facility; a provider sees one "
          "provider; Revenue Cycle and the Executive are mapped to ALL. Because every provider bills only at their "
          "own facility, provider and facility are one hierarchy and both dimensions are filtered - filtering only "
          "the facility would leave 500 provider names in a slicer with no data behind them. An unmapped user sees "
          "nothing, which is the secure default.",
          f"role {q(RLS_ROLE)}", "\tmodelPermission: read", ""]
    for tbl, dax in RLS_FILTERS.items():
        body = dax.split("\n")
        if len(body) == 1:
            ro += [f"\ttablePermission {q(tbl)} = {body[0]}", ""]
        else:
            ro += [f"\ttablePermission {q(tbl)} ="] + ["\t\t\t" + b if b else "" for b in body] + [""]
    # Power BI stamps every role with a PBI_Id on save; a stable one keeps Git clean.
    ro += [f"\tannotation PBI_Id = {uuid.uuid5(NS, 'role/' + RLS_ROLE).hex}", ""]
    write(rdir / f"{RLS_ROLE}.tmdl", ro)

    # Cultures come from Power BI itself: it generates the Q&A linguistic schema from
    # the model and rewrites this file whenever the model changes. Seed it once, then
    # leave it alone - rewriting the stub each run threw away what Power BI had written.
    culture = DEF / "cultures" / "en-US.tmdl"
    if not culture.exists():
        write(culture,
              ["cultureInfo en-US", "", "\tlinguisticMetadata =", "\t\t\t{", '\t\t\t  "Version": "1.0.0",',
               '\t\t\t  "Language": "en-US"', "\t\t\t}", "\t\tcontentType: json"])
    shutil.copyfile(SCAFFOLD / "database.tmdl", DEF / "database.tmdl")
    shutil.copyfile(SCAFFOLD / "definition.pbism", SM / "definition.pbism")

    order = json.dumps([p[0] for p in PARAMETERS] + names + group_names, separators=(",", ":"))
    mdl = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
           # required by calculation groups: implicit measures would bypass them
           "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: en-US", "\tdataAccessOptions",
           "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
           "annotation __PBI_TimeIntelligenceEnabled = 0", "",
           'annotation PBI_ProTooling = ["DevMode"]', "",
           f"annotation PBI_QueryOrder = {order}", ""]
    mdl += [f"ref table {q(n)}" for n in names + group_names]
    mdl += ["", f"ref role {q(RLS_ROLE)}", "", "ref cultureInfo en-US", ""]
    write(DEF / "model.tmdl", mdl)

    # ------------------------------------------------ PBIP / report shell ---
    write_json(PBI / f"{NAME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    plat = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
    write_json(SM / ".platform", {"$schema": plat, "metadata": {"type": "SemanticModel", "displayName": NAME},
                                  "config": {"version": "2.0", "logicalId": tag("logical", "semanticmodel")}})
    write_json(RP / ".platform", {"$schema": plat, "metadata": {"type": "Report", "displayName": NAME},
                                  "config": {"version": "2.0", "logicalId": tag("logical", "report")}})
    write_json(RP / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})

    theme_dir = RP / "StaticResources" / "SharedResources" / "BaseThemes"
    theme_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCAFFOLD / "StaticResources/SharedResources/BaseThemes/CY25SU10.json", theme_dir / "CY25SU10.json")
    (RP / "definition").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCAFFOLD / "version.json", RP / "definition" / "version.json")
    if not (RP / "definition" / "report.json").exists():
        # the base shell; the report generator adds the client theme in Phase 3
        report = json.loads((SCAFFOLD / "report.json").read_text(encoding="utf-8-sig"))
        report["themeCollection"].pop("customTheme", None)
        report["resourcePackages"] = [p for p in report["resourcePackages"] if p["type"] != "RegisteredResources"]
        write_json(RP / "definition" / "report.json", report)

    pages = RP / "definition" / "pages"
    pid = uuid.uuid5(NS, "page.overview").hex[:20]
    if not (pages / "pages.json").exists():     # never overwrite report pages built later
        write_json(pages / "pages.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [pid], "activePageName": pid})
        write_json(pages / pid / "page.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
            "name": pid, "displayName": "Overview", "displayOption": "FitToPage", "height": 720, "width": 1280})

    ncols = sum(len(t.cols) for t in TABLES)
    nitems = sum(len(g["items"]) for g in CALC_GROUPS)
    print(f"{len(TABLES)} tables + {len(CALC_GROUPS)} calculation groups ({nitems} items), {ncols} columns, "
          f"{len(RELATIONSHIPS)} relationships ({sum(1 for r in RELATIONSHIPS if r[2])} active), "
          f"1 role ({len(RLS_FILTERS)} table filters), {len(MEASURES)} measures")


if __name__ == "__main__":
    main()
