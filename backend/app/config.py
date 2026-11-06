"""Application settings loaded from environment variables (and an optional .env file)."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                              # repo root
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = os.getenv("APP_NAME", "FunnelHub CRM")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    database_url: str = os.getenv("DATABASE_URL", "")
    secret_key: str = os.getenv("SECRET_KEY", "")
    token_minutes: int = int(os.getenv("TOKEN_MINUTES", str(60 * 24 * 7)))
    cors_origins: list[str] = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    ]
    frontend_dist: Path = Path(os.getenv("FRONTEND_DIST", str(PROJECT_DIR / "frontend" / "dist")))
    allow_demo_seed: bool = _bool("ALLOW_DEMO_SEED", True)

    def __init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'funnelhub.db').as_posix()}"
        if not self.secret_key:
            # Persist a generated key so logins survive restarts without manual setup.
            key_file = self.data_dir / ".secret_key"
            if key_file.exists():
                self.secret_key = key_file.read_text().strip()
            else:
                self.secret_key = secrets.token_urlsafe(48)
                key_file.write_text(self.secret_key)


settings = Settings()
