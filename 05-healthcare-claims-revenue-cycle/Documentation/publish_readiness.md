# Publish Readiness

Everything this project claims, and the test that proves it. Every figure below was
produced by a script in `Validation/` against the live model and the live database —
none of it is typed by hand.

| Check | Script | Result |
|---|---|---|
| SQL build and validation | `SQL/08_validation.sql` | **121 of 121** |
| Semantic model vs the live SQL views | `verify_semantic_model.py` | **966 of 966** |
| Every measure vs independently written SQL | `reconcile_measures.ps1` | **700 of 700** |
| Every visual's own query returns data | `validate_visuals.ps1` | **218 of 218** |
| Layout, navigation and theme | `validate_report_layout.py` | **0 issues** |
| Interaction: slicers, calculation groups, field parameter, RLS | `test_interactions.ps1` | **46 of 46** |
| Query folding to SQL Server | `check_query_folding.sql` | **24 of 24 views folded, 0 unfolded** |
| A genuine Power BI save | `save_round_trip.ps1` | **288 files, 0 changed** |
| Report schema, fields, geometry, overlap | `04_generate_report.py --check` | **0 errors** |

**The whole build runs in about a minute:** SQL 36 s, model refresh 12.6 s.

---

## 1. The two identities

These are the claims the whole model is built to protect, and they are re-checked on
every build and every refresh.

**Every allowed dollar is in exactly one of four buckets.**

```
AllowedAmount = PaidAmount + PatientResponsibility + OpenARAmount + DeniedAmount
```

Measured live: allowed **$72,713,182.33** = collected **$46,414,738.26** + patient
responsibility **$3,768,666.11** + open AR **$16,830,999.94** + denied
**$5,698,778.02**. Gap: **$0.00**.

Because it holds *row by row*, it holds at every level of every aggregation.
`test_interactions.ps1` re-checks it inside a payer, inside a facility type, inside a
specialty and inside a month — an identity that closes only at the grand total is not
an identity.

**The receivable rolls forward, in all 47 months.**

```
AR(m) = AR(m−1) + submitted − collected − patient responsibility − denied
```

A 670,151-row snapshot and a 246,040-row ledger, built independently and reconciled
against each other. A snapshot alone can drift unnoticed; a ledger alone cannot be
aged. `[AR Roll-Forward Check]` returns the difference and is anchored to the snapshot
month, so it reads zero at *every* grain and not only inside a monthly visual.

Open AR read from the snapshot agrees with open AR read from the claim header **to the
cent** — two entirely separate routes to the same number.

---

## 2. Query folding

Every one of the 24 analytics views the model imports was read with a native
column-list `SELECT` against SQL Server. Zero `select *` statements. Proved from the
**server** side by reading Query Store, not by asking Power Query whether it folded.

Two things this check had to learn:

- **Query Store defaults to `AUTO` capture**, which discards cheap and infrequent
  queries — so the six-row dimension reads never appeared and only the nine expensive
  fact queries did. That looks exactly like partial folding and is not.
  `QUERY_CAPTURE_MODE = ALL` is now set unconditionally in `01_create_database.sql`,
  and the store is cleared on each build so a stale capture can never pass the check.
- **`COUNT(*)` over a LEFT JOIN counts the null-extended row**, so a view with no
  statement at all reported one, and "not seen" printed as "seen, but not a column
  list".

---

## 3. Performance

Full refresh through the engine: **4.6 s**. Model in memory: **42.5 MB** across 1,143
segments, of which `FactARSnapshot` is 14.7 MB.

The heaviest query behind each page, median of three runs:

| Page | Query | Time |
|---|---|---:|
| Executive | Billed, allowed and collected by month | 4 ms |
| Receivables | Open AR at all 47 month ends | 22 ms |
| Receivables | Payer by ageing bucket | 6 ms |
| Denials | Rate by payer, reason and month | 4 ms |
| Mix | The decomposition tree's widest level | 4 ms |
| — | **Both calculation groups over every month** (1,065 rows) | **72 ms** |

### Why the snapshot earns its 670,151 rows

| | |
|---|---:|
| Open AR at every month end, **from the snapshot** | **20 ms** |
| The same, computed from dates at query time | 339 ms |

Seventeen times faster — and the snapshot is also what makes the receivable *ageable*
at all, because a receivable's age is a property of a date, not of a claim.

---

## 4. The save round trip

The generator writes Power BI's own save format, so a genuine Ctrl+S in Desktop must be
a no-op in Git. The test snapshots the `PowerBI` folder, activates Desktop, sends
Ctrl+S, waits 30 seconds and compares byte for byte. **288 files, none changed.** The
save is real, not skipped: Power BI rewrote `cache.abf` and its own per-machine
settings in the same window, and those are git-ignored.

Most of this held on the first run because the generator already carries what earlier
projects in this series learned the hard way — visual `position` is written height
before width; a measure writes `formatString` before `isHidden`; a calculation item
takes a blank line before its `formatStringDefinition` and no `ordinal:`; a field
parameter's `extendedProperty` takes a blank line before it; a one-line calculation
item stays on its own line; and `cultures/en-US.tmdl` belongs to Power BI.

One new rule was learned here: **Power BI TRIMS a measure expression when it saves.**
A DAX expression that begins or ends with a double quote needs a space between it and
Python's `"""` delimiter, or the delimiter swallows the quote — but leaving that space
in the file made every save rewrite the measure. The generator strips the body and
every line's trailing whitespace now.

---

## 5. Security

Row-level security is dynamic, from `USERPRINCIPALNAME()`, against an 82-row mapping
table. **167 security checks pass**, covering:

- **The secure default.** A user with no mapping row sees no facilities and no money.
  This is checked first, because a role that passes only by returning everything is a
  hole, not a filter.
- **Every one of the 82 mapped users**, evaluated through the role's own filter
  expression and compared against SQL: the right number of facilities, and the right
  allowed amount.
- **That provider and facility are one hierarchy.** A facility-scoped user sees that
  facility's providers and no others — filtering only the facility would leave all 500
  provider names in a slicer with nothing behind them.
- **`ProviderChance` is filtered explicitly**, because it is disconnected and no
  relationship would carry the facility filter to it.

`DimPatient` is deliberately *not* filtered, and the verifier asserts that it isn't: a
patient may be treated at more than one facility, so a patient filter would be wrong in
both directions — and unnecessary, because the facility filter already restricts every
claim a scoped user can reach.

---

## 6. Interaction

A rendered page proves a visual draws. These 46 tests prove the page still tells the
truth when a reader *uses* it: each interactive state is reproduced as the query that
state produces and compared with independently written SQL.

The most important group is **filter travel**. Each of these reads a measure from a
different fact than the dimension is usually thought to belong to — claim *lines* by
payer, *denials* by specialty, *cash* by payer, *AR movement* by facility type. If any
fact were missing its own dimension key, the filter would stop at the claim header and
leave the other table whole: a full numerator over a shrinking denominator, which reads
as a plausible number and is wrong. That is the defect that took longest to find in the
previous project in this series, so here it is a test rather than a comment — and
`verify_semantic_model.py` additionally fails the build if any conformed dimension
stops reaching any fact.

Also covered: both calculation groups applied **together** (the precedence is the
point), that a comparison with nothing to compare against is BLANK rather than the
whole figure reported as growth, and that nothing is reported past the as-of month
whatever is selected.

**Not covered, and said rather than implied:** whether Power BI substitutes the field
parameter's chosen column *inside* a visual. That resolution happens when the visual's
query is built, not in a query this harness can write, so it is proven by rendering the
page and reading the axis — see `Validation/evidence/`.

---

## 7. What is not verified

| | |
|---|---|
| Publishing to the Power BI Service | Not done. This is a local PBIP project |
| Incremental refresh | Requires the Service. Folding to SQL Server is proved instead, which is its precondition |
| DirectQuery / composite models | Not built. The model is import-only |
| Gateway, workspace, app deployment | Out of scope |
| Behaviour on data other than this file | The build fails loudly on any row-count mismatch, so a different file stops at `03_load_staging.sql` rather than producing a wrong report |

---

## 8. Before this could be published for real

The dataset is **synthetic**. If this were a real provider group, three things would
have to change before anyone acted on it:

1. **`Pending` would need a real meaning.** Here 23% of claims never resolve, in every
   month of the file. A real extract would carry a resolution date or a write-off, and
   the ageing would become a collections story instead of an arithmetic one.
2. **The denial lifecycle would need outcomes, not just states.** No denied claim in
   this file was ever paid, so appeal yield, overturn rate and recovery days cannot be
   computed. They are the four numbers a denials manager actually works to.
3. **The chargemaster would need to price the procedure.** The charge here is drawn
   independently of the CPT code, which rules out case mix, cost per procedure and
   service-line profitability.

Everything the report *does* say — the composition of the money, the timeliness of the
cycle, the denial workload profile, the shape of the receivable, and the fact that
nothing but the payer predicts a denial — holds on the data as it is.
