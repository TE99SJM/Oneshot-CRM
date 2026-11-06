from . import facebook, rumble, square, youtube

PROVIDERS = {m.INFO.key: m for m in (youtube, facebook, square, rumble)}
