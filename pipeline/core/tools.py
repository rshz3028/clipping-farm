"""Small shared helpers: FFmpeg location, CUDA DLLs, atomic file writes."""
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

# Start helper programs (step processes, FFmpeg, claude) without opening a console window.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def ffmpeg() -> str:
    """FFmpeg 7.1 bundled with imageio-ffmpeg (inside .venv). Its NVENC works with driver 596."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def setup_cuda_dlls() -> None:
    """Make the pip-installed CUDA libraries (cuBLAS, cuDNN) visible on Windows."""
    base = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    for d in glob.glob(os.path.join(base, "*", "bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def write_json(path: Path, data) -> None:
    """Write JSON so a crash never leaves a half-written file behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
