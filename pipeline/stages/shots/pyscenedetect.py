"""PySceneDetect ContentDetector on the CPU."""
import time

from pipeline.core.tools import write_json


def run(unit, cfg):
    from scenedetect import ContentDetector, SceneManager, open_video

    t0 = time.time()
    v = open_video(str(unit.path("source/source.mp4")))
    sm = SceneManager()
    sm.auto_downscale = True
    sm.add_detector(ContentDetector(threshold=cfg.get("threshold", 27.0),
                                    min_scene_len=cfg.get("min_scene_frames", 12)))
    sm.detect_scenes(v, show_progress=False)
    scenes = sm.get_scene_list() or [(v.base_timecode, v.duration)]
    shots = [{"i": i, "start": round(a.seconds, 2), "end": round(b.seconds, 2)}
             for i, (a, b) in enumerate(scenes)]
    write_json(unit.path("source/shots.json"), {
        "source_id": unit.source_id, "fps": round(float(v.frame_rate), 3),
        "width": v.frame_size[0], "height": v.frame_size[1],
        "seconds_taken": round(time.time() - t0, 1), "shots": shots,
    })
    print(f"  {len(shots)} shots")
