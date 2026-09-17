# SQL Data Platform — MarketingAttributionBI

## Run

```powershell
powershell -ExecutionPolicy Bypass -File SQL\run_all.ps1                  # default: localhost\SQLEXPRESS
powershell -ExecutionPolicy Bypass -File SQL\run_all.ps1 -Server "host\instance"
```

Runs `01`–`09` in order and stops at the first failure. `09` throws if any
validation check fails, so a green run means every check passed. Fully
idempotent: the database is dropped and rebuilt each time.

**Prerequisites.** SQL Server 2022 or later (Express is enough — `GENERATE_SERIES`
needs 2022+) and `sqlcmd`. `BULK INSERT` reads files on the server side, so the SQL
Server service account needs read access to `Data\raw`.

**No machine path is committed.** `run_all.ps1` resolves `Data\raw` from the
repository location and passes it as the environment variable `DataRoot`, which
`sqlcmd` exposes to `03_load_staging.sql` as `$(DataRoot)`. (Passing it with
`-v DataRoot=...` fails when the path contains spaces, and Windows PowerShell 5.1
strips the quotes that would fix it.)

## Scripts

| Script | Does |
|---|---|
| `01_create_database.sql` | Creates `MarketingAttributionBI` with schemas `stg`, `dbo`, `analytics` |
| `02_create_staging_tables.sql` | One NVARCHAR landing table per CSV, columns in file order; `stg.LoadLog` |
| `03_load_staging.sql` | `BULK INSERT` of all 10 files; fails on any row-count mismatch with the published counts |
| `04_create_core_tables.sql` | Typed star schema: 10 dimension/config tables, 6 facts, 25 foreign keys, CHECK constraints; persisted `PositionBand` on `FactTouchpoint` |
| `05_load_dimensions.sql` | `ModelConfig`, FX planning rates, calendar regenerated to 2027-06-30 with `IsAfterAsOf` and `IsQuarterComplete` flags, dimensions, the five-stage `DimFunnelStage` |
| `06_load_facts.sql` | Types the facts; derives journey order, funnel stage, USD spend, as-of flags |
| `07_build_attribution.sql` | `FactAttributionCredit`: 5 models × 174,938 touches = 874,690 weights; per-model campaign dispersion for the report's signal test |
| `08_create_views.sql` | 17 `analytics.vw_*` views — the only objects Power BI reads, including the one-row-per-lead `vw_FactLeadFunnel` snapshot, which also states each lead as it stood on the as-of date, and the channel-carrying `vw_DimCampaign` |
| `09_validation.sql` | 82 checks, expected vs actual, PASS/FAIL; throws on any failure |

## Where the expected values come from

Literal expected values in `09_validation.sql` are measured by
`Python/01_data_audit.py` directly from the raw CSVs (published in
`Validation/audit_metrics.json`), never read back from these tables. The
attribution weights are independently recomputed in pandas by
`Validation/validate_attribution.py` and compared row by row.

## Design notes

- **Staging has no extra columns.** `BULK INSERT` maps by position; an IDENTITY or
  DEFAULT column raises Msg 7301. Load lineage lives in `stg.LoadLog`.
- **Typing fails loudly.** `06` counts every value that will not convert and throws
  before loading, rather than letting a NULL or truncation reach `dbo`.
- **Keys are trusted.** Every foreign key is created before its data loads, so the
  engine validates each row and marks the key trusted (`is_not_trusted = 0`,
  checked in `09`).
- Decisions and their rationale are logged in [../PROJECT_STATE.md](../PROJECT_STATE.md).
