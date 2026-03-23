import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project root = directory containing this file's parent (app/../)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class Config:
    TOWN: str = os.environ.get("TOWN", "")
    DATA_ROOT: Path = PROJECT_ROOT / os.environ.get("DATA_ROOT", "data")

    # Derived database URI — requires TOWN to be set
    @classmethod
    def database_uri(cls) -> str:
        if not cls.TOWN:
            raise RuntimeError("TOWN environment variable is not set. Run: export TOWN=<town>")
        db_path = cls.DATA_ROOT / cls.TOWN / "database.db"
        return f"sqlite:///{db_path.resolve()}"

    @classmethod
    def town_config_path(cls) -> Path:
        return cls.DATA_ROOT / cls.TOWN / "config.json"

    @classmethod
    def town_cache_path(cls) -> Path:
        return cls.DATA_ROOT / cls.TOWN / "cache" / "html"

    @classmethod
    def geo_context(cls) -> dict:
        """Return geographic context for LLM classification."""
        import json
        try:
            cfg = json.loads(cls.town_config_path().read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        return {
            "town": cls.TOWN,
            "province": cfg.get("province", ""),
            "region_towns": [t.lower() for t in cfg.get("region_towns", []) if t],
            "province_towns": [t.lower() for t in cfg.get("province_towns", []) if t],
        }

    # Flask
    SECRET_KEY: str = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Admin
    ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "admin")

    # AI models — read from env, else fall back to ~/.config/openai_api_key.txt
    @classmethod
    def _read_openai_key(cls) -> str:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            try:
                key_file = Path.home() / ".config" / "openai_api_key.txt"
                key = key_file.read_text().strip()
            except (OSError, IOError):
                pass
        return key

    OPENAI_API_KEY: str = ""  # resolved at runtime via _read_openai_key()
    OPENAI_MODEL_DEFAULT: str = os.environ.get("OPENAI_MODEL_DEFAULT", "gpt-4o-mini")
    OPENAI_MODEL_STRONG: str = os.environ.get("OPENAI_MODEL_STRONG", "gpt-4o")

    # Embedding
    EMBEDDING_MODEL: str = os.environ.get(
        "EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
    )
    EMBEDDING_DIM: int = 384

    # Story clustering thresholds
    STORY_AUTOMERGE_THRESHOLD: float = float(
        os.environ.get("STORY_AUTOMERGE_THRESHOLD", "0.85")
    )
    STORY_SUGGEST_THRESHOLD: float = float(
        os.environ.get("STORY_SUGGEST_THRESHOLD", "0.65")
    )

    # Scheduling
    FETCH_INTERVAL_MINUTES: int = int(os.environ.get("FETCH_INTERVAL_MINUTES", "15"))
    EMBED_INTERVAL_MINUTES: int = 5
    CLUSTER_INTERVAL_MINUTES: int = 30

    # Clustering KNN lookback window (days)
    CLUSTER_LOOKBACK_DAYS: int = 30

    # APScheduler
    SCHEDULER_API_ENABLED: bool = False
