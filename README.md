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
