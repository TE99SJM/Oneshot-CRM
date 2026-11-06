from . import facebook, instagram, rumble, square, twitch, youtube

PROVIDERS = {m.INFO.key: m for m in (youtube, facebook, instagram, square, rumble, twitch)}
