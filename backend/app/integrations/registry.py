from . import ebay, facebook, gmail, google_analytics, instagram, rumble, square, tiktok, tiktok_shop, twitch, youtube

PROVIDERS = {m.INFO.key: m for m in (youtube, facebook, instagram, tiktok, square, ebay,
                                         tiktok_shop, gmail, rumble, twitch, google_analytics)}
OAUTH_APPS = {m.INFO.key: m for m in (tiktok, tiktok_shop)}            # sign in via /api/oauth/<slug>/callback
