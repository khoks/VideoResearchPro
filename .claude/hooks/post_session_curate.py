"""Stop hook — nudges Claude to run /knowledge-curator and /work-tracker
once per session, so substantive design discussions and work-state changes
get persisted to the docs and the initiatives file before the session ends.

Triggered by `.claude/settings.json` on the Stop event.

Loop-safety: Claude Code sets `stop_hook_active=true` in the JSON payload
on subsequent Stop events that were themselves caused by a prior block.
We exit silently in that case so we never recurse.

The hook is intentionally *light* — it never inspects the transcript itself
to decide relevance. The skills are responsible for being no-ops on tactical
sessions. Keeping the trigger dumb keeps the loop simple and predictable.
"""

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if payload.get("stop_hook_active"):
        return 0

    reason = (
        "Before this session ends, run the project's two persistence skills "
        "so any substantive content from this conversation lands in the repo:\n\n"
        "1. Invoke `/knowledge-curator` — captures vision, architecture, "
        "tech-stack, scaling, and decision content into the canonical docs "
        "(`docs/feature-roadmap.md`, `docs/architecture.md`, "
        "`docs/source-types.md`, `docs/decisions.md`, etc.) and opens a PR.\n\n"
        "2. Invoke `/work-tracker` — updates `docs/initiatives.md` with "
        "status changes on existing items, new stories/tasks for newly-discussed "
        "work, and links to any decisions just recorded; opens a PR.\n\n"
        "Both skills are allowed to be no-ops if the session was purely "
        "tactical (a bug fix, a one-off command, a question without "
        "design content). If neither skill has anything to record, "
        "stop normally without comment.\n\n"
        "Do not invoke a third time after both skills have run."
    )

    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
