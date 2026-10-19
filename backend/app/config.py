"""Settings from .env plus the YAML config files (pipeline, senders, export)."""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""  # from .env (ANTHROPIC_API_KEY) only; never in source
    claude_model: str = "claude-sonnet-5-5"
    data_dir: Path = REPO_ROOT / "data"
    config_dir: Path = REPO_ROOT / "config"
    jwt_secret: str = ""  # from .env (JWT_SECRET); a random per-process secret is used when empty
    jwt_ttl_hours: int = 12
    ssl_cert_file: str = ""  # CA bundle of a TLS-intercepting network filter (SSL_CERT_FILE); empty = system default
    demo_password: str = "demo1234"  # password of the seeded demo users (DEMO_PASSWORD)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def batches_dir(self) -> Path:
        return self.data_dir / "batches"

    def _yaml(self, name: str) -> Dict[str, Any]:
        with open(self.config_dir / name, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _config(self, name: str) -> Dict[str, Any]:
        """Mappings live in the DB (table configentry); the YAML file is only the seed / fallback."""
        try:
            from sqlmodel import Session

            from app.db import get_engine
            from app.models import ConfigEntry

            with Session(get_engine()) as s:
                row = s.get(ConfigEntry, name)
            if row is not None:
                return json.loads(row.data)
        except Exception:  # no table / no DB yet
            pass
        return self._yaml(f"{name}.yaml")

    @property
    def pipeline(self) -> Dict[str, Any]:
        return self._config("pipeline")

    @property
    def senders(self) -> Dict[str, Any]:
        return self._config("senders")

    @property
    def export(self) -> Dict[str, Any]:
        return self._config("export")


@lru_cache
def get_settings() -> Settings:
    return Settings()
