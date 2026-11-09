# Oneshot CRM (FunnelHub)

A self-hosted CRM for managing **social media channels, sales channels, sales funnels, contacts, deals, content and follow-ups** in one place.

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy 2 · SQLite by default (PostgreSQL optional) · JWT login
- **Frontend:** React 18 · TypeScript · Vite · Zustand (state) · React Router
- **Deploy:** one Docker container (API + built UI) with a persistent `/data` volume

## Features

| Area | What you can do |
|---|---|
| Dashboard | Period picker (last 30 / 60 / 90 days, year to date, a full calendar year, or all time — remembered between visits) with a banner saying exactly which dates you're looking at. Won revenue, open & weighted pipeline, win rate, contacts, audience and views; click any of them for a full-screen chart over time with a trendline. Revenue and leads by channel, revenue chart, funnel stage counts, upcoming posts, open follow-ups |
| Pipeline | Multiple funnels with custom stages (probability %, open/won/lost); drag-and-drop deal board; dropping a deal in a Won/Lost stage closes it automatically |
| Contacts | Leads → prospects → customers, source-channel attribution, tags, search/filters, activity timeline (notes, calls, emails, DMs, meetings, tasks), CSV import/export |
| Content | Monthly content calendar + list view, idea bank, post status (idea/draft/scheduled/published), per-post metrics (views, likes, comments, shares, clicks) |
| Compose | Write one post and send it to your Facebook Page, Instagram, TikTok and YouTube at once, now or scheduled; photos, carousels, videos, Reels; per-platform results with links, retry and cancel |
| Channels | Social accounts, stores, marketplaces, email lists, ads, referrals, with followers, monthly cost, and computed leads / open deals / won revenue / views |
| Messages | TikTok Shop buyer chats checked every 5 minutes (unread count on the menu), with replies sent back to the buyer from the CRM |
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

## Use it on your phone (works like an app)

On a phone the CRM switches to an app layout: a title bar at the top, a tab bar at the bottom
(**Home, Orders, Messages, Post, More**), big bold text, large touch buttons and drop-downs, tables shown as
cards, and pop-ups that open full screen. **More** lists every other page. Messages works like a texting app:
tap a chat to open it full screen, then tap **‹ Chats** to go back.

To put it on your home screen with its own icon:

1. Install the **Tailscale** app on the phone and sign in with the same account as the server.
2. Open the CRM address in the phone's browser, e.g. `http://100.121.179.33:3050`, and sign in.
3. **iPhone (Safari):** tap Share (square with an arrow) → **Add to Home Screen** → Add.
   **Android (Chrome):** tap ⋮ → **Add to Home screen** (or **Install app**) → Install.
4. Open it from the new **FunnelHub** icon. On iPhone it opens full screen with no browser bars. Sign in once inside the app.

Optional, for full-screen mode on Android too: Android only opens home-screen apps full screen from an `https://`
address. Tailscale can give you one that only your own devices can reach (it doesn't touch the public Funnel):

```bash
sudo tailscale serve --bg --https=8443 http://127.0.0.1:3050
```

Then use `https://<your-server>.<tailnet>.ts.net:8443` (run `tailscale serve status` to see the exact address)
in step 2. Turn it off with `sudo tailscale serve --https=8443 off`.

## Orders

The **Orders** tab opens on the last 30 days (pick Last 7/90 days, This year, All time or custom dates to change it) and lists every Square, eBay and TikTok Shop order (filter by store) with totals for gross sales, refunds, net sales and Square fees. You can search and filter by status, fulfillment type and date, and export to CSV. Click an order to see everything: line items with variations, modifiers and discounts; taxes, service charges and tips; the customer; shipping or pickup recipient, address, carrier and tracking; card brand/last 4, entry method, fees and receipt; refunds and returns; notes; and the complete raw data the store returned. eBay orders also show the buyer's eBay username, ship-to address, tracking numbers (with carrier links), eBay fees, sales tax eBay collected, and what eBay says is due to you. TikTok Shop orders show items, buyer, payment, ship-to address and tracking, and seller-shipped orders have a **Mark as shipped** form (pick the carrier, type the tracking number) that sends it to TikTok Shop.

The **Pipeline** also opens on the last 30 days: it shows deals created or closed (won/lost) in the selected range. Pick **All time** to see everything.

## Order alerts to your phone

**Settings → Order alerts to my phone.** When a sync finds a new Square, eBay or TikTok Shop order, the CRM alerts you. Sales sync every 15 minutes, so alerts arrive within about 15 minutes of the sale. Turn on any mix of:

| Way | Cost / setup | Notes |
|---|---|---|
| **Phone push (ntfy)**, recommended | Free, no account, no API key | Install the free **ntfy** app ([iPhone](https://apps.apple.com/us/app/ntfy/id1625396347), [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)), tap **+**, type the topic name shown in Settings, then **Send test push**. Tapping the alert opens Orders. |
| **Real SMS (Twilio)** | Paid Twilio account, toll-free number, free toll-free verification (about 3-5 business days) | US carriers block texts from unverified numbers (Twilio error 30032). Enter Account SID, Auth Token, your Twilio number and your phone. |
| **Text through email (Gmail)** | Free; Gmail + app password (or reuses your Gmail connection) | Carrier email-to-text: AT&T/Cricket shut down Jun 2025, T-Mobile late 2024. Verizon (`vtext.com`) still delivers, though not always, until 31 Mar 2027. Google Fi and US Cellular still work. Or send to any email. |

Rules: the first sync of a new store connection (the history import) never alerts. Orders older than 3 days, and canceled or draft orders, don't alert. More than 3 new orders at once sends one summary. You can set a minimum order total and choose which stores alert. **Recent alerts** shows what was sent and any error. Logs: `docker logs funnelhub-crm 2>&1 | grep alerts`.

The ntfy topic name works like a password, so keep it private. To use your own ntfy server, change it under "Show advanced push settings".

## Channel data (pick what you see)

Every sync saves **all the numbers each platform's API gives**, and the CRM also works out numbers from what it
has synced (posts, orders, contacts, deals, emails). On **Channels**, each card has **Choose data**: tick the
numbers you want on that card (Select all / None / Reset to defaults, search box, grouped by section). Each number
shows its time window (right now, last 28 days, last 30 days, the period you picked...) and whether it came from the
platform or from the CRM. Followers and other "right now" numbers show how much they changed in the picked period
once the CRM has a daily history from before it.

The **Dashboard → Combined by type** section adds up the ticked numbers across channels of the same **type**:
Social media (type Social), Sales channels (Marketplace, Website / store, Direct), Email, Paid ads and Other.
Change a channel's type with its Edit form. Click a tile to see the per-channel breakdown. Rates and averages are
averaged instead of added.

| Platform | What's pulled (besides posts / orders the CRM already reads) |
|---|---|
| YouTube | subscribers, lifetime views, video count; **YouTube Analytics (last 28 days)**: views, minutes watched, average view duration and %, subscribers gained/lost, likes, dislikes, comments, shares, playlist adds; lifetime watch hours; revenue, CPM and ad impressions if the channel is monetized |
| Facebook Page | followers, likes, people talking about it, check-ins, reviews, star rating; Page Insights (28 days): content views, viewers, impressions, engagements, Page-action clicks, profile views, video views, follows/unfollows, reactions |
| Instagram | followers, following, posts; insights (28 days): views, reach, accounts engaged, interactions, likes, comments, shares, saves, replies, reposts, link taps, follows |
| TikTok | followers, following, total likes received, public video count |
| Twitch | followers, live now / viewers / minutes live, saved videos and their views and hours, clips and clip views |
| Rumble | followers, paid subscribers, live streams now, live viewers, live likes/dislikes, recent rants |
| Square | customers in the directory, locations, catalog items and variations |
| eBay | active / sold / unsold listings; **traffic (30 days)**: impressions (total / search / store), listing views by source, transactions, click-through and conversion rate |
| TikTok Shop | products, products live |
| Google Analytics | visitors, visits, page views, new / active visitors, engaged visits, engagement and bounce rate, average visit length, pages per visit, events, key events, purchases, revenue, add-to-carts, checkouts |
| Every channel (CRM) | posts, views, likes, comments, shares, engagement rate, orders, gross / net sales, refunds, fees, tax, tips, discounts, average order, items sold, buyers, repeat buyers, canceled / open orders, leads, won revenue, open pipeline, emails in/out/unread |

**One-time re-sign-ins to unlock the new numbers**

- **YouTube Analytics:** Integrations → YouTube → **Set up posting** again (adds the two read-only analytics permissions). Without it you still get subscribers / views / videos.
- **eBay traffic:** Integrations → eBay → **Sign in with eBay** again (adds `sell.analytics.readonly`). Orders keep syncing either way.
- **Facebook Page Insights** need a Page token with `read_insights`; **Instagram insights** need `instagram_manage_insights`. Missing permissions only show a warning on the sync; everything else still syncs.

Platforms retire metrics now and then; anything a platform stops returning is simply skipped.

## Dashboard charts

- **Pick the period** at the top right of the Dashboard: Last 30 days (default), Last 60 days, Last 90 days, Year to date, Full year (choose the year), or All time. The banner under the title always says which dates are shown. "Open pipeline" and "Audience" are always the number right now, and their cards say so.
- **Click any of the six numbers** to open it full screen: time across the bottom, the number up the side, and a dashed straight-line trendline (least-squares fit). Hover to see each day/week/month. You can change the period, group by day/week/month, switch revenue and views to a running total, and turn the trendline off. Press Esc or × to close.
- **Where the history comes from:** revenue, win rate, contacts and pipeline are rebuilt from your deals and contacts. Views use each post's current view count on the day it was published. **Audience has no history from the platforms**, so the CRM now saves one reading per day; that chart starts on the day you install this update and fills in over time.

## Posting (Compose)

The **Compose** tab sends one post to any mix of your **Facebook Page**, **Instagram**, **TikTok** and **YouTube** connections.

1. Write the text, optionally add a link and attach photos or one video (drag and drop works).
2. Tick where it should go. Accounts that need one more setup step are greyed out with a "Fix" link.
3. Pick **Post now** or **Schedule** (your local time), then click the button.
4. The **Posts sent from here** list shows each platform's result with an **Open ↗** link, any error, and **Retry failed**. Scheduled posts can be changed, posted early or cancelled. Every post also appears on the **Content** calendar, and later syncs keep its views and likes up to date.

What each platform takes:

| Platform | Accepts | Notes |
|---|---|---|
| Facebook Page | Text, link, 1–20 photos, or one video | Tick "Post the video as a Reel" for vertical clips (3–90 s) |
| Instagram | 1 photo, a carousel of up to 20 photos, or one video (posted as a Reel) | Needs at least one photo or video. Captions max 2,200 characters; links aren't clickable |
| TikTok | One video, or up to 35 photos | You must pick who can view it and tick TikTok's Music Usage Confirmation every time (TikTok's rule). Comment/Duet/Stitch start off. "Send to TikTok drafts" puts it in your TikTok inbox to finish in the app. Photos need the public media address (below) verified in the TikTok developer portal |
| YouTube | Exactly one video | Title (max 100), visibility, "made for kids" answer, tags. Vertical videos under 3 min become Shorts |

### Permissions to add (one time)

- **Facebook:** make a new Page token like in the Facebook steps but also tick **pages_manage_posts**. Paste it with **Edit** on the Facebook connection.
- **Instagram:** the same token also needs **instagram_content_publish** and **pages_manage_posts**. Paste it with **Edit** on the Instagram connection.
- **YouTube:** click **Set up posting** on the YouTube connection. Step 1 asks how Google should send you back after you sign in:
  - **Automatic (recommended).** Google won't send sign-ins to an IP address like `100.121.179.33:3050` or `192.168.x.x`. It needs a named **https** address. Your Tailscale Funnel name works, and only the sign-in path is made public:
    ```bash
    sudo tailscale funnel --bg --set-path=/api/oauth http://127.0.0.1:3050/api/oauth
    tailscale funnel status          # copy the https://<server>.<tailnet>.ts.net address
    ```
    Paste that address into step 1 and click Save. The CRM shows your return address, `https://<server>.<tailnet>.ts.net/api/oauth/youtube/callback`. In Google Auth Platform → **Clients**, create a client of type **Web application** and add that exact address under **Authorized redirect URIs**. (A "Desktop app" client can't use it.) Paste the new client ID and secret, then click **Open Google sign-in**. After you approve, Google sends you straight back to the CRM at whatever address you normally use, and posting turns on by itself. To turn it off later: `sudo tailscale funnel --https=443 --set-path=/api/oauth off`.
  - **Copy and paste.** No server setup needed. Use a **Desktop app** client. At the end the browser opens a `127.0.0.1` page that won't load; copy its address bar into the CRM.
  - Either way: Google warns "hasn't verified this app". That's normal for your own app (Advanced → Go to …). On the **Audience** page click **Publish app** so the sign-in doesn't expire every 7 days.

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

## Integrations (YouTube, Facebook Page, Instagram, TikTok, Square, eBay, TikTok Shop, Gmail, Rumble, Twitch)

Open **Integrations** in the sidebar, click **Connect** on a platform, follow the built-in steps, and paste
the requested key. The first sync runs right away; after that the CRM syncs on its own schedule
(adjustable per connection with **Edit**). Use **Test** to check credentials and **Sync now** to refresh.

Default schedule:

| What | How often |
|---|---|
| Followers, subscribers, views (YouTube, Facebook, Instagram, TikTok, Rumble, Twitch, Google Analytics) | Every 6 hours |
| Sales (Square, eBay, TikTok Shop orders) and Gmail | Every 15 minutes |
| TikTok Shop buyer messages | Every 5 minutes |

Sales and stats run in two separate background lanes, so a slow stats sync never holds up sales and vice versa.
Each connection shows **next in …**, and the top of the Connections list says whether automatic sync is running.
Results are logged: `docker logs funnelhub-crm 2>&1 | grep auto-sync | tail -20`.

Note: YouTube's public numbers lag. Subscriber counts are rounded to 3 significant figures (1,523 shows as 1,520)
and the channel's lifetime view total can trail by a day or more. Per-video views update faster.

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
| Site visitors | GA4 property ID, website domain, service-account JSON key | Visitors, visits and page views per website → **Site Visitor** section on the existing Dashboard |

### Site Visitor dashboard section

Connect each website under **Dashboard → Site Visitor → Connect site**. Each connection gets its own card, so two sites stay separate even when they share a GA4 property. Counts follow the dashboard's selected date range and use each property's reporting time zone. Visitor totals come directly from GA4 for the whole period; daily unique counts and visitors across different sites are never added together.

The website must already have a working Google Analytics 4 tag. For Square Online, add the `G-` measurement ID under **Settings → Tracking Tools → Google Analytics**. The Square sales API does not supply these visitor totals.

For the CRM connection, enable **Google Analytics Data API** in Google Cloud, create a service account and download its JSON key. Grant that service account's email **Viewer** access in **Google Analytics → Admin → Property access management**. In the CRM, name the connection after the site, enter its domain and **numeric property ID**, then upload the JSON key. Repeat for the second website. The key is encrypted using the existing integration secret storage. An OAuth client JSON file or YouTube API key cannot be used for this connection.

Only the specified hostname and its `www` equivalent are included; other subdomains require their own connection. Website traffic stays separate from social Audience/Views and Square customers/orders. No new sidebar page is added.

Reports are cached in memory for 15 minutes (up to 64 reports); **Refresh** requests new totals. Failed requests show an error, or explicitly marked last-available data for the same site and dates. Paused connections do not fetch reports. Disconnecting removes the dashboard card. Recent data may still be processing in Google Analytics, and tracking begins when the Google tag is installed; connecting the CRM does not reconstruct untracked visits or identify anonymous visitors by name.

### Connecting TikTok (views, followers, posting)

1. Make sure the sign-in path is public (same command as YouTube; skip if done):
   `sudo tailscale funnel --bg --set-path=/api/oauth http://127.0.0.1:3050/api/oauth`
2. Go to [developers.tiktok.com](https://developers.tiktok.com/apps), log in with your TikTok account, **Manage apps → Connect an app**.
3. Add the products **Login Kit** and **Content Posting API** (turn on **Direct Post**). Add the scopes `user.info.basic`, `user.info.profile`, `user.info.stats`, `video.list`, `video.publish`, `video.upload`.
4. In the CRM: Integrations → **Connect TikTok**, paste the **Client key** and **Client secret**, save. The sign-in window opens: paste your `https://<server>.<tailnet>.ts.net` address, click **Save**, and copy the return address it shows (`…/api/oauth/tiktok/callback`) into Login Kit → **Redirect URI** in the TikTok app.
5. Add your own TikTok account as a test user (Sandbox → Target users) if the app isn't approved yet, then click **Sign in with TikTok**. You come straight back and the first sync runs.

What to expect before TikTok approves your app: sign-in only works for test users, and **posts made through the API can only be private ("Only me")**. TikTok also asks your account to be private for that. After TikTok's app review and Content Posting audit, Everyone/Friends/Followers unlock. Views, likes, comments, shares and followers sync either way.

### Connecting TikTok Shop (orders, buyer chats, shipping)

1. Go to [partner.tiktokshop.com](https://partner.tiktokshop.com/), sign up as a developer and create a **custom (in-house) app** linked to your seller account.
2. Add the API scopes: Order information, Product basic, Fulfillment basic, Logistics basic, **Customer service**, and Shop authorized information.
3. In the CRM: Integrations → **Connect TikTok Shop**, paste the **App key**, **App secret** and **Service ID**, pick the region, save. In the sign-in window save your `.ts.net` address and copy the return address (`…/api/oauth/tiktok-shop/callback`) into the app's **Redirect URL** in Partner Center.
4. Once TikTok approves the app, click **Sign in with TikTok Shop**, choose your shop, and approve. Orders, buyers, the **TikTok Shop Sales** funnel, product counts and buyer chats sync right away.

TikTok Shop buyer chats appear in **Messages**, checked every 5 minutes in the background (change **Check messages every (minutes)** on the connection; 0 = only with the regular 6-hour sync). The menu shows an unread count.

**Buyer messages need TikTok's approval of the Customer Service permission**, which can come later than orders. Until then, orders and products sync normally and the Messages page shows a yellow "waiting for TikTok to approve" box with the steps. The CRM re-checks once an hour. When TikTok approves it:

1. Integrations → TikTok Shop → **Sign in with TikTok Shop** again (TikTok only hands out new permissions on a fresh sign-in).
2. Chats appear in Messages within a minute. Or click **Check now** on the Messages page.

 Regular TikTok direct messages (DMs) are not included: TikTok only opens its Business Messaging API to verified business accounts after a data-security review, which a personal app can't realistically get.

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

Channel data: `GET /api/metrics/channels?start&end&tz_offset`, `GET /api/metrics/channels/{id}`,
`PUT /api/metrics/channels/{id}/display` (`{"keys": [...]}` or `{"reset": true}`), `GET /api/metrics/combined`.

Interactive docs: **http://localhost:8000/docs** (Swagger UI). All endpoints except auth/health need `Authorization: Bearer <token>`.

| Method & path | Description |
|---|---|
| `GET /api/health` | Health + database check |
| `GET /api/auth/status` | `{needs_setup, app_name}` |
| `POST /api/auth/setup` | Create the first account (only when none exist) → token |
| `POST /api/auth/login` | `{email, password}` → token |
| `GET /api/auth/me` · `POST /api/auth/password` | Current user · change password |
| `GET /api/oauth/youtube/callback` | Public (no login): Google's automatic return after YouTube sign-in. Protected by a one-time random `state` |
| `GET /api/dashboard?start=&end=&tz_offset=` | KPIs, channel breakdown and funnels for a period (local dates; omit both for all time), upcoming posts, open tasks |
| `GET /api/dashboard/series/{metric}?start=&end=&bucket=auto\|day\|week\|month&tz_offset=` | Time series behind the full-screen charts. Metrics: `won_revenue`, `open_pipeline`, `win_rate`, `contacts`, `new_contacts`, `audience`, `views` |
| `GET /api/dashboard/site-visitors` · `GET /api/dashboard/site-visitors/{integration_id}?start=&end=&refresh=false` | Website connections and GA4 totals for dashboard Site Visitor cards; authenticated, dates in the GA4 property's time zone |
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
| `GET /api/integrations/{id}/oauth` · `PUT …/oauth/redirect` · `GET …/oauth/authorize` · `POST …/oauth/connect` · `POST …/oauth/sign-out` | TikTok and TikTok Shop sign-in |
| `GET /api/oauth/tiktok/callback` · `GET /api/oauth/tiktok-shop/callback` | Public (no login): automatic return after TikTok / TikTok Shop sign-in, protected by a one-time `state` |
| `GET /api/publish/tiktok/{integration_id}/creator-info` | TikTok's live posting options for your account (visibility choices, max length) |
| `GET /api/messages?q=&unread_only=` · `GET /api/messages/{id}` | Buyer chats and their messages |
| `GET /api/messages/status` · `POST /api/messages/check` | Whether buyer chats are on for each TikTok Shop connection (active / waiting_approval / error / not_signed_in) · check right now |
| `POST /api/messages/{id}/reply` · `/refresh` · `/read` | Reply to a buyer, pull the full history, mark read |
| `GET /api/orders/{id}/shipping-providers` · `POST /api/orders/{id}/ship` | TikTok Shop carriers for an order · mark shipped `{tracking_number, shipping_provider_id}` |
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

- Posting to X or Truth Social; TikTok direct messages (needs TikTok's Business Messaging approval)
- Multiple users with roles, email sending, file attachments, Alembic migrations
