"""Daily job: find and add new sources when the supply of unused ones runs low."""
from pipeline.core import registry
from pipeline.core.shorts import source_exhausted
from pipeline.discover import discover


def run(ctx):
    active = [r["source_id"] for r in registry.approved_sources("active")]
    fresh = [s for s in active if not source_exhausted(s)]
    want = int(ctx.cfg.get("min_fresh_sources", 4))
    if len(fresh) >= want:
        ctx.log(f"discover: {len(fresh)} unused sources available (minimum {want}), nothing to do")
        return
    ctx.log(f"discover: only {len(fresh)} unused sources (minimum {want}); searching archives")
    added = discover(max_new=int(ctx.cfg.get("max_new", 5)), log=ctx.log)
    ctx.state.setdefault("discovered", []).extend(added)
    ctx.save()
    ctx.log(f"discover: added {len(added)} new sources")
