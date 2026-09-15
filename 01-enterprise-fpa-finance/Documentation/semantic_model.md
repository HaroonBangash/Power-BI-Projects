# Semantic Model — Enterprise FP&A Finance

Generated as code by `Python/02_generate_semantic_model.py` (TMDL) from the
specification in that file and `Python/model_measures.py`. Nothing is hand-edited
in Power BI Desktop, so a re-run is byte-identical and the Git diff is the change.

**20 tables + 2 calculation groups (11 items), 153 columns, 23 relationships
(19 active), 130 measures in 11 folders, 1 security role with 6 table filters.**

Evidence: `Validation/verify_semantic_model.py` **784 of 784** static checks;
`Validation/reconcile_measures.ps1` **521 of 521** live checks against independent
SQL. The data is synthetic.

## Shape

```
                        DimDate (date table, FY Jul-Jun)
                           │        │        │       │
      ┌────────────────────┘        │        │       └──────────────┐
      │                             │        │                      │
  FactFinancials               FactGL   FactARInvoice          FactCashBalance
  version × month ×            one      one invoice            entity × day
  entity × dept × account      ledger   (+ FactAPBill)
      │      │      │          line
  DimEntity DimDepartment DimAccount        DimCustomer / DimVendor
```

Disconnected by design: `DimPLLine` (statement layout), `DimAgeingBucket`
(ageing computed as of any date), `DimScenario` and `DimSensitivityStep`
(planning drivers), `ModelConfig`, `SecurityUserAccess`.

| Table | Grain | Rows |
|---|---|---:|
| `FactFinancials` | version × month × entity × department × account | 168,782 |
| `FactGL` | one general-ledger line, local currency and AUD | 80,000 |
| `FactARInvoice` / `FactAPBill` | one invoice / one bill | 18,000 / 12,000 |
| `FactCashBalance` | one entity's closing cash on one day | 10,224 |
| `FxRateMonthly` | month × currency: average and closing rate | 336 |
| `DimDate` | one day, 2022-01-01 to 2027-06-30 | 2,007 |

`FactFinancials` is the point of the model: actual, budget and forecast at one
grain means every plan comparison is **one measure under a different version**,
which is exactly what a calculation group does. Actual rows are the ledger summed
to the month (47,822 rows for 80,000 lines) and equal `FactGL` to the cent at
every grain — checked in SQL and again in the live model.

## The two calculation groups

| Group | Precedence | Items |
|---|---:|---|
| **Plan Version** | 20 | Actual, Budget, Forecast, Var vs Budget, Var % vs Budget, Var vs Forecast, Var % vs Forecast |
| **Period View** | 10 | Selected period, Year to date, Prior year, Prior year to date |

Plan Version has the higher precedence, so it is applied **outermost**: "Var % vs
Budget" of a year-to-date figure divides two year-to-date figures. That is
verified, not assumed — the reconciliation compares the calculation group's result
with the same arithmetic written out by hand, for every period item.

Rules the items enforce:

- **Variance is favourable-positive.** For revenue and profit, actual less plan;
  for a cost, plan less actual, so an underspend reads positive. The sign comes
  from the measure in the visual (`ISSELECTEDMEASURE`), from the statement line
  (`DimPLLine[FavourableSign]`) or from the account's `IsIncome`.
- **No plan, no variance.** Interest, FX gain/loss and tax have actuals but no
  budget: the variance is blank, never a 100% miss.
- **Margins vary in percentage points**, and "Var %" is blank on a margin line —
  a percentage of a percentage would mislead.
- **Windows end at the balance date.** Every Period View item is capped at the
  as-of date *before* it is shifted, so FY27's two months are compared with the
  same two months of FY26, not with a full year.

## Measures

130 measures in 11 folders; see
[dax_measure_dictionary.md](dax_measure_dictionary.md) for every definition with
its measured value.

| Folder | Covers |
|---|---|
| 01 Model Controls | as-of date, balance date, months remaining, page context |
| 02 Income Statement | revenue to net profit, margins, the statement line, account detail |
| 03 Plan vs Actual | explicit budget/forecast measures, variances, variance z-scores |
| 04 Time Comparison | prior year, year to date, trailing twelve months |
| 05 FX & Constant Currency | revenue at prior-year rates, translation effect, rates |
| 06 Ledger Detail | ledger amounts, lines, accrued share, vendors and customers |
| 07 Working Capital | AR/AP balances, ageing, DSO, DPO, collection speed |
| 08 Cash | closing, average and minimum daily cash |
| 09 Scenario Planning | run rates, the full-year outlook, sensitivity |
| 10 Data Quality | metrics computed live in SQL, as-of exceptions |
| 11 Report Formatting | dead-zone signal colours |

Three conventions worth naming:

1. **Ledger sign in, presentation sign out.** Tables keep debit + / credit −;
   measures present revenue, costs and profit as positive numbers.
2. **Balances are computed, never read.** `[Balance Date]` is the last day in
   context capped at the as-of date; an invoice is open on it when it was issued
   by then and unpaid then. The source `Status` column is ignored for balances,
   because the extract contains 769 receipts dated after the as-of date.
3. **Ageing is dynamic.** `[AR Ageing Amount]` ages each invoice against the
   balance date, so the buckets are right for any period a user selects — the
   stored as-of bucket exists only for reconciliation.

## Row-level security

One role, **Entity and Department Access**, reading `USERPRINCIPALNAME()`:

| Table | Filter |
|---|---|
| `DimEntity` | the user's entity, or all of them when mapped to `ALL` |
| `DimDepartment` | the user's department, or all |
| `FactARInvoice`, `FactAPBill`, `FactCashBalance` | visible only to users whose department scope is `ALL` |
| `SecurityUserAccess` | the user's own mapping row |

Receivables, payables and cash carry an entity but no department, so a
department-scoped user (the Sales manager, say) sees that department's income
statement across entities and **no treasury data at all** — a cost-centre view is
not a group cash view. An unmapped user sees nothing: the secure default is
tested, and every one of the 18 mapped users' scopes is checked.

## FX

The ledger is translated line by line at the **monthly average rate** (IAS 21
practice), with AUD fixed at 1. Each line also carries its own day's spot
translation (for audit: the whole-ledger difference is 0.005%) and the same
month's rate a year earlier, which is what makes constant-currency growth a
column rather than a calculation.

## Performance

The income statement reads the 168,782-row monthly fact, not the 80,000-line
ledger (and not the multi-million-line ledger the dataset can be scaled to).
`FactGL` stays for drill-through and ledger detail. A full refresh of the whole
model through the engine takes about 9 seconds.
