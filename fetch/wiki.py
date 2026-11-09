"""IIHF tournaments via Wikipedia's open API.

iihf.com blocks automated requests from cloud servers, so we read the
tournament's Wikipedia article instead (MediaWiki API, wikitext). Editors keep
it current during the event: schedule in local time, scores, goal scorers,
and full rosters with jersey numbers on a companion "… rosters" article.

What Wikipedia doesn't have: game-day lineups. For each game we show both
teams' tournament rosters instead, and say so on the page.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from common import http_get, iso_utc, to_int
from iihf import group_table

API = "https://en.wikipedia.org/w/api.php"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}
PHASE_BY_HEADING = [
    (r"group\s+([A-Z])", "PreliminaryRound"), (r"relegation", "RelegationRound"),
    (r"quarterfinal", "Quarterfinals"), (r"semifinal", "Semifinals"),
    (r"third[\s-]place|bronze", "BronzeMedalGame"), (r"^final$|gold", "GoldMedalGame"),
]
PHASE_LABEL = {"PreliminaryRound": "Group stage", "RelegationRound": "Relegation game",
               "Quarterfinals": "Quarterfinal", "Semifinals": "Semifinal",
               "BronzeMedalGame": "Bronze medal game", "GoldMedalGame": "Gold medal game"}


def wikitext(title):
    data = http_get(API, params={"action": "parse", "page": title, "prop": "wikitext",
                                 "format": "json", "formatversion": "2", "redirects": "1"}, as_json=True)
    if "error" in data:
        raise RuntimeError(f"Wikipedia: {data['error'].get('info', 'page not found')} ({title})")
    return data["parse"]["wikitext"]


# ---------------------------------------------------------------- wikitext helpers
def plain(s):
    """Wikitext → readable text: links, bold/italics, small templates, refs."""
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s or "", flags=re.S)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{small\|([^{}]*)\}\}", r"\1", s, flags=re.I)
    s = re.sub(r"\{\{sortname\|([^|{}]*)\|([^|{}]*)[^{}]*\}\}", r"\1 \2", s, flags=re.I)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = s.replace("'''", "").replace("''", "").replace("<br>", " ").replace("<br />", " ")
    return re.sub(r"\s+", " ", s).strip()


def team_code(field):
    m = re.search(r"\{\{\s*ihw(?:-rt)?\s*\|\s*([A-Z]{3})", field or "")
    return m.group(1) if m else plain(field) or "TBD"


def boxes(text):
    """Yield (heading, {field: value}) for each {{Ice hockey box}} in order."""
    heading = ""
    pos = 0
    pattern = re.compile(r"^(={2,4})\s*(.*?)\s*\1\s*$|\{\{\s*Ice hockey box", re.M | re.I)
    while True:
        m = pattern.search(text, pos)
        if not m:
            return
        if m.group(1):
            heading = m.group(2)
            pos = m.end()
            continue
        # Find the matching closing braces.
        depth, i = 0, m.start()
        while i < len(text):
            if text.startswith("{{", i):
                depth += 1
                i += 2
            elif text.startswith("}}", i):
                depth -= 1
                i += 2
                if depth == 0:
                    break
            else:
                i += 1
        body = text[m.start() + 2:i - 2]
        fields = {}
        for part in re.split(r"\n\s*\|", body)[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                fields[k.strip().lower()] = v.strip()
        yield heading, fields
        pos = i


def phase_of(heading):
    h = heading.strip().lower()
    for pat, phase in PHASE_BY_HEADING:
        m = re.search(pat, h, re.I)
        if m:
            return phase, (m.group(1).upper() if phase == "PreliminaryRound" else "")
    return "", ""


def parse_games(text, tz):
    games = []
    for heading, f in boxes(text):
        phase, group = phase_of(heading)
        dm = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", plain(f.get("date", "")))
        tm = re.match(r"(\d{1,2}):(\d{2})", plain(f.get("time", "")))
        if not dm:
            continue
        local = datetime(int(dm.group(3)), MONTHS.get(dm.group(2).lower(), 1), int(dm.group(1)),
                         int(tm.group(1)) if tm else 12, int(tm.group(2)) if tm else 0, tzinfo=tz)
        score_raw = f.get("score", "")
        sm = re.search(r"(\d+)\s*[–-]\s*(\d+)", plain(score_raw))
        extra = re.search(r"\b(GWS|SO|OT)\b", plain(score_raw))
        home, away = team_code(f.get("team1")), team_code(f.get("team2"))
        games.append({
            "gid": f"{local:%Y%m%d}-{home}-{away}".lower(), "start": local,
            "home": home, "away": away, "group": group, "phase": phase,
            "venue": plain(f.get("stadium", "")), "status": "final" if sm else "scheduled",
            "ot": bool(extra and extra.group(1) == "OT"), "so": bool(extra and extra.group(1) in ("SO", "GWS")),
            "hs": int(sm.group(1)) if sm else None, "as": int(sm.group(2)) if sm else None,
            "tbd": not tm, "goals1": f.get("goals1", ""), "goals2": f.get("goals2", ""),
            "goalie1": f.get("goalie1", ""), "goalie2": f.get("goalie2", ""),
        })
    return games


def parse_goals(raw):
    """'02:44 – [[Hayley Scamurra|Scamurra]] ([[Savannah Harmon|Harmon]]) / …'
    → [{'time','scorer','scorer_full','assists':[(short, full)], 'tags'}]"""
    out = []
    for part in re.split(r"\s*/\s*|<br\s*/?>", raw or ""):
        if not part.strip():
            continue
        tmatch = re.search(r"(\d{1,2}:\d{2})", part)
        rest = re.sub(r"\d{1,2}:\d{2}", "", part).strip(" –-")
        links = re.findall(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]", rest)
        names = [(short or full, full) for full, short in links]
        text = plain(rest)
        scorer = text.split("(")[0].strip(" –-")
        tags = re.findall(r"\((PP\d?|SH\d?|EN|PS)\)", text)
        assists_txt = re.search(r"\(([^)]*)\)", text)
        assists = [a.strip() for a in assists_txt.group(1).split(",")] if assists_txt and assists_txt.group(1) not in tags else []
        full_by_short = {s: f for s, f in names}
        out.append({"time": tmatch.group(1) if tmatch else "", "scorer": scorer,
                    "scorer_full": full_by_short.get(scorer, ""), "tags": tags,
                    "assists": [(a, full_by_short.get(a, "")) for a in assists if a]})
    return out


def group_table(games, group, names):
    teams = {}
    for g in games:
        if g["phase"] != "PreliminaryRound" or g["group"] != group:
            continue
        for code in (g["home"], g["away"]):
            teams.setdefault(code, {"team": names.get(code, code), "code": code, "gp": 0, "w": 0, "otw": 0,
                                    "otl": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
        if g["status"] != "final" or g["hs"] is None or g["as"] is None:
            continue
        h, aw = teams[g["home"]], teams[g["away"]]
        extra = g["ot"] or g["so"]
        for me, them, gf, ga in ((h, aw, g["hs"], g["as"]), (aw, h, g["as"], g["hs"])):
            me["gp"] += 1
            me["gf"] += gf
            me["ga"] += ga
            if gf > ga:
                me["otw" if extra else "w"] += 1
                me["pts"] += 2 if extra else 3
            else:
                me["otl" if extra else "l"] += 1
                me["pts"] += 1 if extra else 0
    rows = sorted(teams.values(), key=lambda t: (-t["pts"], -(t["gf"] - t["ga"]), -t["gf"], t["team"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def parse_rosters(text):
    """{'United States': [{'num','pos','name','club','flag'}], …} from the rosters article."""
    teams = {}
    for m in re.finditer(r"^===\s*(.*?)\s*===\s*$", text, re.M):
        name = m.group(1)
        end = text.find("\n===", m.end())
        sec = text[m.end(): end if end > 0 else len(text)]
        players = []
        for row in re.findall(r"^\|\s*(\d+)\s*\|\|(.*)$", sec, re.M):
            cells = [c.strip() for c in row[1].split("||")]
            if len(cells) < 2:
                continue
            pos = plain(cells[0])
            name_cell = cells[1]
            flag = "C" if re.search(r"Captain[^|]*\|\s*'*C'*", name_cell) else (
                   "A" if re.search(r"Captain[^|]*\|\s*'*A'*", name_cell) else "")
            nm = plain(re.sub(r"align=\"?\w+\"?\|", "", name_cell))
            nm = re.sub(r"\s+[–-]\s*[CA]$", "", nm).strip()
            club = plain(re.sub(r"align=\"?\w+\"?\|", "", cells[-1])) if len(cells) > 2 else ""
            players.append({"num": row[0], "pos": pos, "name": nm, "club": club, "flag": flag})
        if players:
            teams[name] = players
    return teams


# ---------------------------------------------------------------- build
def build_event(event_cfg, team_cfgs, cache, watch_cfg):
    tz = ZoneInfo(event_cfg.get("local_timezone", "UTC"))
    title = event_cfg.get("wikipedia_title", event_cfg["name"])
    games_all = parse_games(wikitext(title), tz)
    if not games_all:
        raise ValueError("no games found on the Wikipedia article")
    names = event_cfg.get("names", {})
    try:
        rosters = parse_rosters(wikitext(title + " rosters"))
    except Exception as e:
        print(f"  wikipedia rosters: {e}")
        rosters = {}
    page_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
    iihf_url = f"https://www.iihf.com/en/events/{event_cfg['path']}/schedule"

    def roster_for(code):
        return rosters.get(names.get(code, code), [])

    def groups_for(code):
        order = [("Goalies", "G"), ("Defense", "D"), ("Forwards", "F")]
        r = roster_for(code)
        return [{"title": t, "players": [{"num": p["num"], "name": p["name"], "pos": p["pos"], "flag": p["flag"], "stat": ""}
                                         for p in r if p["pos"] == pos]} for t, pos in order if any(p["pos"] == pos for p in r)]

    results = {}
    for tc in team_cfgs:
        code = tc["iihf"]["code"]
        mine = [g for g in games_all if code in (g["home"], g["away"])]
        group = next((g["group"] for g in mine if g["phase"] == "PreliminaryRound"), "")
        games = []
        for g in mine:
            gid = f"iihf-{g['gid']}"
            comp = f"{event_cfg['short']} · " + (f"Group {g['group']}" if g["phase"] == "PreliminaryRound"
                                                  else PHASE_LABEL.get(g["phase"], g["phase"] or "Game"))
            status_text = ("Final" + (" SO" if g["so"] else " OT" if g["ot"] else "")) if g["status"] == "final" else ""
            game = {
                "id": gid, "comp": comp, "start": iso_utc(g["start"]), "tbd": g["tbd"],
                "home": {"name": names.get(g["home"], g["home"]), "short": g["home"], "score": g["hs"]},
                "away": {"name": names.get(g["away"], g["away"]), "short": g["away"], "score": g["as"]},
                "side": "home" if g["home"] == code else "away", "neutral": True,
                "venue": g["venue"], "status": g["status"], "statusText": status_text,
                "watch": [dict(w) for w in watch_cfg],
                "links": [{"label": "Wikipedia", "url": page_url}, {"label": "IIHF schedule", "url": iihf_url}],
            }
            scoring = []
            for raw, team in ((g["goals1"], g["home"]), (g["goals2"], g["away"])):
                goals = parse_goals(raw)
                # Later mentions are surname-only; expand them from earlier links or the roster.
                known = {short: full for gl in goals for short, full in
                         [(gl["scorer"], gl["scorer_full"])] + gl["assists"] if full}
                for p in roster_for(team):
                    last = p["name"].split()[-1]
                    if sum(1 for q in roster_for(team) if q["name"].split()[-1] == last) == 1:
                        known.setdefault(last, p["name"])
                    known.setdefault(" ".join(p["name"].split()[1:]), p["name"])
                full = lambda short, f="": f or known.get(short, short)  # noqa: E731
                for goal in goals:
                    who = full(goal["scorer"], goal["scorer_full"])
                    ast = ", ".join(full(short, f) for short, f in goal["assists"])
                    scoring.append({"period": "", "time": goal["time"], "team": team,
                                    "text": who + (f" — from {ast}" if ast else "") +
                                            (f" [{', '.join(goal['tags'])}]" if goal["tags"] else "")})
            scoring.sort(key=lambda s: tuple(int(x) for x in s["time"].split(":")) if s["time"] else (999, 0))
            if roster_for(g["home"]) or roster_for(g["away"]) or scoring:
                game["_lineup"] = {
                    "id": gid,
                    "home": {"name": game["home"]["name"], "groups": groups_for(g["home"])},
                    "away": {"name": game["away"]["name"], "groups": groups_for(g["away"])},
                    "scoring": scoring,
                    "source": "the tournament rosters on Wikipedia (game-day scratches aren't shown; times are game clock)",
                }
            games.append(game)
        games.sort(key=lambda x: x["start"])

        bracket = [{"phase": PHASE_LABEL.get(g["phase"], g["phase"]), "start": iso_utc(g["start"]),
                    "home": names.get(g["home"], g["home"]), "away": names.get(g["away"], g["away"]),
                    "hs": g["hs"], "as": g["as"], "status": g["status"], "us": code in (g["home"], g["away"])}
                   for g in sorted(games_all, key=lambda x: x["start"])
                   if g["phase"] not in ("PreliminaryRound", "RelegationRound", "")]

        standings, ranking = [], None
        if group:
            table = group_table(games_all, group, names)
            played = [r for r in table if r["gp"] > 0]
            ranking = {"scope": f"Group {group}", "describe": f"{event_cfg['short']} Group {group} table",
                       "ranks": {r["team"]: r["rank"] for r in played},
                       "us": next((r["rank"] for r in played if r["code"] == code), None)}
            standings.append({
                "title": f"{event_cfg['short']} · Group {group}",
                "columns": [{"key": "gp", "label": "GP"}, {"key": "pts", "label": "PTS"}, {"key": "w", "label": "W"},
                            {"key": "otw", "label": "OTW"}, {"key": "otl", "label": "OTL"}, {"key": "l", "label": "L"},
                            {"key": "gf", "label": "GF"}, {"key": "ga", "label": "GA"}],
                "rows": [dict(r, us=r["code"] == code) for r in group_table(games_all, group, names)],
                "note": "Worked out from the results (3 pts regulation win, 2 OT/SO win, 1 OT/SO loss). "
                        "Tiebreakers aren't applied — check iihf.com when teams are level.",
            })

        # Roster, and tournament scoring counted from the goal summaries.
        roster = roster_for(code)
        by_last = {}
        for p in roster:
            by_last.setdefault(p["name"].split()[-1].lower(), []).append(p)
        tally = {p["name"]: {"g": 0, "a": 0} for p in roster}

        def credit(short, full, kind):
            if full and full in tally:
                tally[full][kind] += 1
                return
            cands = by_last.get((short or full).split()[-1].lower(), []) if (short or full) else []
            if len(cands) == 1:
                tally[cands[0]["name"]][kind] += 1
        for g in mine:
            if g["status"] != "final":
                continue
            raw = g["goals1"] if g["home"] == code else g["goals2"]
            for goal in parse_goals(raw):
                credit(goal["scorer"], goal["scorer_full"], "g")
                for short, full in goal["assists"]:
                    credit(short, full, "a")
        stats = None
        if any(v["g"] or v["a"] for v in tally.values()):
            rows = [{"num": p["num"], "name": p["name"], "pos": p["pos"], "g": tally[p["name"]]["g"],
                     "a": tally[p["name"]]["a"], "pts": tally[p["name"]]["g"] + tally[p["name"]]["a"]}
                    for p in roster if p["pos"] != "G"]
            rows.sort(key=lambda r: (-r["pts"], -r["g"], to_int(r["num"], 99)))
            stats = {"title": f"{event_cfg['name']} — counted from Wikipedia's game summaries",
                     "skaters": {"columns": [{"key": "g", "label": "G"}, {"key": "a", "label": "A"},
                                             {"key": "pts", "label": "PTS"}], "rows": rows},
                     "goalies": {"columns": [], "rows": []}}

        order = {"F": 0, "D": 1, "G": 2}
        results[tc["key"]] = {
            "games": games, "standings": standings, "bracket": bracket,
            "roster": {"title": f"{event_cfg['name']} roster",
                       "players": sorted([{"num": p["num"], "name": p["name"], "pos": p["pos"], "flag": p["flag"],
                                           "detail": p["club"]} for p in roster],
                                         key=lambda p: (order.get(p["pos"], 3), to_int(p["num"], 99)))},
            "stats": stats,
            "ranking": ranking,
        }
    return results
