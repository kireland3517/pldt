# PLDT — Claude Cowork Rules

## Project
Pre-Listing Decision Tool. Python/Flask backend + React frontend.
Deployed on Railway (auto-deploys on push to `origin/main`).
Repo: github.com/kireland3517/pldt
Local clone: C:\Users\kirel\PLDT (Windows 11 — use `curl.exe` not `curl`)

Demo subject: 130 Kingfisher Dr, Simpsonville SC 29680

---

## Workflow — non-negotiable

- Claude (chat app) diagnoses and approves plans. Cowork implements.
- **Reply with a PLAN FIRST. Do not code or push until approved.**
- **NOTHING pushes without approval. Show the diff before pushing.**

---

## PRE-PUSH GATE — run EVERY push, on EVERY file in the diff, no exceptions

### Step 1 — AST parse each .py in the diff
```bash
python -c "import ast; ast.parse(open('path/to/file.py').read())"
```
Run this for every `.py` file changed. A string-grep is NOT verification.

### Step 2 — APP-LEVEL IMPORT (mandatory, never skip)
```bash
cd backend && python -c "import app.main"
```
Must succeed with no error. Single-file AST parse does NOT catch cross-file
ImportErrors. This gate is mandatory. Do not report "pass" unless you ran it.

### Step 3 — Frontend build (if any frontend file changed)
```bash
npm run build
```
Must exit 0.

**Do not report any gate as passing unless you actually executed the command
and observed the output. Grepping source is not verification.**

---

## Data-integrity rules — hard-won, do not relax

- Verify raw API JSON before coding. Never invent field names.
- No fabricated data. Missing values render blank/dash, never 0 or a guess.
- No empty columns: a column appears only if its source provides the data.
- RentCast list-price status vocab: `ok` / `no_data` (settled, never retried) /
  `fetch_failed` (429 or error, retried) / `not_fetched` (initial).
  A 429 is `fetch_failed`, never `no_data`. Empty array = `no_data`.
- Honesty/source labels live in the payload and must match the real source
  (RentCast is "aggregated public + listing data", NOT an MLS feed).
- Cache RentCast in the session blob; reloads cost zero calls. Free tier 50/mo.

---

## Data sources

| Source   | Provides                                                        |
|----------|-----------------------------------------------------------------|
| ATTOM    | sold price, sqft, beds, baths, year built, sold date, location, AVM. No list price, no DOM. |
| RentCast | 2nd AVM (`fetched_avms["rentcast"]`), active listings (list price, DOM, status), per-address sold-home list price via `/v1/listings/sale`. Auth header `X-Api-Key`. Key in Railway env `RENTCAST_API_KEY`. |

AVM divergence: average all `fetched_avms`, not one source.

---

## Known recurring hazard — CRLF normalization drops last line

Windows git with `autocrlf=true` has repeatedly stripped the last line of
files during normalization. After any commit that touches a file, verify the
last line is present in `git show HEAD:<file>`. This is how `TABLE` was lost
from `backend/app/db.py` (twice).

`TABLE = "pldt_sessions"` must always be the last line of `backend/app/db.py`.
Six route files import it: `sessions.py`, `capture.py`, `compute.py`,
`export.py`, `pdf_gen.py`, `pdf_gen_large.py`.

---

## Override engine (Stage 2 Step 1) — added 2026-06-30

Per-line cost override layer lives in:
  - backend/app/logic/net_proceeds.py  (compute_net_proceeds, net_for_plan)
  - backend/app/logic/optimizer.py     (build_plans — overrides_by_plan param)
  - backend/app/routes/compute.py      (PATCH /session/{id}/overrides)

Every line item now carries three numbers: calculated_amount (engine output,
NEVER overwritten), override_amount (user value or null), and amount (the
effective value actually used in net = override_amount if set, else
calculated_amount).

GLOBAL facts/rates — apply identically to all three plans:
  commission_rate, mortgage_payoff, seller_credits, other_seller_costs, has_hoa.
  Mechanism unchanged: session.commission_rate column + session.seller_inputs
  JSON, same as before this change. Now also surfaced as calculated_amount /
  override_amount on their line items.

PER-PLAN lines — independent per plan level:
  transfer_tax, attorney_fee, deed_fee, cl100, hoa_estoppel, repair_cost,
  concessions, carrying_cost.
  New mechanism: session.line_overrides_json column, keyed
  plan_level -> line_key -> amount (key absent or null = not overridden).
  Set/cleared via PATCH /session/{id}/overrides.

Calculated values are byte-identical to the pre-override engine at zero
overrides — proven in backend/tests/test_override_engine.py. Run that file
and confirm "ALL CHECKS MATCH" before any push that touches net_proceeds.py,
optimizer.py, or compute.py.

DB migration required once, outside git (Supabase has no migrations-in-repo
for this project): add jsonb column `line_overrides_json` to pldt_sessions,
default '{}'::jsonb. See SQL handed over alongside this change.

---

## Working agreement — sandbox git/file-write reliability (added 2026-06-30)

On 2026-06-30 the Cowork sandbox's Linux-side mount of this repo showed two
confirmed, independent failure modes:
  1. `.git/index` read as corrupt (bad sha1 signature) from the sandbox, even
     after `git status` was clean on the Windows clone.
  2. `backend/app/data_loader.py` read back 8 lines short / failed ast.parse
     from the sandbox's bash mount, while the same file read cleanly via the
     Windows-path file tool AND on the Windows clone directly (confirmed:
     ast.parse succeeded, tail matched, on the actual machine).
  3. A draft handoff of fix_claude_md.py / fix_override_engine.py was written
     to the sandbox's own scratch "outputs" folder, not the repo root — it
     never reached the Windows clone at all. The outputs folder is a
     different location from C:\Users\kirel\PLDT and is not synced to it.

Conclusion: the sandbox's bash-mounted view of this repo cannot be trusted as
a source of truth, and git operations must not run from that mount. Also,
"the file was written" is not proof it landed on the Windows clone unless it
was written via the Windows-path tool directly INTO the repo folder and then
read back via the same Windows-path tool to confirm.

Standing rule until further notice:
  - Cowork does NOT run git commands against this repo's bash mount, and does
    NOT use the bash-mounted view of this repo as a source of truth for reads.
  - Cowork drafts changes as a standalone Python writer script
    (`fix_<name>.py`), writes it directly into the repo root
    (C:\Users\kirel\PLDT) via the Windows-path file tool, and reads it back
    via the same tool to confirm the file exists and its last line is intact
    before telling Katie it's ready.
  - Katie runs the script from PowerShell on the Windows clone, verifies
    ast.parse and last-line integrity per changed file, then runs
    git diff / git add / git commit herself.
  - Nothing is pushed from the sandbox. Ever.
  - When verification needs to actually RUN the chain (not just parse it),
    Cowork rebuilds a throwaway copy of the needed files in its own sandbox
    scratch space (outside this repo) via the Windows-path file tool — never
    via cp/git against this repo's bash mount — runs the harness there, and
    reports the output back.
