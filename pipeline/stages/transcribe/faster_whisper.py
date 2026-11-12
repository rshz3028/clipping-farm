"""faster-whisper on the GPU. Tries each model in cfg['models']; moves on if out of GPU memory.

Models are kept as plain folders in models/whisper/<name> (downloaded there on first use).
"""
import gc
import subprocess
import time

from pipeline.core.settings import MODELS
from pipeline.core.tools import NO_WINDOW, ffmpeg, setup_cuda_dlls, write_json


def _is_oom(err: Exception) -> bool:
    msg = str(err).lower()
    return any(s in msg for s in ("out of memory", "cuda_error_out_of_memory", "cublas_status_alloc_failed"))


def _model_dir(name: str) -> str:
    d = MODELS / "whisper" / name
    if not (d / "model.bin").exists():
        from faster_whisper.utils import download_model
        print(f"  downloading Whisper '{name}' into {d} ...")
        download_model(name, output_dir=str(d))
    return str(d)


def run(unit, cfg):
    wav = unit.tmp_dir() / "audio16k.wav"
    if not wav.exists():                      # write to .part first: a killed run never leaves half a file
        part = wav.with_name("audio16k.part.wav")
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(unit.path("source/source.mp4")),
                        "-vn", "-ac", "1", "-ar", "16000", str(part)], check=True, creationflags=NO_WINDOW)
        part.replace(wav)
    setup_cuda_dlls()
    from faster_whisper import WhisperModel

    last_err = None
    for name in cfg["models"]:
        model = None
        try:
            t0 = time.time()
            print(f"  loading {name} ({cfg['device']}, {cfg['compute_type']})")
            model = WhisperModel(_model_dir(name), device=cfg["device"], compute_type=cfg["compute_type"])
            segs, info = model.transcribe(
                str(wav), language=cfg.get("language"), word_timestamps=True,
                vad_filter=cfg.get("vad_filter", True), beam_size=cfg.get("beam_size", 5),
                condition_on_previous_text=False,
            )
            segments = []
            for s in segs:
                segments.append({
                    "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                    "words": [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
                              for w in (s.words or [])],
                })
                print(f"\r  transcribed to {s.end/60:5.1f} min", end="", flush=True)
            print()
            write_json(unit.path("source/transcript.json"), {
                "source_id": unit.source_id, "model": name, "duration": round(info.duration, 2),
                "seconds_taken": round(time.time() - t0, 1), "segments": segments,
            })
            print(f"  {len(segments)} segments with {name}")
            wav.unlink(missing_ok=True)
            return
        except Exception as e:
            if not _is_oom(e):
                raise
            last_err = e
            print(f"\n  {name} ran out of GPU memory, trying next model")
        finally:
            del model
            gc.collect()
    raise RuntimeError(f"All Whisper models ran out of memory: {last_err}")
