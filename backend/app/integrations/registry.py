from . import ebay, facebook, gmail, instagram, rumble, square, twitch, youtube

PROVIDERS = {m.INFO.key: m for m in (youtube, facebook, instagram, square, ebay, gmail, rumble, twitch)}
