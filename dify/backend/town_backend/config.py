"""《记仇小镇》后端配置。

所有配置都来自环境变量，且带可用的本地默认值，
以便 ``docker compose up`` 与 ``python -m town_backend`` 两种方式都能跑起来。

路径解析以**仓库根目录**为基准，而不是当前工作目录，
否则同一份配置在不同目录启动会指向不同的文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = DEFAULT_ROOT.parent


def _resolve_root(value: str) -> Path:
    """Resolve a module root against the repository root.

    A relative ``TOWN_ROOT`` must not depend on the current working
    directory, otherwise the same configuration template points at
    different places depending on where the command was started.
    """

    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (REPOSITORY_ROOT / candidate).resolve()


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


@dataclass
class Settings:
    """Runtime settings for the town backend."""

    # ---------------------------------------------------------------- paths
    root: Path = field(default_factory=lambda: _resolve_root(_env("TOWN_ROOT", str(DEFAULT_ROOT))))

    # ---------------------------------------------------------------- seekdb
    seekdb_host: str = field(default_factory=lambda: _env("TOWN_SEEKDB_HOST", "127.0.0.1"))
    seekdb_port: int = field(default_factory=lambda: int(_env("TOWN_SEEKDB_PORT", "2881")))
    seekdb_user: str = field(default_factory=lambda: _env("TOWN_SEEKDB_USER", "root"))
    seekdb_password: str = field(default_factory=lambda: _env("TOWN_SEEKDB_PASSWORD", ""))
    seekdb_database: str = field(default_factory=lambda: _env("TOWN_SEEKDB_DATABASE", "memory_town"))

    # ----------------------------------------------------------- powercontext
    powercontext_url: str = field(default_factory=lambda: _env("TOWN_POWERCONTEXT_URL", "http://127.0.0.1:8800"))
    powercontext_token: str = field(default_factory=lambda: _env("TOWN_POWERCONTEXT_TOKEN", ""))
    powercontext_timeout: float = field(default_factory=lambda: float(_env("TOWN_POWERCONTEXT_TIMEOUT", "20")))

    # ------------------------------------------------------------------ http
    backend_token: str = field(default_factory=lambda: _env("TOWN_BACKEND_TOKEN", ""))
    backend_port: int = field(default_factory=lambda: int(_env("TOWN_BACKEND_PORT", "8848")))
    log_level: str = field(default_factory=lambda: _env("TOWN_LOG_LEVEL", "INFO"))

    # ------------------------------------------------------------- behaviour
    #: Request body size cap; a player message beyond this is rejected.
    max_message_length: int = field(default_factory=lambda: int(_env("TOWN_MAX_MESSAGE_LENGTH", "500")))

    @property
    def schema_path(self) -> Path:
        return self.root / "data" / "schema.sql"

    @property
    def seed_path(self) -> Path:
        return self.root / "data" / "seed.sql"


def load_settings() -> Settings:
    """Build the settings from the process environment."""

    return Settings()
