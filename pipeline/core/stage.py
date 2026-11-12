"""What a stage is, and the 'unit' (a source or a short) it works on.

Every stage has a fixed CONTRACT, declared in pipeline/stages/<stage>/__init__.py:
    LEVEL   = "source" or "short"
    INPUTS  = files it reads    e.g. ["source/source.mp4"]
    OUTPUTS = files it writes   e.g. ["source/transcript.json"]

An implementation is any module pipeline/stages/<stage>/<impl>.py with:
    def run(unit: Unit, cfg: dict) -> None
It must read only its INPUTS and must write all of its OUTPUTS. As long as it
keeps the file formats in CONTRACTS.md, it can be swapped freely.

File references:
    "source/<file>" -> work/sources/<source_id>/<file>
    "short/<file>"  -> work/shorts/<short_id>/<file>
"""
import importlib
from dataclasses import dataclass
from pathlib import Path

from pipeline.core.settings import CONFIG, SHORTS_DIR, SOURCES_DIR, stage_config
from pipeline.core.tools import read_json

# The order stages run in. Source-level stages first, then Short-level stages.
STAGE_ORDER = ["download", "transcribe", "shots", "describe", "select", "script", "check",
               "narrate", "captions", "render", "package"]


@dataclass
class Unit:
    """A source video (id = source_id) or a short (id = '<source_id>__<n>')."""
    id: str

    @property
    def kind(self) -> str:
        return "short" if "__" in self.id else "source"

    @property
    def source_id(self) -> str:
        return self.id.split("__", 1)[0]

    @property
    def source_dir(self) -> Path:
        return SOURCES_DIR / self.source_id

    @property
    def short_dir(self) -> Path:
        if self.kind != "short":
            raise ValueError(f"{self.id} is a source, not a short")
        return SHORTS_DIR / self.id

    @property
    def dir(self) -> Path:
        return self.short_dir if self.kind == "short" else self.source_dir

    def path(self, ref: str) -> Path:
        """Resolve 'source/x' or 'short/x' to a real file path."""
        scope, name = ref.split("/", 1)
        base = self.source_dir if scope == "source" else self.short_dir
        base.mkdir(parents=True, exist_ok=True)
        return base / name

    def tmp_dir(self) -> Path:
        d = self.dir / "_tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def json(self, ref: str):
        return read_json(self.path(ref))


@dataclass
class StageSpec:
    name: str
    level: str
    inputs: list
    outputs: list
    impl_name: str
    cfg: dict

    def implementation(self):
        return importlib.import_module(f"pipeline.stages.{self.name}.{self.impl_name}")


def load_stage(name: str) -> StageSpec:
    contract = importlib.import_module(f"pipeline.stages.{name}")
    cfg = stage_config(name)
    for block in getattr(contract, "SHARED_SETTINGS", []):     # e.g. [timing]; part of the fingerprint
        cfg[block] = dict(CONFIG.get(block, {}))
    impl = cfg.pop("impl", None)
    if not impl:
        raise ValueError(f"pipeline.toml has no impl for stage '{name}'")
    return StageSpec(name, contract.LEVEL, list(contract.INPUTS), list(contract.OUTPUTS), impl, cfg)
