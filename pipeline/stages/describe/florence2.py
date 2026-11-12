"""Florence-2 (local vision model) captions a frame from the middle of each shot.

STATUS: works, but on this laptop's CPU it currently takes ~40 s per frame (about 45 min
per source), so it is not enabled by default. See README / pipeline.toml.
"""
import time

from pipeline.core.settings import ROOT
from pipeline.core.tools import write_json


def run(unit, cfg):
    import cv2
    import torch
    from PIL import Image
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    torch.set_num_threads(int(cfg.get("threads", 8)))
    path = str(ROOT / cfg.get("model_dir", "models/florence2/base"))
    proc = AutoProcessor.from_pretrained(path)
    model = Florence2ForConditionalGeneration.from_pretrained(path).eval()
    shots = unit.json("source/shots.json")["shots"]
    cap = cv2.VideoCapture(str(unit.path("source/source.mp4")))
    task = cfg.get("task", "<CAPTION>")
    out, t0 = {}, time.time()
    for n, sh in enumerate(shots, 1):
        cap.set(cv2.CAP_PROP_POS_MSEC, (sh["start"] + sh["end"]) / 2 * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        inp = proc(text=task, images=img, return_tensors="pt")
        with torch.inference_mode():
            ids = model.generate(**inp, max_new_tokens=int(cfg.get("max_tokens", 40)), num_beams=1)
        out[str(sh["i"])] = proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
        print(f"\r  shot {n}/{len(shots)}  ({time.time() - t0:.0f}s)", end="", flush=True)
    print()
    write_json(unit.path("source/shot_descriptions.json"),
               {"source_id": unit.source_id, "model": f"florence2:{cfg.get('model_dir')}", "descriptions": out})
