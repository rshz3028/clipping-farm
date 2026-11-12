"""Analytics: what happened to our videos on YouTube, linked to how we made them.

store.py      - tables (yt_* = from YouTube, content_features = from our sidecars, studio_stats = Studio CSV)
features.py   - fills content_features from output/*/*.json sidecars + the edits table
studio.py     - imports Studio-only numbers ("Shown in feed", "Viewed vs swiped away") from CSV exports
scorecard.py  - per-video scores vs the channel median + one-line diagnosis
weekly.py     - optional weekly Claude review (proposals only, never changes anything)
dashboard.py  - builds output/dashboard.html (one file, no internet needed)
"""
