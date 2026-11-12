"""Daily job: make music edits (pipeline/edits/make.py) into output/edits_review/.

Settings: [daily.edits] count (edits per day) and theme. Already-made edits today are counted in
today's run state, so re-running the day does not make extra ones. A failed edit is logged and
skipped; it never stops the rest of the daily run.
"""
from pipeline.edits.make import make_one


def run(ctx):
    count = int(ctx.cfg.get("count", 1))
    theme = ctx.cfg.get("theme", "jets")
    made = ctx.state.setdefault("edits_made", [])
    fails = 0
    while len(made) < count and fails < 2:
        ctx.log(f"edits: making {theme} edit {len(made) + 1}/{count}")
        try:
            meta = make_one(theme, log=ctx.log)
        except Exception as e:
            fails += 1
            ctx.log(f"edits: FAILED ({e})")
            continue
        made.append(meta["edit_id"])
        ctx.save()
