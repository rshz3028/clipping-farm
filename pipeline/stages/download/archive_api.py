"""Download via the official NASA Images API / Internet Archive metadata API.

Re-checks the licence on the source page at download time. Resumes partial downloads.
"""
import json
import urllib.parse
import urllib.request

from pipeline.core import registry

UA = {"User-Agent": "archival-shorts-pipeline/0.1"}
PD_LICENCES = (
    "creativecommons.org/licenses/publicdomain",
    "creativecommons.org/publicdomain/mark",
    "creativecommons.org/publicdomain/zero",
)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def _size_mb(url: str) -> float:
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length", 0)) / 1e6


def _nasa_file_url(page_url: str, cfg: dict) -> str:
    nasa_id = urllib.parse.unquote(page_url.rstrip("/").rsplit("/", 1)[-1])
    hrefs = [i["href"] for i in
             _get_json(f"https://images-api.nasa.gov/asset/{urllib.parse.quote(nasa_id)}")["collection"]["items"]]
    meta = _get_json([h for h in hrefs if h.endswith("metadata.json")][0].replace(" ", "%20"))
    for k, v in meta.items():
        if any(s in k.lower() for s in ("copyright", "rights", "usage")) and "©" in str(v):
            raise registry.SourceNotApproved(f"NASA metadata now shows third-party copyright: {v}")
    max_mb = float(cfg.get("max_mb", 1100))
    tried = []
    for q in cfg.get("nasa_quality", ["large", "medium", "small", "mobile"]):
        for h in hrefs:
            if h.endswith(f"~{q}.mp4"):
                url = h.replace(" ", "%20").replace("http://", "https://", 1)
                mb = _size_mb(url)
                tried.append(f"{q} {mb:.0f}MB")
                if mb <= max_mb:
                    return url
    raise RuntimeError(f"No NASA MP4 under {max_mb:.0f} MB (found: {', '.join(tried) or 'none'})")


def _archive_file_url(page_url: str) -> str:
    ident = page_url.rstrip("/").rsplit("/", 1)[-1]
    m = _get_json(f"https://archive.org/metadata/{ident}")
    md = m["metadata"]
    cols = md.get("collection", [])
    cols = [cols] if isinstance(cols, str) else cols
    if "prelinger" not in cols:
        raise registry.SourceNotApproved(f"{ident} is not in the Prelinger collection")
    if not any(p in md.get("licenseurl", "") for p in PD_LICENCES):
        raise registry.SourceNotApproved(f"{ident} licence changed: {md.get('licenseurl')}")
    mp4s = [f for f in m["files"] if f["name"].endswith(".mp4")]
    rank = lambda f: 0 if f.get("format") == "h.264" else 1 if "HiRes" in f.get("format", "") else 2
    return f"https://archive.org/download/{ident}/{urllib.parse.quote(sorted(mp4s, key=rank)[0]['name'])}"


def resolve_file_url(page_url: str, cfg: dict) -> str:
    host = urllib.parse.urlparse(page_url).netloc
    if host == "images.nasa.gov":
        return _nasa_file_url(page_url, cfg)
    if host == "archive.org":
        return _archive_file_url(page_url)
    raise NotImplementedError(f"No downloader for {host} yet")


def run(unit, cfg):
    rec = registry.require_approved(unit.source_id)
    dest = unit.path("source/source.mp4")
    if dest.exists() and dest.stat().st_size > 0:
        # Already downloaded: keep it, so later stages (and Claude calls) are not redone.
        # To force a fresh download, delete source.mp4 first.
        print("  already downloaded, keeping existing file")
        registry.set_local_path(unit.source_id, dest)
        return
    part = dest.with_name(dest.name + ".part")
    file_url = resolve_file_url(rec["url"], cfg)
    have = part.stat().st_size if part.exists() else 0
    headers = dict(UA, **({"Range": f"bytes={have}-"} if have else {}))
    print(f"  from {file_url}")
    with urllib.request.urlopen(urllib.request.Request(file_url, headers=headers), timeout=120) as r:
        if have and r.status != 206:
            have = 0
        total = have + int(r.headers.get("Content-Length", 0))
        with open(part, "ab" if have else "wb") as f:
            done = have
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done/1e6:7.1f} / {total/1e6:.1f} MB", end="", flush=True)
    print()
    part.replace(dest)
    registry.set_local_path(unit.source_id, dest)
