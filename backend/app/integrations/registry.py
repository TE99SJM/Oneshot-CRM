from . import ebay, facebook, gmail, google_analytics, instagram, rumble, square, twitch, youtube

PROVIDERS = {m.INFO.key: m for m in (youtube, facebook, instagram, square, ebay, gmail, rumble, twitch, google_analytics)}
