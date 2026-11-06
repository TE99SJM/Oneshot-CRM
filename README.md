# Oneshot CRM (FunnelHub)

A self-hosted CRM for managing **social media channels, sales channels, sales funnels, contacts, deals, content and follow-ups** in one place.

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy 2 · SQLite by default (PostgreSQL optional) · JWT login
- **Frontend:** React 18 · TypeScript · Vite · Zustand (state) · React Router
- **Deploy:** one Docker container (API + built UI) with a persistent `/data` volume

## Features

| Area | What you can do |
|---|---|
| Dashboard | Won revenue (30 days / all time), open & weighted pipeline, win rate, audience size, 30-day views and engagement, revenue and leads by channel, 6-month revenue chart, funnel stage counts, upcoming posts, open follow-ups |
| Pipeline | Multiple funnels with custom stages (probability %, open/won/lost); drag-and-drop deal board; dropping a deal in a Won/Lost stage closes it automatically |
| Contacts | Leads → prospects → customers, source-channel attribution, tags, search/filters, activity timeline (notes, calls, emails, DMs, meetings, tasks), CSV import/export |
| Content | Monthly content calendar + list view, idea bank, post status (idea/draft/scheduled/published), per-post metrics (views, likes, comments, shares, clicks) |
| Channels | Social accounts, stores, marketplaces, email lists, ads, referrals, with followers, monthly cost, and computed leads / open deals / won revenue / views |
| Tasks | Follow-up list with due dates, overdue highlighting, linked contacts |
| Settings | Change password, load demo data, import/export contacts, link to API docs |

## File tree

```
funnelhub-crm/
├── README.md
├── .env.example              # all settings, documented
├── Dockerfile                # multi-stage: build UI, then Python API serving it
├── docker-compose.yml
├── setup.bat / setup.sh      # one-time install
├── dev.bat   / dev.sh        # dev mode: API :8000 (auto-reload) + UI :5173 (hot reload)
├── start.bat / start.sh      # single server on :8000 (builds UI first)
├── test.bat  / test.sh       # backend tests + frontend type check
├── backend/
│   ├── requirements.txt      # runtime deps
│   ├── requirements-dev.txt  # + pytest, httpx
│   ├── app/
│   │   ├── main.py           # FastAPI app, CORS, router registration, serves frontend/dist
│   │   ├── config.py         # env settings, auto-generated secret key
│   │   ├── database.py       # engine, session, get_db dependency, init_db
│   │   ├── models.py         # User, Channel, Contact, Funnel, FunnelStage, Deal, Post, Activity
│   │   ├── schemas.py        # Pydantic request/response models + validation
│   │   ├── security.py       # PBKDF2 password hashing, JWT tokens
│   │   ├── deps.py           # current_user auth guard, 404/422 helpers
│   │   ├── seed.py           # demo data (python -m app.seed)
│   │   └── routers/
│   │       ├── auth.py       # status, first-run setup, login, me, change password
│   │       ├── dashboard.py  # aggregated KPIs
│   │       ├── channels.py   # CRUD + computed stats
│   │       ├── contacts.py   # CRUD, filters, CSV import/export, related deals & activities
│   │       ├── funnels.py    # CRUD + ordered stage editing
│   │       ├── deals.py      # CRUD + stage moves (auto won/lost/closed_at)
│   │       ├── posts.py      # content calendar CRUD
│   │       ├── activities.py # notes / tasks
│   │       └── system.py     # health check, demo seed
│   └── tests/                # pytest API tests (isolated temp database)
└── frontend/
    ├── package.json, vite.config.ts, tsconfig.json, index.html
    └── src/
        ├── main.tsx, App.tsx # router + auth gate
        ├── api/client.ts     # fetch wrapper (token, errors, upload, download)
        ├── store/            # Zustand: authStore, crmStore, toastStore
        ├── components/       # Layout (sidebar), ui (Modal, Drawer, Field, Stat, BarList, Toasts…)
        ├── pages/            # Dashboard, Pipeline, Contacts, Content, Channels, Tasks, Settings, Login
        ├── types.ts, format.ts, styles.css
```

## Install and run locally

### Prerequisites

- **Python 3.11 or newer** — on Windows, tick "Add python.exe to PATH" in the installer. Check: `python --version`
- **Node.js 20 LTS or newer** (includes npm). Check: `node --version`

### Windows (double-click)

1. Extract the zip, e.g. to `C:\funnelhub-crm`.
2. Double-click **`setup.bat`** (creates `backend\.venv`, installs Python and npm packages, copies `.env.example` → `.env`).
3. Double-click **`dev.bat`**. Two terminal windows open (API and UI) and your browser opens **http://localhost:5173**.
4. First visit shows **Create your owner account** — enter an email and a password (8+ characters).
5. Optional: **Settings → Load demo data** fills the CRM with sample channels, contacts, two funnels, deals, posts and tasks.
6. To stop, close the two terminal windows.

### macOS / Linux

```bash
cd funnelhub-crm
./setup.sh
./dev.sh          # UI: http://localhost:5173   API: http://localhost:8000
```

### Manual steps (any OS)

```bash
# Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev       # open http://localhost:5173
```

The Vite dev server proxies `/api` and `/docs` to the backend, so no CORS setup is needed.

### Single-server mode (what production looks like)

Run **`start.bat`** (or `./start.sh`). It builds the frontend into `frontend/dist` and FastAPI serves both the UI and the API at **http://localhost:8000**.

### Run the tests

`test.bat` / `./test.sh`, or manually:

```bash
cd backend && python -m pytest -q        # 6 API tests on a throwaway database
cd frontend && npm run typecheck
```

## Deploy with Docker

```bash
cp .env.example .env          # set SECRET_KEY, ALLOW_DEMO_SEED=false, CRM_BIND=<tailscale ip>
docker compose up -d --build
docker compose logs -f crm    # then open http://<CRM_BIND>:8000
```

- Data lives in the named volume `crm-data` (`/data` in the container): the SQLite database and the generated secret key. Back it up with
  `docker run --rm -v funnelhub-crm_crm-data:/data -v "$PWD":/backup alpine tar czf /backup/crm-data.tgz -C /data .`
- Upgrade: replace the source files (keep `.env`), then `docker compose up -d --build`. The volume is untouched.
- The `env_file … required: false` syntax needs Docker Compose v2.24+. On older versions, change it to `env_file: .env` and make sure `.env` exists.
- Put it behind HTTPS (Caddy, Nginx Proxy Manager, Cloudflare Tunnel, Tailscale) before exposing it to the internet. The API requires login for everything except `/api/health` and `/api/auth/status|setup|login`; `/api/auth/setup` only works while no account exists.

## Configuration

All variables are optional; see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite in `DATA_DIR` | e.g. `postgresql+psycopg://user:pass@host/db` (uncomment `psycopg` in requirements.txt) |
| `DATA_DIR` | `backend/data` | SQLite file + generated secret key |
| `SECRET_KEY` | generated & saved | JWT signing key; changing it signs everyone out |
| `TOKEN_MINUTES` | `10080` (7 days) | Login lifetime |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated origins allowed to call the API directly |
| `ALLOW_DEMO_SEED` | `true` | Enables Settings → Load demo data (only works on an empty CRM) |

Tables are created automatically on startup. Schema changes in future versions would need a migration tool such as Alembic; this prototype uses `create_all`.

## REST API

Interactive docs: **http://localhost:8000/docs** (Swagger UI). All endpoints except auth/health need `Authorization: Bearer <token>`.

| Method & path | Description |
|---|---|
| `GET /api/health` | Health + database check |
| `GET /api/auth/status` | `{needs_setup, app_name}` |
| `POST /api/auth/setup` | Create the first account (only when none exist) → token |
| `POST /api/auth/login` | `{email, password}` → token |
| `GET /api/auth/me` · `POST /api/auth/password` | Current user · change password |
| `GET /api/dashboard` | KPIs, channel breakdown, funnels, monthly revenue, upcoming posts, open tasks |
| `GET/POST /api/channels` · `GET/PATCH/DELETE /api/channels/{id}` | Channels (list includes computed stats) |
| `GET /api/contacts?q=&status=&channel_id=&tag=&limit=&offset=` | Search/filter, returns `{items, total}` |
| `POST /api/contacts` · `GET/PATCH/DELETE /api/contacts/{id}` | Contact CRUD |
| `GET /api/contacts/{id}/deals` · `/activities` | Related records |
| `GET /api/contacts/export.csv` · `POST /api/contacts/import` | CSV export / import (multipart `file`) |
| `GET/POST /api/funnels` · `GET/PUT/DELETE /api/funnels/{id}` | Funnels; PUT with `stages` reorders/renames/adds/removes stages |
| `GET /api/deals?funnel_id=&status=&contact_id=&channel_id=` · `POST /api/deals` | Deals |
| `GET/PATCH/DELETE /api/deals/{id}` | PATCH `{stage_id}` moves a deal; won/lost stages set `status` and `closed_at` |
| `GET /api/posts?channel_id=&status=&start=&end=` · `POST /api/posts` · `GET/PATCH/DELETE /api/posts/{id}` | Content calendar |
| `GET /api/activities?contact_id=&deal_id=&kind=&open_tasks=` · `POST` · `PATCH/DELETE /{id}` | Notes and tasks |
| `POST /api/demo/seed` | Load demo data into an empty CRM |

Example with curl:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpassword"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s localhost:8000/api/dashboard -H "Authorization: Bearer $TOKEN"
```

## Troubleshooting

- **"Can't reach the API"** in the browser: the backend isn't running on port 8000. Check the API terminal window for errors.
- **`python` not found on Windows**: reinstall Python with "Add to PATH", or use `py` instead of `python` in `setup.bat`.
- **Port already in use**: change `--port 8000` in the scripts (and `VITE_API_TARGET=http://127.0.0.1:<port>` for `npm run dev`).
- **Forgot the password**: stop the app and delete `backend/data/funnelhub.db` (this erases all data), or reset it in the database.
- **Start over with a clean CRM**: stop the app and delete the `backend/data` folder.

## Not included yet (natural next steps)

- Direct posting / metric sync with YouTube, Facebook, Rumble, TikTok APIs (metrics are entered manually today)
- Multiple users with roles, email sending, file attachments, Alembic migrations
