"""Finder: Prelinger Archives on the Internet Archive (archive.org).

Licence check (automatic, per item, on the item's own metadata): must be in the 'prelinger'
collection AND carry a public-domain licence URL (CC Public Domain Dedication / Mark / CC0).
Content checks: length between min/max minutes; advertising/commercial reels are skipped.
"""
import re
import urllib.parse

from pipeline.discover.finders import get_json, minutes, slug

NAME = "prelinger"
LICENCE = "Creative Commons Public Domain Dedication (licenseurl on item page)"
RESTRICTIONS = (
    "Use visuals only; mute the original soundtrack (Prelinger FAQ warns PD films may "
    "contain copyrighted music/footage). No warranty from Internet Archive. Do not show "
    "sponsor logos in a way that implies endorsement."
)
EVIDENCE = ("Item licenseurl = http://creativecommons.org/licenses/publicdomain/ ; "
            "rights FAQ https://www.panix.com/~footage/prelarch.html")
PD = ("creativecommons.org/licenses/publicdomain", "creativecommons.org/publicdomain/mark",
      "creativecommons.org/publicdomain/zero")


def make_record(source_id: str, ident: str, title: str, owner: str, evidence: str = EVIDENCE) -> dict:
    return dict(
        source_id=source_id, url=f"https://archive.org/details/{ident}", title=title, owner=owner,
        licence=LICENCE, commercial_use_allowed=1, derivatives_allowed=1,
        attribution_text=f'Footage: "{title}", Prelinger Archives / Internet Archive (public domain)',
        restrictions=RESTRICTIONS, licence_evidence=evidence,
        date_checked=__import__("time").strftime("%Y-%m-%d"),
    )


def search(cfg: dict, known: set):
    lo, hi = cfg.get("min_minutes", 5), cfg.get("max_minutes", 40)
    exclude = re.compile("|".join(cfg.get("exclude_subject_patterns", [])) or r"$^", re.I)
    found, rejected, checks = [], [], 0
    for subject_query in cfg.get("queries", []):
        qstr = f"collection:prelinger AND mediatype:movies AND ({subject_query})"
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
            {"q": qstr, "fl[]": ["identifier", "title", "description", "year", "runtime", "subject", "licenseurl", "creator"],
             "rows": 50, "sort[]": "downloads desc", "output": "json"}, doseq=True)
        for d in get_json(url)["response"]["docs"]:
            ident = d["identifier"]
            page = f"https://archive.org/details/{ident}"
            title = str(d.get("title") or ident)
            if page in known or any(f["url"] == page for f in found):
                continue
            subjects = d.get("subject", [])
            subjects = ", ".join(subjects) if isinstance(subjects, list) else str(subjects)
            if exclude.search(subjects) or exclude.search(title):
                rejected.append({"url": page, "title": title, "reason": "advertising/excluded subject"})
                continue
            mins = minutes(d.get("runtime"))
            if mins is not None and not (lo <= mins <= hi):
                rejected.append({"url": page, "title": title, "reason": f"length {mins} min outside {lo}-{hi}"})
                continue
            if checks >= int(cfg.get("max_checks", 25)):
                continue
            checks += 1
            item = get_json(f"https://archive.org/metadata/{ident}")          # verify on the item itself
            md = item.get("metadata", {})
            if mins is None:            # no runtime in the search index: use the video file's length
                lengths = [float(f["length"]) for f in item.get("files", [])
                           if f.get("name", "").endswith(".mp4") and str(f.get("length", "")).replace(".", "", 1).isdigit()]
                mins = round(max(lengths) / 60, 1) if lengths else None
                if mins is None or not (lo <= mins <= hi):
                    rejected.append({"url": page, "title": title, "reason": f"length {mins} min outside {lo}-{hi}"})
                    continue
            cols = md.get("collection", [])
            cols = [cols] if isinstance(cols, str) else cols
            lic = md.get("licenseurl", "")
            if "prelinger" not in cols or not any(p in lic for p in PD):
                rejected.append({"url": page, "title": title, "reason": f"licence not public domain: {lic or 'none'}"})
                continue
            creator = md.get("creator") or "unknown producer"
            creator = creator[0] if isinstance(creator, list) else creator
            sponsor = md.get("sponsor")
            owner = f"{creator}{f' / sponsor {sponsor}' if sponsor and sponsor != 'N/A' else ''}; Prelinger Archives"
            desc = md.get("description") or ""
            found.append({
                "url": page, "title": title, "description": re.sub(r"<[^>]+>", " ", str(desc))[:500],
                "year": str(md.get("year") or md.get("date") or "")[:4], "minutes": mins, "subjects": subjects[:200],
                "record": make_record(f"pre_{slug(title)}", ident, title, owner, EVIDENCE + f" | auto-checked {lic}"),
            })
    return found, rejected
