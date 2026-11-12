"""Kokoro-82M TTS on the CPU via onnxruntime (no PyTorch). One sentence at a time,
so each sentence's start/end time in the final audio is known exactly."""
import wave

import numpy as np

from pipeline.core.settings import ROOT
from pipeline.core.tools import write_json


def run(unit, cfg):
    from kokoro_onnx import Kokoro

    script = unit.json("short/script.json")
    k = Kokoro(str(ROOT / cfg["model_file"]), str(ROOT / cfg["voices_file"]))
    speed = float(cfg.get("speed", 1.0))
    t = cfg.get("timing", {})
    pb = float(t.get("playback_speed", 1.0))
    # final video = speech + end card <= max_seconds, and everything is later sped up by pb
    limit = (float(t.get("max_seconds", 59.5)) - float(t.get("end_card_seconds", 2.5)) - 0.5) * pb
    pcm, sentences = _speak(k, script, cfg, speed)
    max_speed = speed * float(cfg.get("max_speedup", 1.1))
    for _ in range(3):                        # too long for the Short + end card: speak a little faster
        if sentences[-1]["end"] <= limit or speed >= max_speed:
            break
        speed = min(max_speed, speed * sentences[-1]["end"] / limit * 1.02)
        print(f"  {sentences[-1]['end']:.1f}s is over {limit}s; re-speaking at speed {speed:.2f}")
        pcm, sentences = _speak(k, script, cfg, speed)
    sr = 24000
    pcm = pcm / max(1e-6, float(np.abs(pcm).max())) * 0.89            # peak about -1 dBFS
    tmp = unit.path("short/narration.wav.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm * 32767).astype(np.int16).tobytes())
    tmp.replace(unit.path("short/narration.wav"))
    write_json(unit.path("short/narration.json"), {
        "voice": cfg["voice"], "speed": round(speed, 3), "sample_rate": sr, "duration": round(len(pcm) / sr, 3),
        "speech_end": sentences[-1]["end"], "sentences": sentences,
    })
    print(f"  {len(pcm) / sr:.1f}s of narration")


def _speak(k, script, cfg, speed):
    sr = 24000
    gap = np.zeros(int(sr * cfg.get("sentence_gap", 0.25)), dtype=np.float32)
    parts = [np.zeros(int(sr * cfg.get("lead_in", 0.2)), dtype=np.float32)]
    t = len(parts[0]) / sr
    sentences = []
    for i, text in enumerate(script["sentences"]):
        audio, sr_out = k.create(text, voice=cfg["voice"], speed=speed, lang=cfg.get("lang", "en-us"))
        assert sr_out == sr, sr_out
        audio = np.asarray(audio, dtype=np.float32)
        sentences.append({"i": i, "text": text, "start": round(t, 3), "end": round(t + len(audio) / sr, 3)})
        parts += [audio, gap]
        t += (len(audio) + len(gap)) / sr
        print(f"\r  sentence {i + 1}/{len(script['sentences'])}", end="", flush=True)
    print()
    return np.concatenate(parts), sentences
