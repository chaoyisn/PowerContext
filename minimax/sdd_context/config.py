"""Runtime configuration for the MiniMax SDD context module.

Every value can be overridden through the environment so the module can run
against a locally owned seekdb instance and a locally started PowerContext
server without editing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one SDD context module instance."""

    root: Path = field(default_factory=lambda: Path(_env("SDD_CONTEXT_ROOT", str(DEFAULT_ROOT))))

    seekdb_host: str = field(default_factory=lambda: _env("SDD_SEEKDB_HOST", "127.0.0.1"))
    seekdb_port: int = field(default_factory=lambda: _env_int("SDD_SEEKDB_PORT", 2881))
    seekdb_user: str = field(default_factory=lambda: _env("SDD_SEEKDB_USER", "root"))
    seekdb_password: str = field(default_factory=lambda: _env("SDD_SEEKDB_PASSWORD", ""))
    seekdb_database: str = field(default_factory=lambda: _env("SDD_SEEKDB_DATABASE", "sdd_context"))

    powercontext_url: str = field(default_factory=lambda: _env("SDD_POWERCONTEXT_URL", "http://127.0.0.1:8790"))
    powercontext_token: str = field(default_factory=lambda: _env("SDD_POWERCONTEXT_TOKEN", ""))
    powercontext_timeout: float = field(default_factory=lambda: float(_env("SDD_POWERCONTEXT_TIMEOUT", "30")))
    powercontext_scope_id: str = field(default_factory=lambda: _env("SDD_POWERCONTEXT_SCOPE_ID", ""))

    minimax_base_url: str = field(default_factory=lambda: _env("SDD_MINIMAX_BASE_URL", "http://127.0.0.1:15721"))
    minimax_api_key: str = field(default_factory=lambda: _env("SDD_MINIMAX_API_KEY", "PROXY_MANAGED"))
    minimax_model: str = field(default_factory=lambda: _env("SDD_MINIMAX_MODEL", "MiniMax-M3.1-Flash"))
    minimax_timeout: float = field(default_factory=lambda: float(_env("SDD_MINIMAX_TIMEOUT", "600")))

    @property
    def state_dir(self) -> Path:
        return self.root / ".state"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    @property
    def spec_dir(self) -> Path:
        return self.root / "specs"

    @property
    def sample_dir(self) -> Path:
        return self.root / "sample"

    @property
    def tests_dir(self) -> Path:
        return self.root / "tests"

    def ensure_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    return Settings()
