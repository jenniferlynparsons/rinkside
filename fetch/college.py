"""NCAA women's hockey from College Hockey News (collegehockeynews.com).

Schedule, results, TV, conference standings, roster, season stats and box
scores. CHN pages are plain server-rendered HTML.
"""
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from common import ET, SKATER_COLUMNS, http_get, iso_utc, last_first_to_first_last, norm_name, num, to_int
import dom

BASE = "https://www.collegehockeynews.com"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def get(path):
    return http_get(BASE + path)


# ---------------------------------------------------------------- schedule
def parse_schedule(html, team_name):
    root = dom.parse(html)
    table = root.find("table", cls="schedule") or next(
        (t for t in root.find_all("table") if re.search(r"\b\d{1,2}\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", t.text)), None)
    if table is None:
        raise ValueError("schedule table not found")
    games, month, year, seen = [], None, None, {}
    for r in dom.rows(table):
        cs = dom.cells(r)
        txt = r.text
        m = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", txt)
        if m and m.group(1).lower() in MONTHS:
            month, year = MONTHS[m.group(1).lower()], int(m.group(2))
            continue
        if len(cs) < 9 or not month:
            continue
        dm = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", cs[0].text)
        if not dm:
            continue
        day = int(dm.group(1))
        result = cs[2].text.strip().upper()
        ours, theirs = cs[3].text.strip(), cs[4].text.replace("-", "").strip()
        extra = cs[5].text.strip().lower()           # "ot", "2ot", "so"…
        loc = cs[6].text.strip().lower()              # "", "at", "vs."
        opp_cell = cs[7]
        opp_raw = opp_cell.text
        flags = re.findall(r"\((\w+)\)", opp_raw)
        opp = re.sub(r"\s*\(\w+\)", "", opp_raw).strip()
        opp_link = next((a.get("href") for a in opp_cell.links() if "/team/" in a.get("href")), "")
        when = cs[8].text if len(cs) > 8 else ""
        box = next((a.get("href") for c in cs[9:] for a in c.links() if "/box/" in a.get("href")), "")
        watch = []
        for c in cs[9:]:
            for a in c.links():
                href = a.get("href")
                name = (a.get("title") or a.text).strip()
                if "/box/" in href or not name or name.lower() == "box":
                    continue
                watch.append({"name": name, "region": "US", "url": href})

        # Start time: "6:00 ET", "10:30 ET", or TBA.
        tm = re.search(r"(\d{1,2}):(\d{2})\s*(ET|CT|MT|PT)?", when)
        tz_shift = {"ET": 0, "CT": 1, "MT": 2, "PT": 3}.get(tm.group(3) if tm else "ET", 0)
        tbd = tm is None
        hour, minute = (int(tm.group(1)), int(tm.group(2))) if tm else (12, 0)
        if tm and hour < 10:  # CHN uses 12-hour times: "6:00" is 6 pm; 10:30/11:30 are morning games
            hour += 12
        local = datetime(year, month, day, hour, minute, tzinfo=ET) + timedelta(hours=tz_shift)

        if result in ("W", "L", "T"):
            status = "final"
        elif ours and theirs:
            status = "live"
        else:
            status = "scheduled"
        us_score = to_int(ours) if status != "scheduled" else None
        them_score = to_int(theirs) if status != "scheduled" else None
        side = "away" if loc == "at" else "home"
        neutral = loc.startswith("vs")
        us = {"name": team_name, "short": team_name[:3].upper(), "score": us_score}
        them = {"name": opp, "short": "", "score": them_score}
        comp = "Exhibition" if "ex" in flags else ("Non-conference" if "nc" in flags else "Conference")
        base_id = f"ncaa-{year:04d}{month:02d}{day:02d}-{norm_name(opp).replace(' ', '')[:12]}"
        seen[base_id] = seen.get(base_id, 0) + 1
        gid = base_id + (f"-{seen[base_id]}" if seen[base_id] > 1 else "")
        status_text = ""
        if status == "final":
            status_text = "Final" + (f" {extra.upper()}" if extra else "")
            status_text = f"{result} · {status_text}"
        games.append({
            "id": gid, "comp": comp, "start": iso_utc(local), "tbd": tbd,
            "home": us if side == "home" else them,
            "away": them if side == "home" else us,
            "side": side, "neutral": neutral, "venue": "",
            "status": status, "statusText": status_text, "result": result if status == "final" else "",
            "watch": watch,
            "links": [{"label": "Box score", "url": BASE + box}] if box else [],
            "_box": box, "_opp_path": opp_link, "_footnote": cs[1].text.strip(),
        })
    return games


def parse_ics_venues(ics):
    """{'YYYY-MM-DD' (ET date): 'Venue'} from CHN's team calendar."""
    out = {}
    for ev in ics.split("BEGIN:VEVENT")[1:]:
        start = re.search(r"DTSTART[^:]*:(\d{8}T\d{6})(Z?)", ev)
        loc = re.search(r"LOCATION:(.*)", ev)
        if not (start and loc):
            continue
        dt = datetime.strptime(start.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        out[dt.astimezone(ET).date().isoformat()] = loc.group(1).strip().replace("\\,", ",")
    return out


# ---------------------------------------------------------------- roster/stats
def parse_roster(html):
    root = dom.parse(html)
    table = root.find("table", pred=lambda t: t.get("id") == "players") or root.find("table", cls="roster")
    if table is None:
        return []
    out, section = [], ""
    for r in dom.rows(table):
        cs = dom.cells(r)
        if r.has_class("stats-section"):
            section = r.text
            continue
        idx = next((i for i, c in enumerate(cs) if "," in c.text and any("/players/" in a.get("href") for a in c.links())), None)
        if idx is None:
            continue

        def at(i):
            return cs[i].text if 0 <= i < len(cs) else ""
        pos = at(idx + 2) if len(at(idx + 2)) <= 2 else ""
        if not pos:
            pos = {"forwards": "F", "defensemen": "D", "defense": "D", "goaltenders": "G", "goalies": "G"}.get(section.lower(), "")
        out.append({
            "num": at(idx - 1).strip(),
            "name": last_first_to_first_last(at(idx)),
            "pos": pos,
            "detail": " · ".join(x for x in [at(idx + 1), at(idx + 3), at(idx + 5)] if x and x != "-"),
        })
    return out


def _stats_table(table, kind, numbers):
    rs = dom.rows(table)
    head = next((r for r in rs if re.search(r"\bGP\b", r.text)), None)
    if head is None:
        return []
    labels = [c.text for c in dom.cells(head)]
    rows = []
    for r in rs[rs.index(head) + 1:]:
        cs = dom.cells(r)
        if len(cs) < len(labels) - 1 or not cs:
            continue
        raw = cs[0].text
        if not raw or raw.lower().startswith(("total", "opponent", "team")):
            continue
        parts = [p.strip() for p in raw.split(",")]
        name = parts[0]
        pos = parts[1] if kind == "skaters" and len(parts) > 2 else ("G" if kind == "goalies" else "")
        rec = {"name": name, "pos": pos, "num": numbers.get(norm_name(name), "")}
        for lab, c in zip(labels[1:], cs[1:]):
            rec[lab] = num(c.text)
        rows.append(rec)
    return rows


def parse_stats(html, roster):
    root = dom.parse(html)
    numbers = {norm_name(p["name"]): p["num"] for p in roster}
    sk = root.find("table", pred=lambda t: t.get("id") == "skaters")
    gk = root.find("table", pred=lambda t: t.get("id") == "goalies")
    skaters = _stats_table(sk, "skaters", numbers) if sk else []
    goalies = _stats_table(gk, "goalies", numbers) if gk else []

    def pick(rows, mapping):
        return [{"num": r["num"], "name": r["name"], "pos": r["pos"],
                 **{k: r.get(src, "") for k, src in mapping}} for r in rows]
    skm = [("gp", "GP"), ("g", "G"), ("a", "A"), ("pts", "Pts."), ("pm", "+/-"), ("pim", "PIM"), ("sog", "Shots")]
    gkm = [("gp", "GP"), ("w", "W"), ("l", "L"), ("t", "T"), ("gaa", "GAA"), ("svp", "SV%"), ("so", "SH")]
    return {
        "skaters": {"columns": [{"key": k, "label": l} for k, l in
                                [("gp", "GP"), ("g", "G"), ("a", "A"), ("pts", "PTS"), ("pm", "+/-"), ("pim", "PIM"), ("sog", "SOG")]],
                    "rows": pick(skaters, skm)},
        "goalies": {"columns": [{"key": k, "label": l} for k, l in
                                [("gp", "GP"), ("w", "W"), ("l", "L"), ("t", "T"), ("gaa", "GAA"), ("svp", "SV%"), ("so", "SO")]],
                    "rows": pick(goalies, gkm)},
    }


def parse_standings(html, conference, team_name):
    root = dom.parse(html)
    table = next((t for t in root.find_all("table")
                  if dom.rows(t) and dom.rows(t)[0].text.strip().upper().startswith(conference.upper())), None)
    if table is None:
        return []
    rows = []
    for r in dom.rows(table):
        cs = dom.cells(r)
        if len(cs) < 14 or not any("/team/" in a.get("href") for a in cs[1].links()):
            continue
        t = [c.text for c in cs]
        rows.append({"rank": to_int(t[0]), "team": t[1], "us": norm_name(t[1]) == norm_name(team_name),
                     "gp": to_int(t[2], 0), "pts": to_int(t[3], 0),
                     "rw": to_int(t[5], 0), "rl": to_int(t[6], 0), "ow": to_int(t[7], 0), "ol": to_int(t[8], 0),
                     "overall": f"{t[11]}-{t[12]}-{t[13]}"})
    return [{
        "title": f"{conference} standings",
        "columns": [{"key": "gp", "label": "GP"}, {"key": "pts", "label": "PTS"}, {"key": "rw", "label": "RW"},
                    {"key": "ow", "label": "OTW"}, {"key": "ol", "label": "OTL"}, {"key": "rl", "label": "RL"},
                    {"key": "overall", "label": "Overall"}],
        "rows": rows,
        "note": "Conference games only (Overall = W-L-T in all games). Regulation win 3 pts · OT/shootout win 2 · OT/shootout loss 1",
    }]


def parse_npi(html):
    """{team name: national rank} from CHN's NPI ratings page."""
    root = dom.parse(html)
    table = max(root.find_all("table"), key=lambda t: len(dom.rows(t)), default=None)
    ranks = {}
    for r in dom.rows(table) if table is not None else []:
        cs = dom.cells(r)
        if len(cs) >= 2 and cs[0].text.isdigit() and cs[1].links():
            ranks[cs[1].text] = int(cs[0].text)
    return ranks


# ---------------------------------------------------------------- box score
def parse_box(html, game, numbers_by_team):
    """numbers_by_team: {normalized team name: {normalized player: jersey}}"""
    root = dom.parse(html)
    tables = root.find_all("table")
    scoring, goalies, skater_tables = [], {}, []
    for t in tables:
        rs = dom.rows(t)
        if not rs:
            continue
        first = rs[0].text.strip()
        if first.startswith("Scoring"):
            period = ""
            for r in rs[1:]:
                cs = dom.cells(r)
                if len(cs) <= 1:
                    period = r.text.replace(" Period", "")
                    continue
                txt = [c.text for c in cs if c.text]
                if len(txt) >= 3:
                    scoring.append({"period": period, "team": txt[0], "time": txt[-1],
                                    "text": " — from ".join(x for x in [txt[1], ", ".join(txt[2:-1])] if x) or txt[1]})
        elif first.startswith("Goalies"):
            team = None
            for r in rs[1:]:
                cs = dom.cells(r)
                if r.has_class("stats-header"):
                    team = cs[0].text if cs else None
                    goalies.setdefault(team, [])
                    continue
                if team and cs and cs[0].text and cs[0].text.upper() != "EMPTY NET":
                    goalies[team].append({"name": cs[0].text, "sv": cs[1].text if len(cs) > 1 else "",
                                          "ga": cs[2].text if len(cs) > 2 else "", "min": cs[3].text if len(cs) > 3 else ""})
        elif t.has_class("data") and rs[0].has_class("stats-section") and re.search(r"\bPt\.?\b", first):
            skater_tables.append(t)

    def same(a, b):
        a, b = norm_name(a), norm_name(b)
        return bool(a) and bool(b) and (a == b or a in b or b in a)

    def side(team_name):
        tkey = norm_name(team_name)
        numbers = next((v for k, v in numbers_by_team.items() if same(k, tkey)), {})
        table = next((t for t in skater_tables if same(dom.cells(dom.rows(t)[0])[0].text, team_name)), None)
        groups, gl_names = [], set()
        gl = next((v for k, v in goalies.items() if k and same(k, team_name)), [])
        if gl:
            groups.append({"title": "Goalies", "players": [
                {"num": numbers.get(norm_name(g["name"]), ""), "name": g["name"], "pos": "G", "flag": "",
                 "stat": f"{g['sv']} SV · {g['ga']} GA · {g['min']}"} for g in gl]})
            gl_names = {norm_name(g["name"]) for g in gl}
        players = []
        if table is not None:
            for r in dom.rows(table)[1:]:
                cs = [c.text for c in dom.cells(r)]
                if not cs or not cs[0] or norm_name(cs[0]) in gl_names:
                    continue
                g, a = to_int(cs[1], 0) if len(cs) > 1 else 0, to_int(cs[2], 0) if len(cs) > 2 else 0
                players.append({"num": numbers.get(norm_name(cs[0]), ""), "name": cs[0], "pos": "", "flag": "",
                                "stat": " ".join(x for x in [f"{g}G" if g else "", f"{a}A" if a else ""] if x)})
        if players:
            players.sort(key=lambda p: to_int(p["num"], 999))
            groups.append({"title": "Skaters", "players": players})
        return {"name": team_name, "groups": groups}

    return {"id": game["id"], "home": side(game["home"]["name"]), "away": side(game["away"]["name"]),
            "scoring": scoring, "source": "College Hockey News box score"}


# ---------------------------------------------------------------- build
def build(team_cfg, cache):
    c = team_cfg["chn"]
    name, tid, season = c["name"], c["id"], c["season"]
    slug = name.replace(" ", "-")
    games = parse_schedule(get(f"/women/team/{slug}/{tid}"), team_cfg.get("display_name", name))
    try:
        venues = parse_ics_venues(get(f"/schedules/team-cal.php?s={season}&td={tid}&w=1"))
    except Exception as e:
        print(f"  ics: {e}")
        venues = {}
    for g in games:
        d = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
        g["venue"] = venues.get(d, "")

    roster = parse_roster(get(f"/women/roster/{slug}/{tid}"))
    stats = parse_stats(get(f"/women/stats/team/{slug}/{tid}"), roster)
    stats["title"] = f"{season[:4]}-{season[6:]} season"
    standings = parse_standings(get("/women/standings.php"), c.get("conference", "ECAC"), name)
    try:
        npi = parse_npi(get("/women/ratings.php"))
    except Exception as e:
        print(f"  npi: {e}")
        npi = {}
    for g in games:
        if g["comp"] == "Conference":
            g["comp"] = c.get("conference", "Conference")

    # Box scores → lineups (jersey numbers come from each team's roster page).
    our_numbers = {norm_name(p["name"]): p["num"] for p in roster}
    for g in games:
        if g["status"] != "final" or not g["_box"]:
            continue
        key = f"lineup/{g['id']}"
        lu = cache.get(key)
        if lu is None:
            try:
                opp_numbers = {}
                if g["_opp_path"]:
                    rp = g["_opp_path"].replace("/team/", "/roster/")
                    opp = cache.get(f"roster{rp}", max_age_hours=24 * 7)
                    if opp is None:
                        opp = parse_roster(get(rp))
                        cache.put(f"roster{rp}", opp)
                    opp_numbers = {norm_name(p["name"]): p["num"] for p in opp}
                them = g["away"] if g["side"] == "home" else g["home"]
                lu = parse_box(get(g["_box"]), g, {norm_name(name): our_numbers,
                                                    norm_name(team_cfg.get("display_name", name)): our_numbers,
                                                    norm_name(them["name"]): opp_numbers})
                cache.put(key, lu)
            except Exception as e:
                print(f"  box {g['_box']}: {e}")
                continue
        g["_lineup"] = lu

    rec = Counter(g["result"] for g in games if g["comp"] != "Exhibition")
    return {
        "games": games,
        "record": f"{rec['W']}-{rec['L']}-{rec['T']}",
        "standings": standings,
        "roster": {"title": f"{season[:4]}-{season[6:]} roster", "players": roster},
        "stats": stats,
        "ranking": {"scope": "NPI", "describe": "national NPI ranking", "ranks": npi,
                    "us": next((v for k, v in npi.items() if norm_name(k) == norm_name(name)), None)},
    }
