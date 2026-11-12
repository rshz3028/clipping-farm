"""Loads pipeline.toml and keeps every download/cache inside the project folder."""
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # D:\dev\clipping_farm
MPT_DIR = ROOT / "MoneyPrinterTurbo"                  # stock MoneyPrinterTurbo, used as a library

with open(ROOT / "pipeline.toml", "rb") as _f:
    CONFIG = tomllib.load(_f)

_p = CONFIG["paths"]
WORK = ROOT / _p["work"]
OUTPUT = ROOT / _p["output"]
MODELS = ROOT / _p["models"]
CACHE = ROOT / _p["cache"]
DB_PATH = WORK / "pipeline.db"
SOURCES_DIR = WORK / "sources"
SHORTS_DIR = WORK / "shorts"
REVIEW_DIR = OUTPUT / "review"
APPROVED_DIR = OUTPUT / "approved"

for _d in (WORK, SOURCES_DIR, SHORTS_DIR, REVIEW_DIR, APPROVED_DIR, MODELS, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

# Keep model downloads out of C:\Users\...\.cache
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE))

# Make stock MoneyPrinterTurbo importable as a library (import app.services...)
if str(MPT_DIR) not in sys.path:
    sys.path.append(str(MPT_DIR))


def stage_config(stage: str) -> dict:
    return dict(CONFIG.get("stages", {}).get(stage, {}))
