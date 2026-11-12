"""What music is trending on Shorts: YouTube Charts "Weekly Top Songs on Shorts" (public, no login).

The chart's songs are copyrighted, so they are never downloaded or used. They only steer the STYLE
of the licensed track we pick (e.g. phonk vs. Brazilian funk). Cached per day in work/edits/trends/.
"""
import json
import re
import time
import urllib.request

from pipeline.core.settings import WORK

CACHE = WORK / "edits" / "trends"
URL = "https://charts.youtube.com/youtubei/v1/browse?alt=json"

# chart-title keywords -> style buckets that map to music-library genres (see music.GENRES)
STYLE_WORDS = {
    "brazilian_phonk": r"montagem|funk|brazil|bra[sz]il|automotivo|\bmtg\b|ela peida",
    "phonk": r"phonk|slowed|hardtekk|drift|cowbell|\bmeow\b|tokyo",
}


def shorts_chart(country: str = "us") -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{time.strftime('%Y-%m-%d')}_{country}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    body = {"context": {"client": {"clientName": "WEB_MUSIC_ANALYTICS", "clientVersion": "2.0", "hl": "en",
                                   "gl": country.upper()}},
            "browseId": "FEmusic_analytics_charts_home",
            "query": f"perspective=CHART_DETAILS&chart_params_country_code={country}"
                     "&chart_params_chart_type=SHORTS_TRACKS_BY_USAGE&chart_params_period_type=WEEKLY"}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Origin": "https://charts.youtube.com",
                                          "Referer": "https://charts.youtube.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)

    def find(o, k):
        if isinstance(o, dict):
            if k in o:
                yield o[k]
            for v in o.values():
                yield from find(v, k)
        elif isinstance(o, list):
            for v in o:
                yield from find(v, k)

    rows = next(find(data, "trackViews"), [])
    out = [dict(rank=t["chartEntryMetadata"]["currentPosition"], title=t["name"],
                artists=", ".join(a["name"] for a in t.get("artists", [])),
                weeks=t["chartEntryMetadata"].get("periodsOnChart"),
                video_id=t.get("encryptedVideoId")) for t in rows]
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def style_weights(chart: list[dict]) -> dict:
    """Rank-weighted share of each style among chart songs (top songs count more)."""
    w = {k: 0.0 for k in STYLE_WORDS}
    for t in chart:
        text = f"{t['title']} {t['artists']}".lower()
        for style, rx in STYLE_WORDS.items():
            if re.search(rx, text):
                w[style] += 1.0 / (1 + t["rank"] / 20)
    return w
