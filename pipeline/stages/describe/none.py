"""No vision model: writes empty descriptions (shots are then matched by speech only)."""
from pipeline.core.tools import write_json


def run(unit, cfg):
    write_json(unit.path("source/shot_descriptions.json"),
               {"source_id": unit.source_id, "model": None, "descriptions": {}})
