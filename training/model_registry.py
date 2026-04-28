"""Model registry for candidate/active/archive model lifecycle.

Training should write to candidates first.  Runtime code should read active
models through this registry so later auto-training can promote or roll back
without touching trading logic.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
ACTIVE_DIR = BASE_DIR / "models" / "active"
CANDIDATES_DIR = BASE_DIR / "models" / "candidates"
ARCHIVE_DIR = BASE_DIR / "models" / "archive"
REGISTRY_PATH = BASE_DIR / "models" / "registry.json"


def _ensure_dirs() -> None:
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def candidate_path(name: str) -> Path:
    _ensure_dirs()
    return CANDIDATES_DIR / name


def active_path(name: str) -> Path:
    _ensure_dirs()
    return ACTIVE_DIR / name


def register_candidate(path: str, metrics: Optional[dict] = None,
                       role: str = "vision") -> dict:
    """Record a trained candidate model without activating it."""
    _ensure_dirs()
    p = Path(path)
    record = {
        "role": role,
        "candidate": str(p),
        "metrics": metrics or {},
        "registered_at": datetime.now().isoformat(),
        "status": "CANDIDATE",
    }
    records = []
    if REGISTRY_PATH.exists():
        try:
            records = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(record)
    REGISTRY_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record


def promote_candidate(candidate: str, active_name: str,
                      metrics: Optional[dict] = None) -> Path:
    """Promote a candidate to active, archiving the previous active file."""
    _ensure_dirs()
    src = Path(candidate)
    if not src.exists():
        raise FileNotFoundError(str(src))

    dst = ACTIVE_DIR / active_name
    if dst.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(dst, ARCHIVE_DIR / f"{dst.stem}_{ts}{dst.suffix}")

    shutil.copy2(src, dst)
    register_candidate(str(src), metrics=metrics, role=active_name)
    return dst
