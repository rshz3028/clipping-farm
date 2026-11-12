"""Record YouTube performance of every video on the channel (read-only).

    python fetch_analytics.py            fetch + save a snapshot + print a table
    python fetch_analytics.py --show     print the last saved snapshot only (no API calls)

Uses the official YouTube Data API (public counts: views/likes/comments) and the
YouTube Analytics API (watch time, average % viewed, shares, subs gained, traffic sources).
Each run appends one snapshot per video to work/pipeline.db (table yt_stats), so the
history builds up if you run it daily. Videos are linked to our own sidecar .json
(by YouTube ID, or by title for Shorts uploaded by hand in Studio).

Sign-in: uses its OWN token (secrets/youtube_read_token.json) with read-only permissions,
so the upload token is untouched. The first run opens a browser: pick the brokeTurboClips account.
Note: YouTube Analytics numbers lag by about 1-3 days.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
if Path(sys.prefix).resolve() != VENV.resolve():
    sys.exit(subprocess.call([str(VENV / "Scripts" / "python.exe"), str(Path(__file__).resolve()), *sys.argv[1:]]))

from pipeline.core import registry                      # noqa: E402
from pipeline.core.settings import CONFIG, OUTPUT       # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
CFG = CONFIG.get("upload", {})
TOKEN = ROOT / "secrets" / "youtube_read_token.json"
METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage",
           "likes", "comments", "shares", "subscribersGained", "subscribersLost"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS yt_stats (
    video_id TEXT, fetched_at TEXT, title TEXT, published_at TEXT, privacy TEXT,
    duration_s REAL, short_id TEXT,
    views INTEGER, likes INTEGER, comments INTEGER,             -- public counters (live)
    a_views INTEGER, a_minutes REAL, a_avg_view_s REAL, a_avg_view_pct REAL,
    a_likes INTEGER, a_comments INTEGER, a_shares INTEGER, a_subs_gained INTEGER, a_subs_lost INTEGER,
    traffic_json TEXT,                                          -- views per traffic source
    PRIMARY KEY (video_id, fetched_at)
);
"""


def clients(no_login=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secret = ROOT / CFG.get("client_secret", "secrets/client_secret.json")
    if not secret.exists():
        sys.exit(f"Missing {secret}.")
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif no_login:
            sys.exit(r"Read sign-in missing or expired. Run: .\.venv\Scripts\python.exe fetch_analytics.py")
        else:
            print("A browser window will open: sign in as the brokeTurboClips account and allow read access.")
            creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds), build("youtubeAnalytics", "v2", credentials=creds)


def iso_dur(s):
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def sidecar_index():
    """Our own sidecars: youtube id -> short_id, and normalised title -> short_id."""
    by_id, by_title = {}, {}
    for side in OUTPUT.glob("*/*.json"):
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = side.stem
        if meta.get("youtube_video_id"):
            by_id[meta["youtube_video_id"]] = sid
        if meta.get("title"):
            by_title[meta["title"].strip().lower()] = sid
    return by_id, by_title


def channel_videos(yt):
    ch = yt.channels().list(part="id,snippet,contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Channel: {ch['snippet']['title']} ({ch['id']})")
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                    maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        tok = r.get("nextPageToken")
        if not tok:
            break
    vids = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,statistics,status,contentDetails", id=",".join(ids[i:i + 50])).execute()
        vids += r["items"]
    return ch["id"], vids


def analytics(ya, video_ids, start):
    end = dt.date.today().isoformat()
    out = {}
    for i in range(0, len(video_ids), 200):
        chunk = video_ids[i:i + 200]
        r = ya.reports().query(ids="channel==MINE", startDate=start, endDate=end, dimensions="video",
                               metrics=",".join(METRICS), filters="video==" + ",".join(chunk),
                               sort="-views", maxResults=200).execute()
        cols = [c["name"] for c in r.get("columnHeaders", [])]
        for row in r.get("rows", []):
            rec = dict(zip(cols, row))
            out[rec["video"]] = rec
    traffic = {}
    for vid in video_ids:
        try:
            r = ya.reports().query(ids="channel==MINE", startDate=start, endDate=end,
                                   dimensions="insightTrafficSourceType", metrics="views",
                                   filters=f"video=={vid}").execute()
            traffic[vid] = {row[0]: row[1] for row in r.get("rows", [])}
        except Exception as e:
            traffic[vid] = {"error": str(e)[:200]}
    return out, traffic


def save(rows):
    with registry.connect() as conn:
        conn.executescript(SCHEMA)
        cols = list(rows[0].keys())
        conn.executemany(f"INSERT OR REPLACE INTO yt_stats ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [tuple(r[c] for c in cols) for r in rows])


def show():
    with registry.connect() as conn:
        conn.executescript(SCHEMA)
        last = conn.execute("SELECT MAX(fetched_at) FROM yt_stats").fetchone()[0]
        if not last:
            print("No snapshots yet. Run without --show first.")
            return
        rows = conn.execute("SELECT title, privacy, duration_s, views, a_avg_view_pct, a_avg_view_s, likes, "
                            "a_shares, a_subs_gained, traffic_json FROM yt_stats WHERE fetched_at=? "
                            "ORDER BY published_at DESC", (last,)).fetchall()
    print(f"\nSnapshot {last}  (analytics columns lag 1-3 days)\n")
    print(f"{'views':>6} {'%view':>6} {'avg s':>6} {'len':>4} {'likes':>5} {'share':>5} {'subs':>4}  {'privacy':8} title")
    for t, p, d, v, pct, avg, lk, sh, sub, tr in rows:
        f = lambda x, n=0: "-" if x is None else f"{x:.{n}f}"   # noqa: E731
        print(f"{f(v):>6} {f(pct):>6} {f(avg):>6} {f(d):>4} {f(lk):>5} {f(sh):>5} {f(sub):>4}  {p:8} {t[:60]}")
        traffic = json.loads(tr or "{}")
        if traffic and "error" not in traffic:
            print(f"{'':>40}traffic: " + ", ".join(f"{k}={n}" for k, n in sorted(traffic.items(), key=lambda x: -x[1])))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-login", action="store_true", help="never open a browser (for unattended runs)")
    args = ap.parse_args()
    if args.show:
        show()
        return 0

    from googleapiclient.errors import HttpError
    yt, ya = clients(args.no_login)
    _, vids = channel_videos(yt)
    if not vids:
        print("No videos on this channel.")
        return 0
    by_id, by_title = sidecar_index()
    start = min(v["snippet"]["publishedAt"][:10] for v in vids)
    try:
        an, traffic = analytics(ya, [v["id"] for v in vids], start)
    except HttpError as e:
        print(f"Analytics API failed (public counts are still saved): {str(e)[:300]}")
        if "accessNotConfigured" in str(e) or "has not been used" in str(e):
            print("-> Enable 'YouTube Analytics API' in Google Cloud Console for this project, then re-run.")
        an, traffic = {}, {}

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for v in vids:
        s, a = v.get("statistics", {}), an.get(v["id"], {})
        title = v["snippet"]["title"]
        rows.append(dict(
            video_id=v["id"], fetched_at=now, title=title, published_at=v["snippet"]["publishedAt"],
            privacy=v["status"]["privacyStatus"], duration_s=iso_dur(v["contentDetails"].get("duration")),
            short_id=by_id.get(v["id"]) or by_title.get(title.strip().lower()),
            views=int(s.get("viewCount", 0)), likes=int(s.get("likeCount", 0)), comments=int(s.get("commentCount", 0)),
            a_views=a.get("views"), a_minutes=a.get("estimatedMinutesWatched"),
            a_avg_view_s=a.get("averageViewDuration"), a_avg_view_pct=a.get("averageViewPercentage"),
            a_likes=a.get("likes"), a_comments=a.get("comments"), a_shares=a.get("shares"),
            a_subs_gained=a.get("subscribersGained"), a_subs_lost=a.get("subscribersLost"),
            traffic_json=json.dumps(traffic.get(v["id"], {})),
        ))
    save(rows)
    print(f"Saved {len(rows)} videos to yt_stats.")
    show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
