# AICTE Integrated Institution Complaint Monitoring Dashboard

A runnable prototype with a responsive dashboard, Flask API, SQLite database, action history, CSV export, and AI-assisted overlap candidate detection.

## Included
- Institution directory with AICTE Permanent IDs and consolidated case counts
- Case search/filtering, status changes, officer/bureau assignment, and action history
- Dashboard KPIs, workload breakdown, due-date/overdue indicators
- Cross-bureau overlap candidates using exact institution matching plus TF-IDF/cosine similarity
- Case creation, institution creation, institution history, reports, and CSV export
- Demo records for local evaluation

## Run on Windows
1. Install Python 3.10+ from https://www.python.org/downloads/ (enable **Add Python to PATH**).
2. Extract the ZIP to a folder you can edit.
3. Double-click `run_windows.bat`. The first run installs dependencies and creates the SQLite database.
4. Open http://127.0.0.1:5000 in your browser.

Or run manually from this folder:
```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The database `aicte_cases.db` is created automatically and demo data is seeded only when the institution table is empty.

## API overview
- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/cases` (supports `q`, `status`, `bureau`, `region`, `category`, `from_date`, `to_date`)
- `POST /api/cases`
- `GET /api/cases/<case_id>`
- `PATCH /api/cases/<case_id>`
- `GET /api/institutions`, `POST /api/institutions`, `GET /api/institutions/<permanent_id>`
- `GET /api/overlaps`
- `GET /api/reports`
- `GET /api/export.csv`

## Important production notes
This is a prototype, not an official AICTE deployment. It uses sample data, has no production identity provider or role-based access controls, and does not send email/SMS notifications. Before using real complaints, add SSO/MFA, role/region permissions, CSRF and rate limiting, encrypted document storage, audit-log protections, backup/restore, retention policies, security testing, and approved notification integrations. AI overlap results are *candidates for human review*, not findings or legal/regulatory conclusions. Validate the model against authorized historical data before operational use.
