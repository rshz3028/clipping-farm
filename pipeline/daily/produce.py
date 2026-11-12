"""Daily job: make Shorts until today's target is reached."""
from pipeline.core import registry, runner
from pipeline.core.settings import WORK
from pipeline.core.shorts import is_packaged, materialize, pending_shorts, source_exhausted
from pipeline.core.stage import STAGE_ORDER, load_stage

SOURCE_STAGES = [s for s in STAGE_ORDER if load_stage(s).level == "source"]
SHORT_STAGES = [s for s in STAGE_ORDER if load_stage(s).level == "short"]


def _make_short(ctx, short_id):
    try:
        for s in SHORT_STAGES:
            runner.run(s, short_id)
    except (runner.UsageLimit, KeyboardInterrupt):
        raise
    except Exception as e:
        ctx.state["failed"][short_id] = str(e)[:300]
        ctx.save()
        ctx.log(f"SKIPPED {short_id}: {e}")
        return
    ctx.state["made"].append(short_id)
    ctx.save()
    ctx.log(f"FINISHED {short_id}  ({len(ctx.state['made'])}/{ctx.state['target']} today)")


def _source_order(only):
    ids = [r["source_id"] for r in registry.approved_sources("active")]
    if only:
        ids = [i for i in ids if i in only]
    ids = [i for i in ids if not source_exhausted(i)]
    started = [i for i in ids if (WORK / "sources" / i / ".stages").exists()]
    return started + [i for i in ids if i not in started]          # in-progress sources first


def run(ctx):
    only = ctx.args.source
    for sid in pending_shorts():                     # 1. finish half-made Shorts first
        if ctx.need() <= 0:
            return
        if only and sid.split("__")[0] not in only:
            continue
        _make_short(ctx, sid)

    for src in _source_order(only):                  # 2. then new material
        if ctx.need() <= 0:
            return
        if src in ctx.state["failed"]:
            continue
        try:
            for s in SOURCE_STAGES:
                runner.run(s, src)
            new = [sid for sid in materialize(src) if not is_packaged(sid)]
        except (runner.UsageLimit, KeyboardInterrupt):
            raise
        except Exception as e:
            ctx.state["failed"][src] = str(e)[:300]
            ctx.save()
            ctx.log(f"SKIPPED source {src}: {e}")
            continue
        if not new:
            ctx.log(f"{src}: no passing scripts left to make")
        for sid in new:
            if ctx.need() <= 0:
                return
            if sid not in ctx.state["failed"]:
                _make_short(ctx, sid)
    if ctx.need() > 0:
        ctx.log("produce: ran out of usable sources (the discover job adds more next run)")
