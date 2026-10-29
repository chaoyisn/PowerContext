"""Configuration loaded from environment / .env. Every knob is documented in .env.example."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

EmbeddingProvider = Literal["minilm", "hashing", "openai", "multilingual"]
RetrievalMode = Literal["vector", "fulltext", "hybrid"]
FtsAnalyzer = Literal["ik", "ngram", "ngram2", "space", "beng"]


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RF_",
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- seekdb ---
    seekdb_mode: Literal["server", "embedded"] = "server"
    seekdb_host: str = "127.0.0.1"
    seekdb_port: int = 2881
    seekdb_tenant: str = "sys"
    seekdb_user: str = "root"
    seekdb_password: str = ""
    seekdb_database: str = "test"
    seekdb_path: str = "./data/seekdb.db"
    seekdb_prefix: str = "rf_"
    seekdb_fts_analyzer: FtsAnalyzer = "ik"
    seekdb_vector_distance: Literal["cosine", "l2", "inner_product"] = "cosine"
    seekdb_connect_timeout: int = 10

    # --- embeddings ---
    embedding_provider: EmbeddingProvider = "minilm"
    embedding_dimension: int = 384
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    # Optional cache directory for the multilingual ONNX model; defaults to <data>/models.
    embedding_multilingual_dir: str = ""

    # --- powercontext ---
    powercontext_url: str = "http://127.0.0.1:17429"
    powercontext_token: str = ""
    powercontext_timeout: float = 20.0
    powercontext_integration: str = "researchflow"
    powercontext_max_context_bytes: int = 6000

    # --- llm ---
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_timeout: float = 60.0
    llm_max_tokens: int = 1200
    llm_temperature: float = 0.2

    # --- retrieval / qa ---
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.0
    retrieval_min_coverage: float = 0.30
    retrieval_vector_confidence: float = 0.62
    qa_max_evidence_chunks: int = 8

    # --- uploads ---
    upload_max_bytes: int = 20 * 1024 * 1024
    upload_allowed_extensions: str = ".pdf,.md,.markdown,.txt"

    # --- http ---
    api_host: str = "127.0.0.1"
    api_port: int = 8787
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- storage ---
    data_dir: str = "./data"
    log_dir: str = "./logs"
    log_level: str = "INFO"

    @field_validator("seekdb_prefix")
    @classmethod
    def _normalize_prefix(cls, v: str) -> str:
        cleaned = "".join(ch for ch in v.strip().lower() if ch.isalnum() or ch == "_")
        return cleaned or "rf_"

    @property
    def allowed_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.upload_allowed_extensions.split(",") if e.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def data_path(self) -> Path:
        return _resolve(self.data_dir)

    @property
    def log_path(self) -> Path:
        return _resolve(self.log_dir)

    @property
    def upload_path(self) -> Path:
        return self.data_path / "uploads"

    @property
    def chunks_collection(self) -> str:
        return f"{self.seekdb_prefix}chunks"

    @property
    def documents_table(self) -> str:
        return f"{self.seekdb_prefix}documents"

    @property
    def pages_table(self) -> str:
        return f"{self.seekdb_prefix}pages"

    @property
    def projects_table(self) -> str:
        return f"{self.seekdb_prefix}projects"

    @property
    def meta_table(self) -> str:
        return f"{self.seekdb_prefix}meta"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.log_path.mkdir(parents=True, exist_ok=True)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    return settings
