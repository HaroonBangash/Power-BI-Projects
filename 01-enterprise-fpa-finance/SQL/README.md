# SQL Data Platform — FinancePlanningBI

## Run

```powershell
powershell -ExecutionPolicy Bypass -File SQL\run_all.ps1                  # default: localhost\SQLEXPRESS
powershell -ExecutionPolicy Bypass -File SQL\run_all.ps1 -Server "host\instance"
```

Runs `01`–`09` in order and stops at the first failure. `09` throws if any
validation check fails, so a green run means every check passed. Fully
idempotent: the database is dropped and rebuilt each time (about 12 seconds).

**Prerequisites.** SQL Server 2019 or later (Express is enough) and `sqlcmd`.
`BULK INSERT` reads files on the server side, so the SQL Server service account
needs read access to `Data\raw`.

**No machine path is committed.** `run_all.ps1` resolves `Data\raw` from the
repository location and passes it as the environment variable `DataRoot`, which
`sqlcmd` exposes to `03_load_staging.sql` as `$(DataRoot)`.

## Scripts

| Script | Does |
|---|---|
| `01_create_database.sql` | Creates `FinancePlanningBI` with schemas `stg`, `dbo`, `analytics`; turns on Query Store (used to prove query folding) |
| `02_create_staging_tables.sql` | One NVARCHAR landing table per CSV, columns in file order; `stg.LoadLog` |
| `03_load_staging.sql` | `BULK INSERT` of all 14 files; fails on any row-count mismatch with the published counts |
| `04_create_core_tables.sql` | Typed star schema: 13 dimension/config tables, 7 facts, 39 foreign keys, CHECK constraints |
| `05_load_dimensions.sql` | `ModelConfig` (as-of date derived from the ledger), calendar to 2027-06-30 with financial-year columns and as-of flags, dimensions, ageing buckets, scenario drivers, FX (AUD fixed at 1; monthly average rates) |
| `06_load_facts.sql` | Types the facts; translates every GL line at its month's average rate (spot and prior-year rate kept alongside); derives each invoice's and bill's state on the as-of date |
| `07_build_financials.sql` | `FactFinancials`: Actual (GL summed to the month), Budget and Forecast in one fact at one grain |
| `08_create_views.sql` | 17 `analytics.vw_*` views — the only objects Power BI reads; unknown customer/vendor members |
| `09_validation.sql` | 108 checks, expected vs actual, PASS/FAIL; throws on any failure |

## Where the expected values come from

Literal expected values in `09_validation.sql` are measured by
`Python/01_data_audit.py` directly from the raw CSVs (published in
`Validation/audit_metrics.json`), never read back from these tables. The audit
translates money in `Decimal` with the same rule as SQL — monthly average rate
rounded half away from zero to 6 dp, each line rounded to the cent — so every
money check is exact, not approximate.

## Design notes

- **Ledger sign everywhere.** Amounts keep debit + / credit −; revenue is negative in
  every table. Presentation signs belong to the semantic model.
- **Balances are computed, not read.** `IsOpenAsOf` and the ageing bucket come from
  the document dates against the as-of date. The source `Status` column reflects an
  extract taken after the as-of date and is kept only for audit.
- **Typing fails loudly.** NOT NULL targets reject any unparseable value; the one
  nullable parsed column (`PaidDate`) is checked explicitly; every fact's row count
  is asserted after its insert.
- **Keys are trusted.** Every foreign key is created before its data loads, so the
  engine validates each row (`is_not_trusted = 0`, checked in `09`).
- Decisions and their rationale are logged in [../PROJECT_STATE.md](../PROJECT_STATE.md).
