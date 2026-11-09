"""Read-only GA4 website totals, kept separate from social followers and posts."""
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from datetime import date
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from ..models import utcnow
from .base import FieldSpec, ProviderInfo, SyncContext, SyncError

INFO = ProviderInfo(
    key="google_analytics", name="Site visitors (Google Analytics)", platform="google_analytics", channel_kind="website",
    summary="Website visitors, visits and page views, shown separately for each site on the dashboard.",
    syncs=["Site Visitor dashboard cards", "Visitors, visits and page views for the selected period", "Connect each website separately"],
    fields=[
        FieldSpec("hostname", "Website domain", placeholder="example.com",
                  help="Only this domain and its www version are counted. Connect your other site separately."),
        FieldSpec("property_id", "GA4 property ID", placeholder="123456789",
                  help="The numeric ID in Google Analytics → Admin → Property details. This is different from the G- tracking ID."),
        FieldSpec("service_account", "Service account JSON file", secret=True, kind="json_file",
                  help="Upload the downloaded service-account key. When editing, leave this blank to keep the saved key."),
    ],
    steps=[
        "Create a Google Analytics 4 property and install its Google tag on your website. In Square Online, use Settings → Tracking Tools → Google Analytics.",
        "In Google Cloud, enable Google Analytics Data API. Create a service account, then create and download a JSON key for it.",
        "In Google Analytics → Admin → Property access management, add the service account's email with the Viewer role.",
        "Give this connection your site's name, enter its domain and numeric GA4 property ID, and upload the JSON key. Repeat for your second site.",
    ],
    docs_url="https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart",
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
METRICS = {"totalUsers": "visitors", "sessions": "visits", "screenPageViews": "page_views"}
# Before GA4 properties existed; supports the dashboard's open-ended All time selection.
ALL_TIME_START = "2015-08-14"
CACHE_SECONDS = 900
_cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_cache_lock = threading.Lock()


def credentials(secrets: dict) -> dict:
    try:
        raw = secrets.get("service_account", "")
        if len(raw) > 32000:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("type") != "service_account":
            raise ValueError()
        if not isinstance(data.get("client_email"), str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.gserviceaccount\.com", data["client_email"]):
            raise ValueError()
        key = load_pem_private_key(data["private_key"].encode(), password=None)
        if not isinstance(key, RSAPrivateKey):
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise SyncError("Upload a valid Google service-account JSON key, not an OAuth client JSON file.") from e


def validate_config(config: dict, secrets: dict) -> None:
    if not re.fullmatch(r"[0-9]{1,20}", config.get("property_id", "")):
        raise SyncError("GA4 property ID must contain only numbers (not a G- tracking ID).")
    raw = config.get("hostname", "").strip().lower()
    try:
        url = urlsplit(raw if "://" in raw else "https://" + raw)
        host = (url.hostname or "").encode("idna").decode().rstrip(".")
        if url.scheme not in {"http", "https"} or url.username or url.password or url.port or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValueError()
        if len(host) > 253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
            raise ValueError()
    except (ValueError, UnicodeError) as e:
        raise SyncError("Enter your website's domain, such as example.com, without a page path.") from e
    config["hostname"] = host.removeprefix("www.")
    credentials(secrets)


def _response(response: httpx.Response, *, token: bool = False) -> dict:
    # Never echo upstream error bodies: authentication errors can contain credential material.
    if response.status_code >= 400:
        if token:
            hint = "The service-account key was rejected. Check that it is active and upload a new key if needed."
        else:
            hint = {400: "Check the property ID and date range.",
                    401: "The service-account credentials were rejected.",
                    403: "Enable Google Analytics Data API and grant the service account Viewer access to this GA4 property.",
                    404: "The GA4 property could not be found.",
                    429: "Google's reporting quota is temporarily exhausted. Try again later."}.get(response.status_code, "Google Analytics is unavailable. Try again later.")
        raise SyncError("Google Analytics: " + hint)
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except ValueError as e:
        raise SyncError("Google Analytics returned an unreadable response. Try again later.") from e


def fetch_report(client: httpx.Client, config: dict, secrets: dict, start: str, end: str) -> dict:
    config = dict(config)
    validate_config(config, secrets)
    cred = credentials(secrets)
    now = int(time.time())
    assertion = jwt.encode({"iss": cred["client_email"], "scope": SCOPE, "aud": TOKEN_URL,
                            "iat": now, "exp": now + 3600}, cred["private_key"], algorithm="RS256")
    try:
        # Use fixed Google endpoints, never URLs supplied by an uploaded JSON key.
        token = _response(client.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                       "assertion": assertion}, follow_redirects=False, timeout=15), token=True)
        if not isinstance(token.get("access_token"), str) or not token["access_token"]:
            raise SyncError("Google Analytics did not return an access token.")
        host = config["hostname"]
        body = _response(client.post(
            f"https://analyticsdata.googleapis.com/v1beta/properties/{config['property_id']}:runReport",
            headers={"Authorization": "Bearer " + token["access_token"]},
            json={"dateRanges": [{"startDate": start, "endDate": end}],
                  "metrics": [{"name": name} for name in METRICS],
                  "dimensionFilter": {"filter": {"fieldName": "hostName", "inListFilter": {
                      "values": [host, "www." + host], "caseSensitive": False}}}},
            follow_redirects=False, timeout=20))
    except httpx.HTTPError as e:
        raise SyncError("Could not reach Google Analytics. Try again later.") from e
    try:
        # A dimensionless report gives unique users across the whole period. Never add daily user counts.
        rows = body.get("rows", [])
        if len(rows) > 1 or body.get("rowCount", 0) > 1:
            raise ValueError()
        names = [h["name"] for h in body["metricHeaders"]]
        if set(names) != set(METRICS):
            raise ValueError()
        values = [int(v["value"]) for v in rows[0]["metricValues"]] if rows else [0] * len(names)
        if len(values) != len(names) or any(v < 0 for v in values):
            raise ValueError()
        totals = {METRICS[name]: value for name, value in zip(names, values)}
    except (KeyError, ValueError, TypeError, IndexError) as e:
        raise SyncError("Google Analytics returned incomplete totals. Try again later.") from e
    meta = body.get("metadata") or {}
    warnings = []
    if meta.get("subjectToThresholding"):
        warnings.append("Google may withhold some data because of privacy thresholds.")
    if meta.get("samplingMetadatas") or meta.get("dataLossFromOtherRow") or meta.get("dataTruncationReasons"):
        warnings.append("Google returned sampled or incomplete data for this period.")
    if meta.get("emptyReason"):
        warnings.append("Google returned an empty report. Check the property's data collection and reporting settings.")
    return {**totals, "start": start, "end": end, "timezone": meta.get("timeZone", ""),
            "fetched_at": utcnow().isoformat(), "warnings": warnings}


def report(client: httpx.Client, config: dict, secrets: dict, start: str, end: str, refresh: bool = False) -> dict:
    # Bounded process-local cache; identity includes credentials and host, so edits cannot reuse another site's totals.
    identity = hashlib.sha256(json.dumps([config, secrets], sort_keys=True).encode()).hexdigest()
    key = (identity, start, end, date.today().isoformat())
    with _cache_lock:
        cached = _cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < CACHE_SECONDS:
            _cache.move_to_end(key)
            return {**cached[1], "stale": False, "error": ""}
    try:
        result = fetch_report(client, config, secrets, start, end)
    except SyncError as e:
        if cached:
            return {**cached[1], "stale": True, "error": str(e)}
        raise
    with _cache_lock:
        _cache[key] = (time.monotonic(), result)
        _cache.move_to_end(key)
        while len(_cache) > 64:
            _cache.popitem(last=False)
    return {**result, "stale": False, "error": ""}


def test(ctx: SyncContext) -> str:
    fetch_report(ctx.client, ctx.config, ctx.secrets, "yesterday", "yesterday")
    return f"Connected to Google Analytics for {ctx.config['hostname']}"


def sync(ctx: SyncContext) -> None:
    result = report(ctx.client, ctx.config, ctx.secrets, "29daysAgo", "today", refresh=True)
    if result["stale"]:
        raise SyncError(result["error"])
    ctx.stats["site_visitors_30d"] = result["visitors"]
    ctx.warnings.extend(result["warnings"])
    ctx.metric("visitors", result["visitors"], "Site visitors", "num", "Traffic", "30d")
    ctx.metric("visits", result["visits"], "Visits (sessions)", "num", "Traffic", "30d")
    ctx.metric("page_views", result["page_views"], "Page views", "num", "Traffic", "30d")
    try:
        extra = _extra_report(ctx)
    except (SyncError, httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as e:
        ctx.warnings.append(f"Extra Google Analytics numbers unavailable ({e}).")
        return
    for name, (key, label, unit, section, combine) in EXTRA.items():
        if name in extra:
            v = extra[name]
            if unit == "pct":
                v = round(v * 100, 2)
            ctx.metric(key, round(v, 2), label, unit, section, "30d", combine)


EXTRA = {   # GA4 metric: (key, label, unit, section, combine)
    "newUsers": ("new_visitors", "New visitors", "num", "Traffic", "sum"),
    "activeUsers": ("active_visitors", "Active visitors", "num", "Traffic", "sum"),
    "engagedSessions": ("engaged_visits", "Engaged visits", "num", "Traffic", "sum"),
    "engagementRate": ("site_engagement_rate", "Engagement rate", "pct", "Traffic", "avg"),
    "bounceRate": ("bounce_rate", "Bounce rate", "pct", "Traffic", "avg"),
    "averageSessionDuration": ("avg_visit_seconds", "Average visit length", "seconds", "Traffic", "avg"),
    "screenPageViewsPerSession": ("pages_per_visit", "Pages per visit", "num", "Traffic", "avg"),
    "eventCount": ("site_events", "Events", "num", "Traffic", "sum"),
    "keyEvents": ("key_events", "Key events (conversions)", "num", "Sales", "sum"),
    "ecommercePurchases": ("site_purchases", "Website purchases", "num", "Sales", "sum"),
    "purchaseRevenue": ("site_revenue", "Website purchase revenue", "money", "Sales", "sum"),
    "addToCarts": ("add_to_carts", "Add-to-carts", "num", "Sales", "sum"),
    "checkouts": ("checkouts", "Checkouts started", "num", "Sales", "sum"),
}


def _extra_report(ctx: SyncContext) -> dict:
    """Second, best-effort report with everything else GA4 gives for the site (last 30 days)."""
    cred = credentials(ctx.secrets)
    now = int(time.time())
    assertion = jwt.encode({"iss": cred["client_email"], "scope": SCOPE, "aud": TOKEN_URL,
                            "iat": now, "exp": now + 3600}, cred["private_key"], algorithm="RS256")
    token = _response(ctx.client.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                       "assertion": assertion}, follow_redirects=False, timeout=15),
                      token=True)["access_token"]
    host = ctx.config["hostname"]
    out: dict = {}
    names = list(EXTRA)
    for chunk in (names[:10], names[10:]):          # GA4 allows 10 metrics per request
        body = _response(ctx.client.post(
            f"https://analyticsdata.googleapis.com/v1beta/properties/{ctx.config['property_id']}:runReport",
            headers={"Authorization": "Bearer " + token},
            json={"dateRanges": [{"startDate": "29daysAgo", "endDate": "today"}],
                  "metrics": [{"name": n} for n in chunk],
                  "dimensionFilter": {"filter": {"fieldName": "hostName", "inListFilter": {
                      "values": [host, "www." + host], "caseSensitive": False}}}},
            follow_redirects=False, timeout=20))
        heads = [h["name"] for h in body.get("metricHeaders", [])]
        rows = body.get("rows") or []
        vals = [float(v["value"]) for v in rows[0]["metricValues"]] if rows else [0.0] * len(heads)
        out.update(zip(heads, vals))
    return out
