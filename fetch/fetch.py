#!/usr/bin/env python3
"""Rinkside data refresh.

Reads config.json, pulls schedules, scores, standings, rosters, stats and
lineups for each team, and writes small JSON files the site reads.

    python3 fetch/fetch.py                 # writes ./data
    python3 fetch/fetch.py --out _site/data --cache .cache

If one source fails, its previous data is kept and the failure is noted in
data/meta.json (the site shows it in the footer). Nothing here writes to any
other site.
"""
import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import iso_utc, norm_name, now_utc, parse_iso  # noqa: E402
import college  # noqa: E402
import iihf  # noqa: E402
import wiki  # noqa: E402
from pwhl import PWHL  # noqa: E402
from plan import plan  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cache:
    """Small JSON-file cache that survives between runs (GitHub Actions
    restores it), so finished box scores are fetched once, not every run."""

    def __init__(self, path):
        self.path = path
        os.makedirs(path, exist_ok=True)

    def _file(self, key):
        return os.path.join(self.path, key.strip("/").replace("/", "__") + ".json")

    def get(self, key, max_age_hours=None):
        f = self._file(key)
        if not os.path.exists(f):
            return None
        if max_age_hours is not None and time.time() - os.path.getmtime(f) > max_age_hours * 3600:
            return None
        try:
            with open(f) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def put(self, key, value):
        with open(self._file(key), "w") as fh:
            json.dump(value, fh, separators=(",", ":"))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _match(name, table):
    """Find a team or player in a {name: value} table despite small spelling differences."""
    n = norm_name(name)
    for k, v in table.items():
        if norm_name(k) == n:
            return v
    for k, v in table.items():
        kn = norm_name(k)
        if kn and n and (kn in n or n in kn):
            return v
    return None


def finish_team(key, team_cfg, payload, out):
    """Add captains and opponent rankings, split lineups into their own
    files, and strip private fields."""
    # Captains: what the source says, unless config.json names them.
    flags = {p["name"]: p["flag"] for p in payload.get("roster", {}).get("players", []) if p.get("flag")}
    flags.update(payload.pop("_captains", {}) or {})
    override = team_cfg.get("captains")
    if override:
        flags = {n: "C" for n in override.get("C", [])}
        flags.update({n: "A" for n in override.get("A", [])})

    def flag_of(name):
        return _match(name, flags) or "" if flags else ""
    for p in payload.get("roster", {}).get("players", []):
        p["flag"] = flag_of(p["name"])

    # Opponent ranking relative to ours.
    ranking = payload.pop("ranking", None) or {}
    ranks, us_rank = ranking.get("ranks") or {}, ranking.get("us")
    if ranking:
        payload["ranking"] = {"scope": ranking["scope"], "describe": ranking["describe"], "us": us_rank}

    lineup_dir = os.path.join(out, "lineups")
    games = []
    for g in payload.get("games", []):
        lu = g.pop("_lineup", None)
        g["team"] = key
        g["lineup"] = False
        them = g["away"] if g.get("side") == "home" else g["home"]
        r = _match(them["name"], ranks) if ranks else None
        if r and us_rank:
            g["rank"] = {"them": r, "us": us_rank, "scope": ranking["scope"]}
        if lu and any(lu.get(s, {}).get("groups") for s in ("home", "away")):
            for grp in lu.get(g.get("side"), {}).get("groups", []):
                for p in grp["players"]:
                    if flags:
                        p["flag"] = flag_of(p["name"])
            write_json(os.path.join(lineup_dir, f"{g['id']}.json"), lu)
            g["lineup"] = True
        for k in [k for k in g if k.startswith("_")]:
            g.pop(k)
        games.append(g)
    payload["games"] = games
    payload.update({"key": key, "name": team_cfg["name"], "short": team_cfg["short"],
                    "league": team_cfg["league"], "updated": iso_utc(now_utc())})
    write_json(os.path.join(out, "teams", f"{key}.json"), payload)
    return len(games)


def extra_games(cfg, key):
    """Hand-entered games from config.json (exhibitions, Rivalry Series…)."""
    out = []
    for i, g in enumerate(cfg.get("extra_games", [])):
        if g.get("team") != key:
            continue
        start = datetime.fromisoformat(g["start"]).astimezone(timezone.utc)
        us = {"name": cfg_team(cfg, key)["name"], "short": "", "score": g.get("our_score")}
        them = {"name": g["opponent"], "short": "", "score": g.get("their_score")}
        home = g.get("side", "home") == "home"
        final = g.get("our_score") is not None and g.get("their_score") is not None
        out.append({
            "id": f"extra-{key}-{i}", "comp": g.get("comp", "Exhibition"), "start": iso_utc(start), "tbd": False,
            "home": us if home else them, "away": them if home else us,
            "side": "home" if home else "away", "neutral": False, "venue": g.get("venue", ""),
            "status": "final" if final else "scheduled", "statusText": "Final" if final else "",
            "watch": g.get("watch", []), "links": g.get("links", []),
        })
    return out


def cfg_team(cfg, key):
    return next(t for t in cfg["teams"] if t["key"] == key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    ap.add_argument("--cache", default=os.path.join(ROOT, ".cache"))
    ap.add_argument("--only", help="comma-separated team keys")
    ap.add_argument("--mode", choices=["auto", "full"], default="full",
                    help="auto: fetch only the teams that need it right now (used by the scheduled run)")
    ap.add_argument("--now", help="pretend it is this UTC time (for testing the planner)")
    args = ap.parse_args()
    now = parse_iso(args.now) if args.now else now_utc()

    with open(os.path.join(ROOT, "config.json")) as fh:
        cfg = json.load(fh)
    cache = Cache(args.cache)
    os.makedirs(args.out, exist_ok=True)

    # Previous good data lives in the cache, so a failed source keeps showing it.
    last_good = os.path.join(args.cache, "last-good")
    if os.path.isdir(last_good):
        shutil.copytree(last_good, args.out, dirs_exist_ok=True)
    meta_path = os.path.join(args.out, "meta.json")
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        meta = {}
    meta.setdefault("sources", {})

    only = set(args.only.split(",")) if args.only else None
    teams = [t for t in cfg["teams"] if not only or t["key"] in only]

    if args.mode == "auto":
        due = plan(teams, args.out, meta, now)
        for k, why in due.items():
            print(f"→ {k}: {why}")
        if not due:
            print("Nothing to fetch right now — no source contacted.")
            set_output("changed", "false")
            return
        teams = [t for t in teams if t["key"] in due]

    def ok(key, label, n):
        meta["sources"][key] = {"label": label, "ok": True, "checked": iso_utc(now),
                                "updated": iso_utc(now), "games": n}
        print(f"✓ {key}: {n} games")

    def fail(key, label, err):
        prev = meta["sources"].get(key, {})
        meta["sources"][key] = {**prev, "label": label, "ok": False, "checked": iso_utc(now),
                                "error": str(err)[:300]}
        print(f"✗ {key}: {err}")
        traceback.print_exc()

    # College (College Hockey News) and PWHL (HockeyTech): one team at a time.
    pwhl = PWHL(cfg["pwhl"]) if "pwhl" in cfg else None
    for t in teams:
        try:
            if t["source"] == "chn":
                payload = college.build(t, cache)
            elif t["source"] == "pwhl":
                payload = pwhl.build(t, cache)
            else:
                continue
            payload["games"] += extra_games(cfg, t["key"])
            payload["games"].sort(key=lambda g: g["start"])
            ok(t["key"], t["source_label"], finish_team(t["key"], t, payload, args.out))
        except Exception as e:
            fail(t["key"], t["source_label"], e)

    # IIHF: one page serves every national team we follow.
    iihf_teams = [t for t in teams if t["source"] == "iihf"]
    if iihf_teams:
        try:
            # iihf.com blocks cloud servers, so Wikipedia is the default source.
            mod = iihf if cfg["iihf"].get("source") == "iihf" else wiki
            res = mod.build_event(cfg["iihf"], iihf_teams, cache, cfg["iihf"].get("watch", []))
            for t in iihf_teams:
                payload = res[t["key"]]
                payload["games"] += extra_games(cfg, t["key"])
                payload["games"].sort(key=lambda g: g["start"])
                payload["event"] = cfg["iihf"]["name"]
                ok(t["key"], t["source_label"], finish_team(t["key"], t, payload, args.out))
        except Exception as e:
            for t in iihf_teams:
                fail(t["key"], t["source_label"], e)

    meta["generated"] = iso_utc(now)
    meta["timezone"] = cfg.get("display_timezone", "America/New_York")
    meta["teams"] = [{"key": t["key"], "name": t["name"], "short": t["short"], "league": t["league"],
                      "color": t.get("color", "")} for t in cfg["teams"]]
    write_json(meta_path, meta)

    # Save this run's output as the new fallback.
    shutil.copytree(args.out, last_good, dirs_exist_ok=True)
    bad = [k for k, v in meta["sources"].items() if not v.get("ok")]
    print("done" + (f" — problems with: {', '.join(bad)}" if bad else ""))
    set_output("changed", "true")


def set_output(name, value):
    """Tell the GitHub workflow whether to publish."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
