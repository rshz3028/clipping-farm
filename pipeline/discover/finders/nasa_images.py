"""Finder: NASA Image and Video Library (images.nasa.gov).

Licence check (automatic, per item, on NASA's own metadata):
  - every rights/copyright/usage field present must point to NASA's media guidelines
    and must not contain a (c) notice;
  - no third-party credit (Getty, AP, Reuters, courtesy, etc.);
  - not from JPL (managed by Caltech, different terms) or other excluded centres.
Content checks: length between min/max minutes; titles that are usually modern edits with
licensed music, interviews or news shows are skipped.
"""
import re
from urllib.parse import quote as q

from pipeline.discover.finders import get_json, minutes, slug

NAME = "nasa_images"
LICENCE = "NASA media - not subject to US copyright (NASA Images and Media Usage Guidelines)"
RESTRICTIONS = (
    "Credit NASA. Do not imply NASA endorsement of any product, service or channel. "
    "Do not use the NASA insignia/logotype as branding. Do not use names/likenesses of "
    "currently employed NASA astronauts or staff in a commercial/promotional way. "
    "Narration and thumbnails must be our own."
)
EVIDENCE = ("https://www.nasa.gov/nasa-brand-center/images-and-media/ ; item metadata Rights/Credit "
            "fields point to NASA guidelines, no third-party copyright listed")
THIRD_PARTY = re.compile(r"©|\(c\)|getty|associated press|\bap\b|reuters|courtesy|all rights reserved", re.I)


def make_record(source_id: str, nasa_id: str, title: str, evidence: str = EVIDENCE) -> dict:
    return dict(
        source_id=source_id, url="https://images.nasa.gov/details/" + q(nasa_id, safe=",-_"),
        title=title, owner="NASA", licence=LICENCE, commercial_use_allowed=1, derivatives_allowed=1,
        attribution_text=f'Footage: NASA - "{title}" (images.nasa.gov)', restrictions=RESTRICTIONS,
        licence_evidence=evidence, date_checked=__import__("time").strftime("%Y-%m-%d"),
    )


def _licence_problem(meta: dict) -> str | None:
    for k, v in meta.items():
        kl, vs = k.lower(), str(v)
        if any(s in kl for s in ("copyright", "rights", "usage")) and vs.strip():
            if "nasa.gov" not in vs.lower() or "©" in vs:
                return f"{k}: {vs[:120]}"
        if any(s in kl for s in ("credit", "creator", "photographer")) and THIRD_PARTY.search(vs):
            return f"third-party credit {k}: {vs[:120]}"
    return None


def search(cfg: dict, known: set):
    exclude_centers = set(cfg.get("exclude_centers", ["JPL"]))
    exclude = re.compile("|".join(cfg.get("exclude_title_patterns", [])) or r"$^", re.I)
    lo, hi = cfg.get("min_minutes", 5), cfg.get("max_minutes", 60)
    found, rejected, checks = [], [], 0
    for query in cfg.get("queries", []):
        data = get_json(f"https://images-api.nasa.gov/search?media_type=video&page_size=40&q={q(query)}")
        for it in data["collection"]["items"]:
            m = it["data"][0]
            nid, title = m["nasa_id"], m.get("title", m["nasa_id"])
            url = "https://images.nasa.gov/details/" + q(nid, safe=",-_")
            if url in known or any(f["url"] == url for f in found):
                continue
            if m.get("center") in exclude_centers:
                rejected.append({"url": url, "title": title, "reason": f"centre {m.get('center')} excluded"})
                continue
            if exclude.search(title):
                rejected.append({"url": url, "title": title, "reason": "title matches an exclude pattern"})
                continue
            if checks >= int(cfg.get("max_checks", 25)):
                continue
            checks += 1
            try:
                hrefs = [i["href"] for i in get_json(f"https://images-api.nasa.gov/asset/{q(nid)}")["collection"]["items"]]
                meta = get_json([h for h in hrefs if h.endswith("metadata.json")][0].replace(" ", "%20"))
            except Exception as e:
                rejected.append({"url": url, "title": title, "reason": f"metadata unavailable: {e}"})
                continue
            problem = _licence_problem(meta)
            if problem:
                rejected.append({"url": url, "title": title, "reason": f"licence: {problem}"})
                continue
            mins = minutes(meta.get("QuickTime:Duration") or meta.get("QuickTime:MediaDuration"))
            if mins is None or not (lo <= mins <= hi):
                rejected.append({"url": url, "title": title, "reason": f"length {mins} min outside {lo}-{hi}"})
                continue
            if not any(h.endswith(".mp4") for h in hrefs):
                rejected.append({"url": url, "title": title, "reason": "no mp4"})
                continue
            found.append({
                "url": url, "title": title, "description": (m.get("description") or "")[:500],
                "year": (m.get("date_created") or "")[:4], "minutes": mins,
                "subjects": ", ".join(m.get("keywords", [])[:10]),
                "record": make_record(f"nasa_{slug(title)}", nid, title,
                                      EVIDENCE + f" | auto-checked {meta.get('XMP:Rights') or 'no rights field'}"),
            })
    return found, rejected
