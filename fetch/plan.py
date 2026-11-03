"""Decide which teams are worth fetching right now.

The GitHub Action wakes up every 30 minutes, but most wake-ups end here
without contacting any source. A team is fetched only when:

  * it has never been fetched, or
  * it hasn't been refreshed yet today (after 6 a.m. Eastern) — this picks up
    schedule changes, TV listings, rosters and standings, or
  * a PWHL or IIHF game starts within the next 75 minutes (lineups are
    posted about an hour before puck drop), or
  * one of its games should be over by now and we don't have the final yet.

IIHF teams are only refreshed daily while a tournament is near; otherwise
weekly. A source that failed is left alone for two hours before retrying.
"""
import json
import os
from datetime import timedelta

from common import ET, parse_iso

GAME_LENGTH = timedelta(hours=2, minutes=30)   # puck drop to final horn, roughly
GIVE_UP_AFTER = timedelta(hours=12)            # postponed? the daily refresh will catch it
RETRY_EVERY = timedelta(minutes=55)            # if the final isn't posted yet
PREGAME = timedelta(minutes=75)
FAILED_BACKOFF = timedelta(hours=2)
DAILY_HOUR_ET = 6


def _load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def plan(teams, out_dir, meta, now):
    due = {}
    for t in teams:
        key = t["key"]
        src = meta.get("sources", {}).get(key, {})
        data = _load(os.path.join(out_dir, "teams", f"{key}.json"))
        updated = parse_iso(src["updated"]) if src.get("updated") else None
        checked = parse_iso(src["checked"]) if src.get("checked") else None

        if data is None or updated is None:
            due[key] = "first fetch"
            continue
        if src.get("ok") is False and checked and now - checked < FAILED_BACKOFF:
            continue  # give a struggling source a rest

        games = data.get("games", [])
        reason = None

        # Daily refresh (weekly for IIHF teams between tournaments).
        now_et = now.astimezone(ET)
        if t["source"] == "iihf":
            near = any(-timedelta(days=2) <= parse_iso(g["start"]) - now <= timedelta(days=14) for g in games)
            if near and updated.astimezone(ET).date() < now_et.date() and now_et.hour >= DAILY_HOUR_ET:
                reason = "daily refresh during the tournament"
            elif not near and now - updated >= timedelta(days=7):
                reason = "weekly check for new tournament info"
        elif updated.astimezone(ET).date() < now_et.date() and now_et.hour >= DAILY_HOUR_ET:
            reason = "daily refresh"

        for g in games:
            if reason:
                break
            if g.get("status") == "final":
                continue
            start = parse_iso(g["start"])
            if t["source"] in ("pwhl", "iihf") and start - PREGAME <= now < start + timedelta(minutes=15) \
                    and updated < start - PREGAME:
                reason = f"lineups before puck drop ({g['id']})"
            elif start + GAME_LENGTH <= now <= start + GIVE_UP_AFTER:
                if updated < start + GAME_LENGTH:
                    reason = f"game should be over ({g['id']})"
                elif now - updated >= RETRY_EVERY:
                    reason = f"no final score yet, checking again ({g['id']})"
        if reason:
            due[key] = reason
    return due
