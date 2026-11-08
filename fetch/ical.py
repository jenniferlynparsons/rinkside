"""Calendar feeds (.ics) built from the team data, one per team plus one for
every team together. Subscribe to them by URL in Google Calendar, Apple
Calendar or Outlook; events keep stable IDs, so time changes and new games
update in place."""
import json
import os
from datetime import datetime, timedelta, timezone

GAME_LENGTH = timedelta(hours=2, minutes=30)


def _esc(s):
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r", "").replace("\n", "\\n"))


def _fold(line):
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 74:
            out.append(cur.decode("utf-8"))
            cur = b" "
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _event(g, team, site_url, stamp, with_team):
    us = g["home"] if g["side"] == "home" else g["away"]
    them = g["away"] if g["side"] == "home" else g["home"]
    prefix = "vs" if g.get("neutral") or g["side"] == "home" else "at"
    title = f"{team['short']} {prefix} {them['name']}"
    # No scores in the calendar: it would spoil games watched later.
    if g["side"] == "home" and not g.get("neutral"):
        title = "🏠 " + title

    lines = [g.get("comp", "")]
    watch = [w for w in g.get("watch", []) if w.get("region") != "Canada"]
    if watch:
        lines.append("Watch: " + ", ".join(w["name"] + ("?" if w.get("note") else "") for w in watch))
        lines += [f"{w['name']}: {w['url']}" for w in watch if w.get("url")]
    if any(w.get("note") for w in watch):
        lines.append("(? = broadcaster not confirmed)")
    r = g.get("rank")
    if r:
        word = "above" if r["them"] < r["us"] else "below" if r["them"] > r["us"] else "level with"
        lines.append(f"{them['name']} is ranked {word} {team['short']} ({r['scope']}: {r['them']} vs {r['us']})")
    if site_url:
        lines.append(f"Details and lineups: {site_url}#/game/{g['id']}")

    start = datetime.fromisoformat(g["start"].replace("Z", "+00:00"))
    ev = ["BEGIN:VEVENT", f"UID:{g['id']}@rinkside", f"DTSTAMP:{stamp}"]
    if g.get("tbd"):  # time not announced yet: all-day placeholder on the right Eastern date
        from zoneinfo import ZoneInfo
        d = start.astimezone(ZoneInfo("America/New_York")).date()
        ev += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        lines.insert(0, "Start time to be announced.")
    else:
        ev += [f"DTSTART:{_utc(start)}", f"DTEND:{_utc(start + GAME_LENGTH)}"]
    ev += [f"SUMMARY:{_esc(title)}", f"DESCRIPTION:{_esc(chr(10).join(x for x in lines if x))}"]
    if g.get("venue"):
        ev.append(f"LOCATION:{_esc(g['venue'])}")
    if site_url:
        ev.append(f"URL:{site_url}#/game/{g['id']}")
    ev.append("STATUS:CONFIRMED")
    ev.append("END:VEVENT")
    return ev


def _calendar(name, events):
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Rinkside//Hockey schedules//EN",
            "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}",
            "X-WR-TIMEZONE:America/New_York", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
            "X-PUBLISHED-TTL:PT6H"]
    return "\r\n".join(_fold(x) for x in head + events + ["END:VCALENDAR"]) + "\r\n"


def site_url_from_env(cfg):
    if cfg.get("site_url"):
        return cfg["site_url"].rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def write_calendars(cfg, data_dir, cal_dir):
    """Build calendar/<team>.ics and calendar/all.ics from data/teams/*.json."""
    os.makedirs(cal_dir, exist_ok=True)
    site = site_url_from_env(cfg)
    stamp = _utc(datetime.now(timezone.utc))
    every = []
    written = []
    for t in cfg["teams"]:
        try:
            with open(os.path.join(data_dir, "teams", f"{t['key']}.json")) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        games = data.get("games", [])
        mine = [x for g in games for x in _event(g, t, site, stamp, with_team=False)]
        with open(os.path.join(cal_dir, f"{t['key']}.ics"), "w", newline="") as fh:
            fh.write(_calendar(f"{t['name']} — Rinkside", mine))
        every += [x for g in games for x in _event(g, t, site, stamp, with_team=True)]
        written.append(t["key"])
    with open(os.path.join(cal_dir, "all.ics"), "w", newline="") as fh:
        fh.write(_calendar("Rinkside — all teams", every))
    return written
