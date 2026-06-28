# Pre-Listing Decision Tool

**Read START_HERE.md first.** Then read docs/ in the order it lists.

## Structure

```
reference/          general library (components_library.csv, questionnaire_bank.json, etc.)
seed/               front-door property inputs (address, public facts, constraints)
validation/         QUARANTINED — answer key for the blind test; running tool never reads this
docs/               spec set (Framework, UX/UI, Checklist, Technical Handoff)
backend/            FastAPI / Python
frontend/           React
```

## The blind rule
The running tool loads only `reference/` and `seed/`. It never reads `validation/`.
Condition enters only through capture (photos + questionnaire). See docs/PreListing_Tool_Technical_Handoff.md.

## Stack
React · FastAPI · Supabase · Railway

## Local dev

```bash
# backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm start
```

## Deploy
Push to GitHub. Railway auto-deploys on push. See docs/PreListing_Tool_Technical_Handoff.md for env vars.

### Railway monorepo setup
This repo has separate `backend/` and `frontend/` services.

**Backend service**
- Root Directory: `backend`
- Config file path: `/backend/railway.toml`
- Env vars: `SUPABASE_URL`, `SUPABASE_KEY`, `ATTOM_API_KEY` (optional)

**Frontend service**
- Root Directory: `frontend`
- Config file path: `/frontend/railway.toml`
- Env var: `VITE_API_URL` (set at build time)

If the backend Root Directory is left at `/`, the root `/railway.toml` uses `cd backend && uvicorn ...` as a fallback.
