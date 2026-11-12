"""Music-edit pipeline (separate from the educational Shorts pipeline).

trends.py  - YouTube Shorts chart -> which music style is trending (songs themselves never used)
music.py   - NCS phonk / Brazilian phonk library: pick, download, verbatim credit
footage.py - NASA raw B-roll per theme: find, licence-check, download (reuses discover + download code)
editor.py  - analysis (faces/subtitles/text/sky), beat tracking, cut plan, FFmpeg render
make.py    - one edit end to end -> output/edits_review/
Run: python make_edit.py  |  daily job "edits" in run_daily.py
"""
