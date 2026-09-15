# Enterprise FP&A & Financial Planning Dataset

Designed for advanced financial modelling: actuals, budget, forecast, AR/AP, cash, FX and dynamic security.

## Purpose
This dataset is **synthetic and portfolio-safe**. It is designed for an advanced Power BI project rather than a beginner dashboard.

## Suggested Architecture
Raw CSVs → SQL database / Fabric Lakehouse → Power Query / Dataflow → Semantic Model → Power BI Service

## Tables
- **fact_gl.csv** — General ledger transactions (80k starter rows)
- **fact_budget.csv** — Monthly budget by entity, department and account
- **fact_forecast.csv** — Monthly forecast with scenarios
- **fact_ar.csv** — Accounts receivable invoices
- **fact_ap.csv** — Accounts payable bills
- **fact_cash_balance.csv** — Daily entity cash balances
- **fact_fx_rates.csv** — Daily FX rates into AUD
- **dim_*** — Date, entity, department, account, customer and vendor dimensions
- **security_user_access.csv** — Dynamic RLS mapping

## Suggested Relationships
- dim_date[Date] 1:* fact_gl[Date]
- dim_entity[EntityID] 1:* all finance fact tables
- dim_department[DepartmentID] 1:* fact_gl / budget / forecast
- dim_account[AccountCode] 1:* fact_gl / budget / forecast
- security_user_access should filter entity/department through a security bridge

## Advanced Tasks to Implement
1. Build Actual vs Budget vs Forecast calculation groups.
2. Create dynamic scenario modelling using disconnected parameter tables.
3. Implement FX conversion from local currency to AUD.
4. Create AR/AP ageing buckets and working-capital KPIs.
5. Implement dynamic RLS by user email, entity and department.
6. Optimise the model and document DAX Studio / Performance Analyzer improvements.

## Scaling Notes
The starter dataset is intentionally moderate in size. Use the included generator script to multiply transaction-level facts to 1M–10M rows for incremental-refresh and performance testing.
