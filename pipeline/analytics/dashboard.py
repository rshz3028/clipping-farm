"""Build output/dashboard.html: one self-contained file (data inside, no internet, no libraries).

Everything comes from work/pipeline.db + our sidecars; no API calls here.
"""
import datetime as dt
import html
import json
from collections import Counter, defaultdict

from pipeline.core.settings import OUTPUT, ROOT
from pipeline.analytics import features, scorecard, store, studio, weekly

PAGE = OUTPUT / "dashboard.html"
TEMPLATE = ROOT / "pipeline" / "analytics" / "dashboard_template.html"


def _day(s):
    return (s or "")[:10] or None


def _days(a, b):
    a, b = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def gather():
    studio.import_all(log=lambda *_: None)
    conn = store.connect()
    try:
        features.refresh(conn)
        sc = scorecard.build(conn)
        q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]   # noqa: E731
        channel = q("SELECT * FROM yt_channel ORDER BY fetched_at")
        # per-snapshot sum of video views (the channel-level counter lags behind it)
        snap_views = q("SELECT fetched_at, SUM(views) AS v FROM yt_stats GROUP BY fetched_at ORDER BY fetched_at")
        feats = q("SELECT * FROM content_features")
        daily = q("SELECT video_id, day, views, engaged_views, subs_gained FROM yt_daily")
        sources = q("SELECT status, added_by, added_on FROM sources")
        llm = q("SELECT ts, ok, input_tokens, cache_write_tokens, cache_read_tokens, output_tokens, cost_usd "
                "FROM llm_calls")
        try:
            tracks = conn.execute("SELECT COUNT(*) FROM music_tracks").fetchone()[0]
        except Exception:
            tracks = 0
    finally:
        conn.close()

    vids = sc["videos"]
    kind_of = {v["video_id"]: v["kind"] for v in vids}
    public = [v for v in vids if v["privacy"] == "public"]
    today = dt.date.today().isoformat()

    # ── views per day by kind (YouTube Analytics) ──
    per_day = defaultdict(lambda: {"short": 0, "edit": 0})
    for d in daily:
        per_day[d["day"]][kind_of.get(d["video_id"], "short")] += d["views"] or 0
    pub_days = [_day(v["published"]) for v in public if v["published"]]
    start = min(list(per_day) + pub_days) if (per_day or pub_days) else today
    end = max(list(per_day) + [today])
    views_daily = [{"day": d, "short": per_day[d]["short"], "edit": per_day[d]["edit"]} for d in _days(start, end)]

    # ── production per day ──
    prod = defaultdict(Counter)
    for f in feats:
        if _day(f["made"]):
            prod[_day(f["made"])][f["kind"]] += 1
    for v in public:
        prod[_day(v["published"])]["published"] += 1
    p_start = min(prod) if prod else today
    production = [{"day": d, "short": prod[d]["short"], "edit": prod[d]["edit"], "published": prod[d]["published"]}
                  for d in _days(p_start, today)]

    # ── where everything is ──
    folders = Counter((f["kind"], f["folder"]) for f in feats)
    status = Counter(s["status"] for s in sources)
    pipeline = [
        {"group": "Sources", "items": [
            ["Ready to use", status.get("active", 0)], ["Used up", status.get("used", 0)],
            ["Jet B-roll (edits)", status.get("edit", 0)], ["Skipped", status.get("skipped", 0)]]},
        {"group": "Educational Shorts", "items": [
            ["Waiting for review", folders[("short", "review")]], ["Approved", folders[("short", "approved")]],
            ["Uploaded", folders[("short", "uploaded")]],
            ["Public on YouTube", sum(1 for v in public if v["kind"] == "short")]]},
        {"group": "Music edits", "items": [
            ["Waiting for review", folders[("edit", "edits_review")]], ["Approved", folders[("edit", "approved")]],
            ["Uploaded", folders[("edit", "uploaded")]],
            ["Public on YouTube", sum(1 for v in public if v["kind"] == "edit")]]},
    ]

    # ── Claude usage per day ──
    cl = defaultdict(lambda: {"calls": 0, "cost": 0.0, "tokens": 0})
    for c in llm:
        d = cl[_day(c["ts"])]
        d["calls"] += 1
        d["cost"] += c["cost_usd"] or 0
        d["tokens"] += sum((c[k] or 0) for k in ("input_tokens", "cache_write_tokens", "cache_read_tokens",
                                                 "output_tokens"))
    claude = [{"day": d, **cl[d]} for d in (_days(min(cl), today) if cl else [])]

    # ── kind comparison ──
    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        return xs[len(xs) // 2] if xs else None
    kinds = []
    for k, name in (("short", "Educational Shorts"), ("edit", "Music edits")):
        vs = [v for v in public if v["kind"] == k]
        kinds.append(dict(kind=k, name=name, count=len(vs), views=sum(v["views"] for v in vs),
                          median_views=med([v["views"] for v in vs]), median_pct=med([v["avg_view_pct"] for v in vs]),
                          median_hook=med([v["hook_ret"] for v in vs]), subs=sum(v["subs_gained"] or 0 for v in vs)))

    # ── milestones ──
    ch_last = channel[-1] if channel else {}
    total_views = max(ch_last.get("total_views") or 0, sum(v["views"] for v in vids))
    subs = ch_last.get("subscribers") or 0
    views_hist = {s["fetched_at"]: s["v"] or 0 for s in snap_views}
    for c in channel:
        views_hist[c["fetched_at"]] = max(views_hist.get(c["fetched_at"], 0), c["total_views"] or 0)
    hist = {"total_views": sorted(views_hist.items()),
            "subscribers": [(c["fetched_at"], c["subscribers"] or 0) for c in channel]}
    ms = []

    def first(label, when):
        if when:
            ms.append({"label": label, "date": _day(when), "done": True})
    first("First source licence-checked", min((s["added_on"] for s in sources if s["added_on"]), default=None))
    first("First Claude script call", min((c["ts"] for c in llm), default=None))
    first("First educational Short made", min((f["made"] for f in feats if f["kind"] == "short" and f["made"]),
                                              default=None))
    first("First video public on YouTube", min((v["published"] for v in public), default=None))
    first("First music edit made", min((f["made"] for f in feats if f["kind"] == "edit" and f["made"]), default=None))
    for metric, steps, label in (("total_views", (10, 100, 1000, 10000, 100000, 1000000), "channel views"),
                                 ("subscribers", (1, 10, 100, 1000), "subscribers")):
        now_val = total_views if metric == "total_views" else subs
        for n in steps:
            hit = next((t for t, val in hist[metric] if val >= n), None)
            if hit:
                ms.append({"label": f"{n:,} {label[:-1] if n == 1 else label}", "date": _day(hit), "done": True})
            else:
                ms.append({"label": f"{n:,} {label[:-1] if n == 1 else label}", "date": None, "done": False, "now": now_val})
                break
    ms.sort(key=lambda m: (not m["done"], m["date"] or ""))

    cutoff = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    views90 = sum(d["views"] or 0 for d in daily if d["day"] >= cutoff) if daily else sum(v["views"] for v in public)

    last_review = weekly.latest()
    is_due, why = weekly.due() if not last_review else (None, None)
    return dict(
        generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        fetched_at=sc["fetched_at"],
        channel=dict(title=ch_last.get("title") or "brokeTurboClips", subscribers=subs, total_views=total_views,
                     video_count=ch_last.get("video_count") or len(vids)),
        history=[{"t": c["fetched_at"], "views": c["total_views"], "subs": c["subscribers"]} for c in channel],
        kpi=dict(public=len(public), made=len(feats), shorts_made=sum(f["kind"] == "short" for f in feats),
                 edits_made=sum(f["kind"] == "edit" for f in feats), median_pct=sc["medians"].get("avg_view_pct"),
                 claude_cost=sum(c["cost_usd"] or 0 for c in llm), claude_calls=len(llm), tracks=tracks,
                 sources=len(sources)),
        ypp=dict(subs=subs, views90=views90),
        videos=[{k: v[k] for k in v if k != "curve"} | {"curve": v["curve"]} for v in vids],
        median_curve=sc["median_curve"], medians=sc["medians"],
        views_daily=views_daily, production=production, pipeline=pipeline, claude=claude, kinds=kinds,
        milestones=ms,
        review=dict(text=last_review.read_text(encoding="utf-8") if last_review else None,
                    name=last_review.stem if last_review else None,
                    why=None if last_review else (why if isinstance(why, str) else "due at the next run")),
    )


def build(open_browser=False):
    data = gather()
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob).replace(
        "__TITLE__", html.escape(data["channel"]["title"]))
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    if open_browser:
        import os
        os.startfile(PAGE)       # noqa: S606 (Windows: open in the default browser)
    return PAGE
