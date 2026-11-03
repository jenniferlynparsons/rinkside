#!/usr/bin/env python3
"""Checks the fetch planner: when does a scheduled run contact a source?

    python3 fetch/tests/test_plan.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from common import parse_iso  # noqa: E402
from plan import plan  # noqa: E402

TEAMS = [{"key": "princeton", "source": "chn"}, {"key": "sirens", "source": "pwhl"},
         {"key": "usa", "source": "iihf"}]


def game(gid, start, status="scheduled"):
    return {"id": gid, "start": start, "status": status}


def setup(tmp):
    os.makedirs(os.path.join(tmp, "teams"), exist_ok=True)
    data = {
        # Princeton at home Friday Nov 6, 6 pm ET (23:00 UTC)
        "princeton": [game("ncaa-1031", "2026-10-31T19:00:00Z", "final"), game("ncaa-1106", "2026-11-06T23:00:00Z")],
        # Sirens open Dec 6, 3 pm ET
        "sirens": [game("pwhl-369", "2026-12-06T20:00:00Z")],
        # USA vs Switzerland Nov 6, 1 pm ET (18:00 UTC)
        "usa": [game("iihf-13547", "2026-11-06T18:00:00Z"), game("iihf-13551", "2026-11-08T14:00:00Z")],
    }
    for k, games in data.items():
        with open(os.path.join(tmp, "teams", f"{k}.json"), "w") as fh:
            json.dump({"games": games}, fh)


def meta(updated, **over):
    m = {"sources": {k: {"ok": True, "updated": updated, "checked": updated} for k in ("princeton", "sirens", "usa")}}
    for k, v in over.items():
        m["sources"][k].update(v)
    return m


def run(tmp, now, m):
    return plan(TEAMS, tmp, m, parse_iso(now))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        setup(tmp)
        cases = [
            # (description, now, meta, expected keys)
            ("quiet afternoon, everything fetched this morning",
             "2026-11-04T19:00:00Z", meta("2026-11-04T11:10:00Z"), set()),
            ("first run after midnight: too early for the daily refresh",
             "2026-11-05T09:00:00Z", meta("2026-11-04T11:10:00Z"), set()),
            ("6:07 am ET: daily refresh for college and PWHL, IIHF too (Worlds is near)",
             "2026-11-05T11:07:00Z", meta("2026-11-04T11:10:00Z"), {"princeton", "sirens", "usa"}),
            ("an hour before USA plays: no pre-game fetch (Wikipedia has no game-day lineups)",
             "2026-11-06T17:00:00Z", meta("2026-11-06T11:10:00Z"), set()),
            ("an hour before the Sirens play: lineups",
             "2026-12-06T19:00:00Z", meta("2026-12-06T11:10:00Z"), {"sirens"}),
            ("lineups already fetched; game in progress: leave it alone",
             "2026-11-06T19:30:00Z", meta("2026-11-06T16:50:00Z"), set()),
            ("USA game should be over",
             "2026-11-06T20:37:00Z", meta("2026-11-06T16:50:00Z"), {"usa"}),
            ("checked at 20:37, still no final: wait before asking again",
             "2026-11-06T21:07:00Z", meta("2026-11-06T20:37:00Z"), set()),
            ("…then try again an hour later",
             "2026-11-06T21:37:00Z", meta("2026-11-06T20:37:00Z"), {"usa"}),
            ("no pre-game fetch for college (no lineups until the box score)",
             "2026-11-06T22:07:00Z", meta("2026-11-06T21:40:00Z"), set()),
            ("(the USA result came in)", None, None, None),
            ("Princeton game should be over",
             "2026-11-07T01:37:00Z", meta("2026-11-06T21:40:00Z"), {"princeton"}),
            ("failed source rests for two hours",
             "2026-11-07T01:37:00Z", meta("2026-11-06T21:40:00Z", princeton={"ok": False, "checked": "2026-11-07T01:07:00Z"}), set()),
            ("between tournaments IIHF is checked weekly, not daily",
             "2027-02-10T12:07:00Z", meta("2027-02-09T11:10:00Z", usa={"updated": "2027-02-05T11:10:00Z"}), {"princeton", "sirens"}),
            ("…and once a week has passed",
             "2027-02-13T12:07:00Z", meta("2027-02-13T11:10:00Z", usa={"updated": "2027-02-05T11:10:00Z"}), {"usa"}),
        ]
        failed = 0
        for desc, now, m, expected in cases:
            if now is None:  # the last fetch brought in the USA final
                p = os.path.join(tmp, "teams", "usa.json")
                d = json.load(open(p))
                d["games"][0]["status"] = "final"
                json.dump(d, open(p, "w"))
                continue
            got = run(tmp, now, m)
            ok = set(got) == expected
            failed += not ok
            print(("✓" if ok else "✗"), desc, "→", got or "nothing")
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
