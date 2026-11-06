from . import ebay, facebook, instagram, rumble, square, twitch, youtube

PROVIDERS = {m.INFO.key: m for m in (youtube, facebook, instagram, square, ebay, rumble, twitch)}
