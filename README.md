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
| Compose | Write one post and send it to your Facebook Page, Instagram and YouTube at once, now or scheduled; photos, carousels, videos, Reels; per-platform results with links, retry and cancel |
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
│   │   ├── migrate.py        # adds new columns to older databases on startup
│   │   ├── integrations/     # youtube.py, facebook.py, square.py, rumble.py, service.py, scheduler.py
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

## Orders

The **Orders** tab opens on the last 30 days (pick Last 7/90 days, This year, All time or custom dates to change it) and lists every Square and eBay order (filter by store) with totals for gross sales, refunds, net sales and Square fees. You can search and filter by status, fulfillment type and date, and export to CSV. Click an order to see everything: line items with variations, modifiers and discounts; taxes, service charges and tips; the customer; shipping or pickup recipient, address, carrier and tracking; card brand/last 4, entry method, fees and receipt; refunds and returns; notes; and the complete raw data the store returned. eBay orders also show the buyer's eBay username, ship-to address, tracking numbers (with carrier links), eBay fees, sales tax eBay collected, and what eBay says is due to you.

The **Pipeline** also opens on the last 30 days: it shows deals created or closed (won/lost) in the selected range. Pick **All time** to see everything.

## Posting (Compose)

The **Compose** tab sends one post to any mix of your **Facebook Page**, **Instagram** and **YouTube** connections.

1. Write the text, optionally add a link and attach photos or one video (drag and drop works).
2. Tick where it should go. Accounts that need one more setup step are greyed out with a "Fix" link.
3. Pick **Post now** or **Schedule** (your local time), then click the button.
4. The **Posts sent from here** list shows each platform's result with an **Open ↗** link, any error, and **Retry failed**. Scheduled posts can be changed, posted early or cancelled. Every post also appears on the **Content** calendar, and later syncs keep its views and likes up to date.

What each platform takes:

| Platform | Accepts | Notes |
|---|---|---|
| Facebook Page | Text, link, 1–20 photos, or one video | Tick "Post the video as a Reel" for vertical clips (3–90 s) |
| Instagram | 1 photo, a carousel of up to 20 photos, or one video (posted as a Reel) | Needs at least one photo or video. Captions max 2,200 characters; links aren't clickable |
| YouTube | Exactly one video | Title (max 100), visibility, "made for kids" answer, tags. Vertical videos under 3 min become Shorts |

### Permissions to add (one time)

- **Facebook:** make a new Page token like in the Facebook steps but also tick **pages_manage_posts**. Paste it with **Edit** on the Facebook connection.
- **Instagram:** the same token also needs **instagram_content_publish** and **pages_manage_posts**. Paste it with **Edit** on the Instagram connection.
- **YouTube:** click **Set up posting** on the YouTube connection and follow the three steps. You make a free Google sign-in app (OAuth client, type **Desktop app**), paste its ID and secret, then sign in. Google warns "hasn't verified this app": that's normal for your own app (Advanced → Go to …). At the end the browser opens a `127.0.0.1` page that won't load; copy its address bar into the CRM. On the **Audience** page click **Publish app** so the sign-in doesn't expire every 7 days.

### Good to know

- Scheduled posts go out within about 30 seconds of their time, **as long as the CRM is running**. If the server is off, they go out as soon as it starts again.
- Photos and videos are uploaded to the server first (`data/media`). They're deleted automatically 14 days after posting.
- For Instagram photos, the CRM stores them as hidden Facebook Page photos so Instagram can fetch them, then deletes those copies. Nothing extra to set up.
- Instagram videos upload directly. If Instagram ever refuses that for your app, put your public Tailscale address (for example `https://mserver.your-tailnet.ts.net`) in **Public media address** on the Instagram connection and share only the media folder:
  `sudo tailscale funnel --bg --set-path=/api/media/public http://127.0.0.1:3050/api/media/public`
  If eBay's Funnel address is already saved, the CRM uses that host automatically.
- If the server restarts in the middle of posting, that item is marked failed with a note. Check the platform before you click Retry so it isn't posted twice.

## Importing channels

Channels → **Import CSV** reads the columns `Name, Type, Platform, Handle, URL, Followers / subscribers, Monthly cost (USD), Active, Notes` (comma- or tab-separated; Excel/Google Sheets "Download as CSV" works). Type can be the on-screen label ("Website / store") or the short name. A row whose Name matches an existing channel updates it, and blank cells keep what's already there. **Export / template** downloads the same layout.

## Integrations (YouTube, Facebook Page, Instagram, Square, eBay, Gmail, Rumble, Twitch)

Open **Integrations** in the sidebar, click **Connect** on a platform, follow the built-in steps, and paste
the requested key. The first sync runs right away; after that the CRM syncs on its own schedule
(every 6 hours by default, adjustable per connection). Use **Test** to check credentials and **Sync now** to refresh.

| Platform | What you paste | What syncs |
|---|---|---|
| YouTube | Channel @handle + Google Cloud API key (YouTube Data API v3) | Subscribers, recent uploads with views/likes/comments → Content |
| Facebook Page | Page ID + long-lived Page access token (Graph API v27.0) | Followers, recent posts with reactions/comments/shares; views if the token has `read_insights` |
| Instagram | Facebook Page ID + the same Page token with `instagram_basic` (account must be Business/Creator and linked to the Page) | Followers, recent posts/reels with likes/comments |
| Square | Production access token | Every order (open, completed, canceled) with full details → **Orders** tab; customers and online buyers → Contacts; orders → deals in an auto-created "Square Sales" funnel (refunds subtracted) |
| eBay | App ID + Cert ID + RuName from developer.ebay.com, then a one-time "Sign in with eBay" (see below) | Every sold order (up to 2 years) with buyer, items, shipping address, tracking, eBay fees and refunds → **Orders** tab; buyers → Contacts; orders → deals in an "eBay Sales" funnel (Needs shipping / Shipped / Refunded) |
| Gmail | Gmail address + Google app password (myaccount.google.com/apppasswords, needs 2-Step Verification) | Sent and received mail → **Emails** tab and each contact's page; optionally people you email become contacts. Read-only. |
| Rumble | Live Stream API URL (rumble.com/account/livestream-api) and/or channel page URL | Followers, subscribers, live streams. Rumble has no public per-video stats API. |
| Twitch | Channel name + Client ID/Secret from dev.twitch.tv/console | Follower total, live viewers, videos with views |

### Connecting Gmail

1. Make sure 2-Step Verification is on at [myaccount.google.com/security](https://myaccount.google.com/security).
2. Open [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), name it "Oneshot CRM", click Create, and copy the 16 letters.
3. In the CRM: **Integrations → Connect Gmail**, enter your Gmail address and the app password, then click **Connect & sync**.

Options: **Which mail** = `primary` (Primary inbox tab + Sent, the default) or `all`. **New contacts from email** = `emailed` (people you've sent mail to become contacts, the default), `all` (also people who email you; newsletters and no-reply senders are skipped), or `none`. The first sync reads the last 90 days, up to 1,500 messages per sync, and later syncs read only new mail.

The CRM reads mail over IMAP and never sends, deletes or marks anything. Images inside emails are blocked until you click **Load images**, so senders can't tell you opened a message, and attachments stay in Gmail. To cut off access, delete the app password in your Google account.

Why not "Sign in with Google"? Google treats Gmail reading as a restricted permission. For a personal, unverified Google Cloud app, that sign-in expires every 7 days, while an app password keeps working until you revoke it.

### Connecting eBay

eBay takes a few more steps than the others, but you only do them once (the sign-in lasts 18 months, and the CRM shows the expiry date).

1. On [developer.ebay.com](https://developer.ebay.com) sign in with your seller account → **Hi &lt;name&gt; → Application Keys** → create a **Production** keyset.
2. In the CRM: **Integrations → Connect eBay**, paste the **App ID** and **Cert ID**, and click Save. The **eBay setup** window opens.
3. **Part 1, account-deletion notices.** eBay keeps new keys switched off until you give it a public https address for "a buyer closed their account" notices. The CRM handles those notices itself (it deletes that buyer's orders, deal and contact); it just needs to be reachable. On the server, run this once to make **only** the CRM's `/api/ebay` path public through Tailscale Funnel:

   ```bash
   sudo tailscale funnel --bg --set-path=/api/ebay http://127.0.0.1:3050/api/ebay
   tailscale funnel status
   ```

   If it prints a link to enable Funnel or HTTPS, open it, click Enable, and run the command again. `funnel status` shows your address, something like `https://mserver.tail1234.ts.net`. Your endpoint URL is that address plus `/api/ebay/account-deletion`. Paste it into the CRM (Save), then click **Check**: it should say the endpoint is reachable. On eBay, open **Alerts & Notifications** (or the "Your keyset is disabled" link), choose Marketplace account deletion, enter your email, paste the same endpoint URL and the **verification token** shown in the CRM, and click Save. eBay checks it right away, and your keys switch on.
   - Only `/api/ebay/...` is public. The rest of the CRM stays on your network/tailnet. To turn it off later: `sudo tailscale funnel --https=443 --set-path=/api/ebay off`.
4. **Part 2, RuName.** On eBay: **User Tokens** (next to the Production keyset) → "Get a Token from eBay via Your Application" → **Add eBay Redirect URL**. Fill in a privacy policy URL (your website works), tick **OAuth**, and Save. Copy the **RuName** into the CRM.
   - Optional: set "Your auth accepted URL" to `https://<your funnel address>/api/ebay/oauth/callback`. The sign-in then finishes by itself, and you can skip the pasting in Part 3.
5. **Part 3, sign in.** Click **Open eBay sign-in**, sign in, and click **Agree**. Copy the whole address of the "thank you" page eBay shows, paste it into the box, and click **Finish sign-in** (within 5 minutes). The first sync pulls the last 365 days of orders (you can set up to 730).

On the Channels page, cards for these platforms show **Pull live data**, which opens the connect form already pointed at that channel.

Notes:
- Tokens are encrypted in the database with a key derived from `SECRET_KEY`. If you change `SECRET_KEY`, re-enter tokens.
- Disconnecting keeps everything already synced. Synced items show a "Synced" badge; their stats are overwritten on each sync.
- The server needs outbound internet access. Set `SYNC_SCHEDULER=false` to disable background syncing.
- Database upgrades are automatic: new columns are added to an existing database at startup.

## Configuration

All variables are optional; see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite in `DATA_DIR` | e.g. `postgresql+psycopg://user:pass@host/db` (uncomment `psycopg` in requirements.txt) |
| `DATA_DIR` | `backend/data` | SQLite file + generated secret key |
| `SECRET_KEY` | generated & saved | JWT signing key + integration token encryption; changing it signs everyone out and requires re-entering integration tokens |
| `TOKEN_MINUTES` | `10080` (7 days) | Login lifetime |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated origins allowed to call the API directly |
| `ALLOW_DEMO_SEED` | `true` | Enables Settings → Load demo data (only works on an empty CRM) |
| `SYNC_SCHEDULER` | `true` | Background sync of connected integrations |

Tables are created automatically on startup, and new columns from upgrades are added automatically (`backend/app/migrate.py`).

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
| `GET /api/publish/targets` | Accounts you can post to, with readiness |
| `POST /api/publish/media` | Upload photos/videos (multipart `files`) |
| `POST /api/publish` · `GET /api/publish` · `GET/PATCH/DELETE /api/publish/{id}` | Create (now or `scheduled_at`), list, edit or remove posts |
| `POST /api/publish/{id}/post-now` · `/retry` · `/cancel` | Post a scheduled item early, retry failed platforms, cancel |
| `GET /api/integrations/{id}/youtube/authorize` · `POST …/youtube/connect` · `POST …/youtube/disconnect` | YouTube posting sign-in |
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

- Posting to X, TikTok or Truth Social
- Multiple users with roles, email sending, file attachments, Alembic migrations
