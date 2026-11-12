"""Per-video scorecard: numbers at fixed ages, compared with the channel median, plus a diagnosis.

Method (what works for Shorts channels, see CLAUDE.md issue 15):
  * compare with OUR channel's median, not internet benchmarks (YouTube publishes none)
  * compare at the same age (views in the first 2 and first 7 days), so new videos aren't punished
  * outlier score = views / channel median (2.0 = twice a typical video)
  * diagnose in order, one problem at a time:
      not shown in feed -> topic/niche;  swiped away / early drop -> first 2-3 s;
      steady slide -> pacing;  good retention but small reach -> bigger topic;
      reach without subscribers -> conversion
"""
import datetime as dt
import json
import statistics

from pipeline.core.settings import CONFIG
from pipeline.analytics import store

CFG = CONFIG.get("analytics", {})
MIN_VIEWS = CFG.get("min_views_to_judge", 30)
HOOK_SECONDS = CFG.get("hook_seconds", 3)


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _date(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def _point(curve, ratio):
    """watch ratio at the curve point nearest to `ratio`."""
    if not curve:
        return None
    return min(curve, key=lambda p: abs(p[0] - ratio))[1]


def build(conn=None):
    own = conn is None
    conn = conn or store.connect()
    try:
        last = conn.execute("SELECT MAX(fetched_at) FROM yt_stats").fetchone()[0]
        if not last:
            return dict(videos=[], medians={}, median_curve=[], fetched_at=None)
        stats = [dict(r) for r in conn.execute("SELECT * FROM yt_stats WHERE fetched_at=?", (last,))]
        feats = {r["short_id"]: dict(r) for r in conn.execute("SELECT * FROM content_features")}
        by_yt = {f["youtube_id"]: f for f in feats.values() if f.get("youtube_id")}
        daily = {}
        for r in conn.execute("SELECT video_id, day, views, engaged_views, subs_gained FROM yt_daily ORDER BY day"):
            daily.setdefault(r["video_id"], []).append(dict(r))
        curves = {}
        for r in conn.execute("SELECT video_id, ratio, watch_ratio, rel_perf FROM yt_retention ORDER BY ratio"):
            curves.setdefault(r["video_id"], []).append((r["ratio"], r["watch_ratio"], r["rel_perf"]))
        studio = {}
        for r in conn.execute("SELECT video_id, shown_in_feed, viewed_pct FROM studio_stats "
                              "ORDER BY COALESCE(shown_in_feed, 0)"):
            studio[r["video_id"]] = dict(r)      # largest export (= longest period) wins
    finally:
        if own:
            conn.close()

    today = dt.date.today()
    vids = []
    for s in stats:
        vid = s["video_id"]
        f = feats.get(s["short_id"]) or by_yt.get(vid) or {}
        pub = _date(s["published_at"])
        age = (today - pub).days if pub else None
        dur = s["duration_s"] or f.get("duration_s")
        days = daily.get(vid, [])
        last_day = _date(days[-1]["day"]) if days else None

        def upto(n):  # views in the first n days, only if analytics already covers them
            if not (pub and last_day) or last_day < pub + dt.timedelta(days=n - 1):
                return None
            return sum(d["views"] or 0 for d in days if _date(d["day"]) <= pub + dt.timedelta(days=n - 1))

        curve = curves.get(vid, [])
        hook = mid = end = rel = None
        if curve and dur:
            pts = [(c[0], c[1]) for c in curve]
            hook = _point(pts, min(HOOK_SECONDS / dur, 1.0))
            mid = _point(pts, 0.5)
            end = pts[-1][1]
            rels = [c[2] for c in curve if c[2] is not None]
            rel = sum(rels) / len(rels) if rels else None
        loc = json.loads(s.get("location_json") or "{}")
        loc = {k: v for k, v in loc.items() if isinstance(v, (int, float))}
        feed_share = (loc.get("SHORTS_FEED", 0) / sum(loc.values())) if loc and sum(loc.values()) else None
        st = studio.get(vid, {})
        views = s["views"] or 0
        subs = s["a_subs_gained"]
        vids.append(dict(
            video_id=vid, short_id=s["short_id"], title=s["title"], privacy=s["privacy"],
            kind=f.get("kind") or ("edit" if "#" in (s["title"] or "") else "short"),
            topic=f.get("topic"), hook_text=f.get("hook"), track=f.get("track"), music_style=f.get("music_style"),
            published=s["published_at"], age_days=age, duration_s=dur,
            views=views, engaged_views=s.get("engaged_views"), likes=s["likes"], comments=s["comments"],
            shares=s["a_shares"], subs_gained=subs, avg_view_pct=s["a_avg_view_pct"], avg_view_s=s["a_avg_view_s"],
            views_d2=upto(2), views_d7=upto(7),
            hook_ret=hook, mid_ret=mid, end_ret=end, rel_perf=rel, feed_share=feed_share,
            shown_in_feed=st.get("shown_in_feed"), viewed_pct=st.get("viewed_pct"),
            subs_per_1k=(subs / views * 1000) if (subs is not None and views) else None,
            curve=[[round(c[0], 3), round(c[1], 3)] for c in curve],
        ))

    public = [v for v in vids if v["privacy"] == "public"]
    med = {k: _median([v[k] for v in public]) for k in
           ("views_d2", "views_d7", "views", "avg_view_pct", "hook_ret", "mid_ret", "viewed_pct", "rel_perf")}
    for v in vids:
        for n in ("d2", "d7"):
            m = med.get(f"views_{n}")
            v[f"outlier_{n}"] = (v[f"views_{n}"] / m) if (m and v[f"views_{n}"] is not None) else None
        v["diagnosis"] = diagnose(v, med, len(public))
    # median retention curve over public videos (by curve point)
    buckets = {}
    for v in public:
        for r, w in v["curve"]:
            buckets.setdefault(round(r, 2), []).append(w)
    median_curve = [[r, round(statistics.median(ws), 3)] for r, ws in sorted(buckets.items())]
    return dict(videos=vids, medians=med, median_curve=median_curve, fetched_at=last)


def diagnose(v, med, n_public):
    """One problem at a time, in the order that matters. level: good | info | warning | serious"""
    if v["privacy"] != "public":
        return dict(level="info", code="not_public", label="Not public",
                    advice="Private/unlisted videos get no feed traffic; nothing to judge.")
    if v["age_days"] is not None and v["age_days"] < 2:
        return dict(level="info", code="too_early", label="Too early",
                    advice="Wait 2 days: Shorts are tested on small audiences first and Analytics lags 1-3 days.")
    rel_ok = n_public >= 5          # channel medians mean little with fewer videos
    views = v["engaged_views"] if v["engaged_views"] is not None else v["views"]
    shown, share = v["shown_in_feed"], v["feed_share"]
    barely = (shown is not None and shown < 100) or \
             (shown is None and views < MIN_VIEWS and (share is None or share < 0.5))
    if barely:
        return dict(level="serious", code="no_distribution", label="Barely shown",
                    advice="YouTube hardly showed it in the Shorts feed. Topic/niche problem, or the channel "
                           "is still new: keep posting in ONE niche, pick topics people already search for.")
    if views < MIN_VIEWS:
        return dict(level="info", code="low_data", label="Too few views",
                    advice=f"Under {MIN_VIEWS} views: numbers are noise. Judge later or by the group.")
    vp, hk = v["viewed_pct"], v["hook_ret"]
    if (vp is not None and vp < (med["viewed_pct"] * 0.9 if rel_ok and med["viewed_pct"] else 60)) or \
       (hk is not None and hk < (med["hook_ret"] * 0.9 if rel_ok and med["hook_ret"] else 0.7)):
        return dict(level="serious", code="hook", label="Weak hook",
                    advice="Viewers leave in the first 2-3 s. Change the first frame and the first line "
                           "(clearer question, more striking shot, text on screen at once).")
    if hk and v["mid_ret"] is not None and v["mid_ret"] / hk < 0.6:
        return dict(level="warning", code="pacing", label="Slow middle",
                    advice="Big drop before the middle: get to the answer sooner, cut filler sentences, or shorten.")
    o = v["outlier_d7"] if v["outlier_d7"] is not None else v["outlier_d2"]
    if v["avg_view_pct"] is not None and v["avg_view_pct"] >= 80 and o is not None and o < 1:
        return dict(level="warning", code="small_topic", label="Small topic",
                    advice="People who see it watch it, but it isn't spreading: same format, bigger/more famous topic.")
    if views >= 500 and v["subs_per_1k"] is not None and v["subs_per_1k"] < 1:
        return dict(level="warning", code="no_conversion", label="No new subs",
                    advice="Reach without subscribers: end with a reason to follow (series, 'part 2'), keep one niche.")
    if o is not None and o >= 2:
        return dict(level="good", code="outlier", label="Winner",
                    advice="Well above your typical video: make more like this (topic, opening, length).")
    return dict(level="good", code="ok", label="Normal",
                advice="No clear problem. Keep going; compare once there are more videos.")


def print_report():
    data = build()
    if not data["videos"]:
        print("No analytics yet. Run: python fetch_analytics.py")
        return
    f = lambda x, n=0, pct=False: "-" if x is None else (f"{x * 100:.{n}f}%" if pct else f"{x:.{n}f}")  # noqa: E731
    print(f"\nScorecard (snapshot {data['fetched_at']}; medians over public videos)\n")
    print(f"{'views':>6} {'d2':>5} {'d7':>5} {'xMed':>5} {'%view':>6} {'hook':>5} {'mid':>5} {'feed':>5}  "
          f"{'diagnosis':14} title")
    for v in sorted(data["videos"], key=lambda v: v["published"] or "", reverse=True):
        o = v["outlier_d7"] if v["outlier_d7"] is not None else v["outlier_d2"]
        print(f"{v['views']:>6} {f(v['views_d2']):>5} {f(v['views_d7']):>5} {f(o, 1):>5} {f(v['avg_view_pct']):>6} "
              f"{f(v['hook_ret'], 0, True):>5} {f(v['mid_ret'], 0, True):>5} {f(v['feed_share'], 0, True):>5}  "
              f"{v['diagnosis']['label']:14} {(v['title'] or '')[:55]}")
    print("\nxMed = views vs the channel median at the same age; hook = still watching at "
          f"{HOOK_SECONDS}s; feed = share of views from the Shorts feed.")
