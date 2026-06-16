"""Load the applicant's master data (resume) JSON.

Resolution order:
1. MASTER_DATA_JSON env var (raw JSON) — handy for cloud without committing the file
2. MASTER_DATA_PATH file (local, or a Render Secret File)
"""
import json
from .config import cfg


def load_master() -> dict:
    if cfg.MASTER_DATA_JSON:
        return json.loads(cfg.MASTER_DATA_JSON)
    if cfg.MASTER_DATA_PATH.exists():
        return json.loads(cfg.MASTER_DATA_PATH.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"master data not found. Set MASTER_DATA_PATH (or a Render Secret File) "
        f"or paste MASTER_DATA_JSON. Looked at {cfg.MASTER_DATA_PATH}."
    )


def master_exists() -> bool:
    return bool(cfg.MASTER_DATA_JSON) or cfg.MASTER_DATA_PATH.exists()
