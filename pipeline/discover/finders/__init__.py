"""Shared helpers for finders."""
import json
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "archival-shorts-pipeline/0.1"}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def slug(text: str, n: int = 32) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:n].rstrip("_")


def minutes(text) -> float | None:
    """'0:24:29', '14:26', '1:00:34' or 'PA8087 ... 0:10:14' -> minutes."""
    m = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?!\d)", str(text or ""))
    if not m:
        return None
    h, mm, ss = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    return round(h * 60 + mm + ss / 60, 1)


def quote(s: str) -> str:
    return urllib.parse.quote(s)
