"""Command line for the Shorts pipeline.

    python -m pipeline sources                       show the source registry
    python -m pipeline seed                          (re)load the hand-checked sources
    python -m pipeline stages                        list stages and which implementation each uses
    python -m pipeline run <stage> <id> [--force]    run one stage (skips if already up to date)
    python -m pipeline source <source_id> [--force]  run all source-level stages for one source
    python -m pipeline discover [max_new]            search archives and add qualifying sources
    python -m pipeline shorts <source_id>           create Short folders for scripts that passed the check
    python -m pipeline short <short_id> [--force]    run all Short-level stages (narrate ... package)
    python -m pipeline status <id>                   show which stages are done / out of date
"""
import sys

from pipeline.core import registry, runner
from pipeline.core.stage import STAGE_ORDER, Unit, load_stage


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    if cmd == "_child":                       # internal: runner's child process
        runner.run_stage_inprocess(args[0], args[1])
    elif cmd == "sources":
        registry.print_table()
    elif cmd == "seed":
        from pipeline.seed_sources import seed
        seed()
    elif cmd == "stages":
        for s in STAGE_ORDER:
            sp = load_stage(s)
            print(f"  {s:12} [{sp.level:6}] impl={sp.impl_name:16} {sp.inputs} -> {sp.outputs}")
    elif cmd == "run":
        runner.run(args[0], args[1], force=force)
    elif cmd == "source":
        for s in STAGE_ORDER:
            if load_stage(s).level == "source":
                runner.run(s, args[0], force=force)
    elif cmd == "discover":
        from pipeline.discover import discover
        added = discover(max_new=int(args[0]) if args else None)
        print(f"Added {len(added)} sources: {', '.join(added) or '-'}")
    elif cmd == "shorts":
        from pipeline.core.shorts import materialize
        for sid in materialize(args[0]):
            print(" ", sid)
    elif cmd == "short":
        for s in STAGE_ORDER:
            if load_stage(s).level == "short":
                runner.run(s, args[0], force=force)
    elif cmd == "status":
        u = Unit(args[0])
        for s in STAGE_ORDER:
            if load_stage(s).level == u.kind:
                print(f"  {s:12} {'up to date' if runner.is_current(u, s) else 'needs to run'}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    from pipeline.core.claude_cli import BrainError
    try:
        sys.exit(main(sys.argv[1:]))
    except BrainError as e:
        msg = str(e).lower()
        print(f"STOPPED: {e}")
        limited = any(s in msg for s in ("usage limit", "rate limit", "limit reached", "429", "overloaded"))
        sys.exit(runner.EXIT_USAGE_LIMIT if limited else 1)
    except (registry.SourceNotApproved, runner.StageFailed) as e:
        print(f"STOPPED: {e}")
        sys.exit(2)
