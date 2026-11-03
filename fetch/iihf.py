"""IIHF tournaments (iihf.com): schedule, results, lineups, rosters and
tournament stats for the national teams we follow. Group standings are
computed here from the results, using IIHF points (3 / 2 / 1 / 0)."""
import re
from datetime import datetime, timedelta, timezone

from common import caps_name, http_get, iso_utc, now_utc, num, to_int
import dom

BASE = "https://www.iihf.com"
PHASES = {"PreliminaryRound": "Group stage", "RelegationRound": "Relegation round",
          "Quarterfinals": "Quarterfinal", "Semifinals": "Semifinal",
          "BronzeMedalGame": "Bronze medal game", "GoldMedalGame": "Gold medal game",
          "PlacementRound": "Placement game"}


def get(path):
    return http_get(BASE + path)


# ---------------------------------------------------------------- schedule
def parse_schedule(html):
    root = dom.parse(html)
    out = []
    for c in root.find_all(cls="b-card-schedule", attr="data-game-id"):
        a = c.attrs

        def flag(k):
            return a.get(k, "").lower() == "true"
        home_el, away_el = c.find(cls="js-homescore"), c.find(cls="js-awayscore")
        arena = c.find(cls="s-arena")
        arena_txt = arena.text if arena else ""
        venue = re.sub(r",\s*(Group\s+\w+|Quarterfinal.*|Semifinal.*|.*Medal.*|Relegation.*)$", "", arena_txt).strip()
        link = next((x.get("href") for x in c.links() if "/gamecenter/" in x.get("href")), "")
        date, time_ = a.get("data-date-utc", ""), a.get("data-time-utc", "00:00:00")
        try:
            start = datetime.fromisoformat(f"{date}T{time_}").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        status = "final" if flag("data-gameisfinal") else ("live" if flag("data-gameislive") else "scheduled")
        out.append({
            "gid": a["data-game-id"], "start": start, "home": a.get("data-hometeam", ""),
            "away": a.get("data-guestteam", ""), "group": a.get("data-group", ""),
            "phase": a.get("data-phase", ""), "venue": venue, "status": status,
            "ot": flag("data-gameisfinalovertime"), "so": flag("data-gameisfinalshootout"),
            "hs": to_int(home_el.text) if home_el else None, "as": to_int(away_el.text) if away_el else None,
            "link": link,
        })
    return out


def group_table(cards, group, names):
    teams = {}
    for g in cards:
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


# ---------------------------------------------------------------- tables keyed by player id
def fwk_rows(scope):
    """IIHF pages split one player's data across several tables; every row
    carries data-fwk-id. Merge by that id: {id: {cellclass: text}}."""
    merged, order = {}, []
    for r in scope.find_all("tr", cls="js-table-row"):
        pid = r.get("data-fwk-id")
        if not pid:
            continue
        rec = merged.setdefault(pid, {})
        if pid not in order:
            order.append(pid)
        for td in dom.cells(r):
            key = next((c[8:] for c in td.classes if c.startswith("s-cell--") and c not in ("s-cell--value",)), None)
            if not key or key in ("avatar", "statistics"):
                continue
            val = td.find(cls="s-value")
            rec[key] = (val.text if val else td.text).strip()
            cap = td.find(cls="s-captain")
            if cap:
                rec["captain"] = cap.text.strip()
    return [merged[p] for p in order]


def parse_roster(html):
    root = dom.parse(html)
    players = []
    for rec in fwk_rows(root):
        if not rec.get("j") and not rec.get("position"):
            continue  # team officials
        players.append(rec)
    return players


def parse_lineup(html):
    """{'home': [groups], 'away': [groups]} — groups are goalies then lines."""
    root = dom.parse(html)
    out = {}
    for side in ("home", "away"):
        box = root.find(cls=f"s-team--{side}")
        groups = []
        if box is None:
            out[side] = groups
            continue
        for mt in box.find_all(cls="m-lineup-table"):
            title_el = mt.find(cls="s-table-title")
            title = title_el.text.strip().title() if title_el else ""
            players = []
            for r in mt.find_all("tr", cls="js-table-row"):
                name_td = r.find("td", cls="s-cell--name")
                if name_td is None:
                    continue
                nm = name_td.find(cls="s-value")
                j = r.find("td", cls="s-cell--j")
                pos = r.find("td", cls="s-cell--pos")
                cap = name_td.find(cls="s-captain")
                players.append({"num": (j.text if j else "").strip(),
                                "name": caps_name((nm.text if nm else name_td.text).strip()),
                                "pos": (pos.text if pos else "").strip(),
                                "flag": cap.text.strip() if cap else "", "stat": ""})
            if not players:
                continue
            if not title:
                title = "Goalies" if all(p["pos"] == "GK" for p in players) else "Skaters"
            for p in players:
                if p["pos"] == "GK":
                    p["pos"] = "G"
            groups.append({"title": title, "players": players})
        out[side] = groups
    return out


# ---------------------------------------------------------------- build
def build_event(event_cfg, team_cfgs, cache, watch_cfg):
    path = f"/en/events/{event_cfg['path']}"
    cards = parse_schedule(get(f"{path}/schedule"))
    if not cards:
        raise ValueError("no games found on the IIHF schedule page")
    names = event_cfg.get("names", {})

    # Roster pages (ids differ per event): find links on the teams page.
    roster_links = {}
    try:
        troot = dom.parse(get(f"{path}/teams"))
        for a in troot.links():
            m = re.search(r"/teams/roster/\d+/([a-z_]+)", a.get("href"))
            if m:
                roster_links[m.group(1)] = a.get("href")
    except Exception as e:
        print(f"  iihf teams page: {e}")

    results = {}
    soon = now_utc() + timedelta(minutes=75)
    for tc in team_cfgs:
        code = tc["iihf"]["code"]
        mine = [g for g in cards if code in (g["home"], g["away"])]
        group = next((g["group"] for g in mine if g["phase"] == "PreliminaryRound"), "")
        games = []
        for g in mine:
            gid = f"iihf-{g['gid']}"
            phase = PHASES.get(g["phase"], g["phase"])
            comp = f"{event_cfg['short']} · " + (f"Group {g['group']}" if g["phase"] == "PreliminaryRound" else phase)
            status_text = ""
            if g["status"] == "final":
                status_text = "Final" + (" SO" if g["so"] else (" OT" if g["ot"] else ""))
            elif g["status"] == "live":
                status_text = "Live"
            game = {
                "id": gid, "comp": comp, "start": iso_utc(g["start"]), "tbd": False,
                "home": {"name": names.get(g["home"], g["home"]), "short": g["home"],
                         "score": g["hs"] if g["status"] != "scheduled" else None},
                "away": {"name": names.get(g["away"], g["away"]), "short": g["away"],
                         "score": g["as"] if g["status"] != "scheduled" else None},
                "side": "home" if g["home"] == code else "away", "neutral": True,
                "venue": g["venue"], "status": g["status"], "statusText": status_text,
                "watch": [dict(w) for w in watch_cfg],
                "links": [{"label": "IIHF game centre", "url": BASE + g["link"]}] if g["link"] else [],
            }
            # Lineups: published shortly before puck drop.
            if g["link"] and (g["status"] != "scheduled" or g["start"] <= soon):
                key = f"lineup/{gid}"
                lu = cache.get(key) if g["status"] == "final" else None
                if lu is None:
                    try:
                        parsed = parse_lineup(get(g["link"].replace("/playbyplay/", "/lineup/")))
                        if parsed.get("home") or parsed.get("away"):
                            lu = {"id": gid,
                                  "home": {"name": game["home"]["name"], "groups": parsed.get("home", [])},
                                  "away": {"name": game["away"]["name"], "groups": parsed.get("away", [])},
                                  "scoring": [], "source": "IIHF game centre"}
                            if g["status"] == "final":
                                cache.put(key, lu)
                    except Exception as e:
                        print(f"  iihf lineup {gid}: {e}")
                if lu:
                    game["_lineup"] = lu
            games.append(game)
        games.sort(key=lambda x: x["start"])

        # Medal round: every playoff game, so the bracket is visible even
        # before our team's opponent is known.
        bracket = []
        for g in sorted(cards, key=lambda x: x["start"]):
            if g["phase"] in ("PreliminaryRound", "RelegationRound"):
                continue
            bracket.append({"phase": PHASES.get(g["phase"], g["phase"]), "start": iso_utc(g["start"]),
                            "home": names.get(g["home"], g["home"]), "away": names.get(g["away"], g["away"]),
                            "hs": g["hs"], "as": g["as"], "status": g["status"],
                            "us": code in (g["home"], g["away"])})

        standings = []
        if group:
            standings.append({
                "title": f"{event_cfg['short']} · Group {group}",
                "columns": [{"key": "gp", "label": "GP"}, {"key": "pts", "label": "PTS"}, {"key": "w", "label": "W"},
                            {"key": "otw", "label": "OTW"}, {"key": "otl", "label": "OTL"}, {"key": "l", "label": "L"},
                            {"key": "gf", "label": "GF"}, {"key": "ga", "label": "GA"}],
                "rows": [dict(r, us=r["code"] == code) for r in group_table(cards, group, names)],
                "note": "Worked out from the results here (3 pts regulation win, 2 OT/SO win, 1 OT/SO loss). "
                        "Tiebreakers aren't applied — check iihf.com when teams are level.",
            })

        roster, stats = [], None
        slug = tc["iihf"].get("roster_slug", "")
        if slug in roster_links:
            try:
                recs = parse_roster(get(roster_links[slug]))
                roster = [{"num": r.get("j", ""), "name": caps_name(r.get("name", "")),
                           "pos": r.get("position", ""),
                           "detail": " · ".join(x for x in [r.get("club", ""), r.get("dob", "")] if x)}
                          for r in recs]
                order = {"F": 0, "D": 1, "G": 2, "GK": 2}
                roster.sort(key=lambda p: (order.get(p["pos"], 3), to_int(p["num"], 99)))
                sk = [r for r in recs if r.get("position") != "G" and r.get("gp") not in (None, "", "0")]
                gk = [r for r in recs if r.get("position") == "G" and r.get("gp") not in (None, "", "0")]
                if sk or gk:
                    stats = {"title": event_cfg["name"],
                             "skaters": {"columns": [{"key": k, "label": l} for k, l in
                                                     [("gp", "GP"), ("g", "G"), ("a", "A"), ("pts", "PTS"),
                                                      ("pm", "+/-"), ("pim", "PIM"), ("sog", "SOG")]],
                                         "rows": sorted([{"num": r.get("j", ""), "name": caps_name(r.get("name", "")),
                                                          "pos": r.get("position", ""), "gp": num(r.get("gp")),
                                                          "g": num(r.get("g")), "a": num(r.get("a")),
                                                          "pts": num(r.get("pts")), "pm": r.get("dynamic", ""),
                                                          "pim": num(r.get("pim")), "sog": num(r.get("sog"))}
                                                         for r in sk], key=lambda x: -(x["pts"] or 0) if isinstance(x["pts"], int) else 0)},
                             "goalies": {"columns": [{"key": k, "label": k.upper()} for k in
                                                     [x for x in ("gp", "toi", "ga", "gaa", "svs", "svs%", "so") if any(x in r for r in gk)]],
                                         "rows": [dict({"num": r.get("j", ""), "name": caps_name(r.get("name", "")), "pos": "G"},
                                                       **{k: r.get(k, "") for k in ("gp", "toi", "ga", "gaa", "svs", "svs%", "so")})
                                                  for r in gk]}}
            except Exception as e:
                print(f"  iihf roster {code}: {e}")

        if not roster:  # roster page missing or empty: build one from the game lineups
            seen = {}
            for gm in games:
                lu = gm.get("_lineup")
                if not lu:
                    continue
                for grp in lu[gm["side"]]["groups"]:
                    for p in grp["players"]:
                        seen.setdefault(p["name"], {"num": p["num"], "name": p["name"], "pos": p["pos"],
                                                    "detail": ""})
            order = {"F": 0, "D": 1, "G": 2}
            roster = sorted(seen.values(), key=lambda p: (order.get(p["pos"], 3), to_int(p["num"], 99)))

        results[tc["key"]] = {
            "games": games, "standings": standings, "bracket": bracket,
            "roster": {"title": f"{event_cfg['name']} roster", "players": roster},
            "stats": stats,
        }
    return results
