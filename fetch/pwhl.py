"""PWHL data from HockeyTech, the stats provider behind thepwhl.com.

The key and client code are the public ones thepwhl.com itself uses in the
browser. Everything here is read-only JSON.
"""
from datetime import timedelta

from common import http_get, iso_utc, now_utc, parse_iso, to_int

FEED = "https://lscluster.hockeytech.com/feed/index.php"

# Where each broadcaster airs, so the page can say "US: ION" / "Canada: TSN".
REGION = {
    "ion": "US", "scripps": "US", "wmyd": "US", "kmcc": "US", "nbc": "US",
    "tsn": "Canada", "rds": "Canada", "cbc": "Canada", "sportsnet": "Canada",
    "prime video": "Canada", "radio-canada": "Canada", "ici": "Canada",
    "tva": "Canada", "fanduel": "US",
}


def region_of(name):
    n = name.lower()
    for k, v in REGION.items():
        if k in n:
            return v
    return ""


class PWHL:
    def __init__(self, cfg):
        self.base = {"key": cfg["key"], "client_code": cfg["client_code"],
                     "fmt": "json", "lang": "en"}

    def get(self, **params):
        return http_get(FEED, params={**self.base, **params}, as_json=True)

    def kit(self, **params):
        return self.get(feed="modulekit", **params)["SiteKit"]

    # ------------------------------------------------------------------
    def seasons(self):
        """Seasons that belong to the current campaign: the latest regular
        season, the preseason just before it, and any playoffs after it."""
        all_s = self.kit(view="seasons")["Seasons"]
        regs = [s for s in all_s if s["playoff"] == "0" and "regular" in s["season_name"].lower()]
        reg = max(regs, key=lambda s: int(s["season_id"]))
        reg_start = reg["start_date"]
        prev_regs = [s for s in regs if int(s["season_id"]) < int(reg["season_id"])]
        prev = max(prev_regs, key=lambda s: int(s["season_id"])) if prev_regs else None
        picked = []
        for s in all_s:
            if s is reg:
                picked.append((s, "PWHL"))
            elif s["playoff"] == "1" and s["start_date"] > reg_start:
                picked.append((s, "Walter Cup Playoffs"))
            elif (s["playoff"] == "0" and s is not reg and "regular" not in s["season_name"].lower()
                  and s["end_date"] >= (parse_iso(reg_start + "T00:00:00+00:00") - timedelta(days=90)).date().isoformat()
                  and s["start_date"] <= reg_start):
                picked.append((s, "Preseason"))
        return reg, prev, picked

    def build(self, team_cfg, cache):
        match = team_cfg["pwhl"]["team_name"].lower()
        reg, prev, picked = self.seasons()

        games, team_id = [], None
        for season, comp in picked:
            for g in self.kit(view="schedule", season_id=season["season_id"]).get("Schedule", []):
                names = (g["home_team_name"].lower(), g["visiting_team_name"].lower())
                if match not in names:
                    continue
                team_id = g["home_team"] if names[0] == match else g["visiting_team"]
                games.append(self.game(g, comp, match))
        games.sort(key=lambda g: g["start"])

        # Lineups for anything that has started. Finished games are cached.
        for g in games:
            # Lineups: once a game has started, or within 75 minutes of puck drop.
            if g["status"] == "scheduled" and parse_iso(g["start"]) - now_utc() > timedelta(minutes=75):
                continue
            key = f"lineup/{g['id']}"
            lu = cache.get(key) if g["status"] == "final" else None
            if lu is None:
                try:
                    lu = self.lineup(g["_gid"], g)
                except Exception as e:  # one bad box score shouldn't sink the rest
                    print(f"  pwhl lineup {g['_gid']}: {e}")
                    continue
                if g["status"] == "final":
                    cache.put(key, lu)
            g["_lineup"] = lu

        standings = self.standings(reg, team_id)
        roster, roster_title = [], reg["season_name"]
        if team_id:
            roster = self.roster(team_id, reg["season_id"])
            if not roster:  # regular-season roster not posted yet → training camp roster
                pre = next((s for s, c in picked if c == "Preseason"), None)
                if pre:
                    roster, roster_title = self.roster(team_id, pre["season_id"]), pre["season_name"]
        stats = self.stats(team_id, reg) if team_id else None
        if stats is None and team_id and prev:
            stats = self.stats(team_id, prev)
            if stats:
                stats["title"] += " (last season — new stats start with the first regular-season game)"

        # League position: points per game, then points (only once games are played).
        rows = [r for t in standings for r in t["rows"] if r["gp"] > 0]
        rows.sort(key=lambda r: (-r["pts"] / r["gp"], -r["pts"], -r["w"]))
        ranks = {r["team"]: i for i, r in enumerate(rows, 1)}
        us_rank = next((ranks[r["team"]] for r in rows if r["us"]), None)

        # Captains: the C/A marks on our side of the most recent lineup.
        captains = {}
        for g in reversed(games):
            lu = g.get("_lineup")
            if lu:
                for grp in lu[g["side"]]["groups"]:
                    for p in grp["players"]:
                        if p.get("flag") in ("C", "A"):
                            captains[p["name"]] = p["flag"]
                if captains:
                    break

        return {
            "ranking": {"scope": "PWHL", "describe": "PWHL league table (points per game)", "ranks": ranks, "us": us_rank},
            "_captains": captains,
            "games": games,
            "standings": standings,
            "roster": {"title": roster_title + " roster", "players": roster},
            "stats": stats,
        }

    # ------------------------------------------------------------------
    def game(self, g, comp, match):
        final = g.get("final") == "1"
        started = g.get("started") == "1"
        status = "final" if final else ("live" if started else "scheduled")
        start = parse_iso(g["GameDateISO8601"])
        watch = []
        b = g.get("broadcasters") or {}
        if isinstance(b, dict):
            for lst in b.values():
                for x in lst or []:
                    name = (x.get("name") or "").strip()
                    region = region_of(name)
                    if region == "Canada":
                        continue  # US viewer: Canadian channels aren't useful
                    if name and not any(w["name"].lower() == name.lower() for w in watch):
                        watch.append({"name": "ION" if name.lower() == "ion" else name,
                                      "region": region or "US", "url": x.get("url") or ""})
        # The league streams every game for US viewers.
        watch.append({"name": "PWHL YouTube", "region": "US",
                      "url": "https://www.youtube.com/@thepwhlofficial"})
        home_is_us = g["home_team_name"].lower() == match
        status_text = g.get("game_status", "")
        return {
            "id": f"pwhl-{g['id']}",
            "_gid": g["id"],
            "comp": comp,
            "start": iso_utc(start),
            "tbd": g.get("time_tbd") == "1" or g.get("date_tbd") == "1",
            "home": {"name": g["home_team_name"], "short": g["home_team_code"],
                     "score": to_int(g["home_goal_count"]) if status != "scheduled" else None},
            "away": {"name": g["visiting_team_name"], "short": g["visiting_team_code"],
                     "score": to_int(g["visiting_goal_count"]) if status != "scheduled" else None},
            "side": "home" if home_is_us else "away",
            "neutral": False,
            "venue": " · ".join(x for x in [g.get("venue_name", "").split(" | ")[0], g.get("venue_location", "")] if x),
            "status": status,
            "statusText": status_text if status != "scheduled" else "",
            "watch": watch,
            "links": [{"label": "Game centre", "url": f"https://www.thepwhl.com/en/stats/game-center/{g['id']}"}],
        }

    def lineup(self, gid, game):
        gs = self.get(feed="gc", tab="gamesummary", game_id=gid)["GC"]["Gamesummary"]

        def side(lineup, name):
            groups = []
            gl = [{"num": p.get("jersey_number", ""), "name": f"{p['first_name']} {p['last_name']}",
                   "pos": "G", "flag": "Starter" if p.get("start") == "1" else "",
                   "stat": f"{p.get('saves', 0)} SV · {p.get('goals_against', 0)} GA" if p.get("time") else ""}
                  for p in lineup.get("goalies", [])]
            sk = []
            for p in lineup.get("players", []):
                g, a = to_int(p.get("goals"), 0), to_int(p.get("assists"), 0)
                sk.append({"num": p.get("jersey_number", ""), "name": f"{p['first_name']} {p['last_name']}",
                           "pos": p.get("position_str", ""), "flag": p.get("status", "") if p.get("status") in ("C", "A") else "",
                           "stat": " ".join(x for x in [f"{g}G" if g else "", f"{a}A" if a else ""] if x)})
            order = {"C": 0, "LW": 0, "RW": 0, "F": 0, "LD": 1, "RD": 1, "D": 1}
            sk.sort(key=lambda p: (order.get(p["pos"], 2), to_int(p["num"], 99)))
            if gl:
                groups.append({"title": "Goalies", "players": gl})
            fw = [p for p in sk if order.get(p["pos"]) == 0]
            de = [p for p in sk if order.get(p["pos"]) == 1]
            other = [p for p in sk if order.get(p["pos"], 2) == 2]
            if fw:
                groups.append({"title": "Forwards", "players": fw})
            if de:
                groups.append({"title": "Defense", "players": de})
            if other:
                groups.append({"title": "Skaters", "players": other})
            return {"name": name, "groups": groups}

        scoring = []
        for gl in gs.get("goals", []) or []:
            sc = gl.get("goal_scorer") or {}
            assists = [f"{a.get('first_name','')} {a.get('last_name','')}".strip()
                       for a in (gl.get("assist1_player"), gl.get("assist2_player")) if a and a.get("last_name")]
            tags = [t for t, f in (("PP", "power_play"), ("SH", "short_handed"), ("EN", "empty_net")) if gl.get(f) == "1"]
            scoring.append({
                "period": {"1": "1st", "2": "2nd", "3": "3rd"}.get(str(gl.get("period_id")), "OT"),
                "time": gl.get("time", ""),
                "team": sc.get("team_code", ""),
                "text": f"#{sc.get('jersey_number','')} {sc.get('first_name','')} {sc.get('last_name','')}"
                        + (f" ({gl.get('scorer_goal_num')})" if gl.get("scorer_goal_num") else "")
                        + (f" — from {', '.join(assists)}" if assists else " — unassisted")
                        + (f" [{', '.join(tags)}]" if tags else ""),
            })
        shots = gs.get("totalShots") or {}
        return {
            "id": game["id"],
            "home": side(gs.get("home_team_lineup") or {}, game["home"]["name"]),
            "away": side(gs.get("visitor_team_lineup") or {}, game["away"]["name"]),
            "scoring": scoring,
            "shots": {"home": shots.get("home"), "away": shots.get("visitor")},
            "source": "PWHL / HockeyTech",
        }

    def standings(self, reg, team_id):
        rows = self.kit(view="statviewtype", type="standings", stat="conference",
                        season_id=reg["season_id"]).get("Statviewtype", [])
        tables, cur = [], None
        for r in rows:
            if r.get("repeatheader"):
                cur = {"title": r.get("name", "Standings"), "rows": []}
                tables.append(cur)
                continue
            if cur is None or "team_id" not in r:
                continue
            name = r.get("name", "")
            if " - " in name[:4]:  # clinch markers like "x - Montréal Victoire"
                name = name.split(" - ", 1)[1]
            cur["rows"].append({
                "rank": to_int(r.get("rank") or r.get("overall_rank")),
                "team": name, "us": r["team_id"] == team_id,
                "gp": to_int(r.get("games_played"), 0),
                "w": to_int(r.get("regulation_wins"), 0),
                "otw": to_int(r.get("non_reg_wins"), 0),
                "otl": to_int(r.get("non_reg_losses"), 0),
                "l": to_int(r.get("reg_losses") or r.get("losses"), 0),
                "pts": to_int(r.get("points"), 0),
                "gf": to_int(r.get("goals_for"), 0), "ga": to_int(r.get("goals_against"), 0),
            })
        # The table with our team first.
        tables.sort(key=lambda t: not any(x["us"] for x in t["rows"]))
        cols = [{"key": "gp", "label": "GP"}, {"key": "pts", "label": "PTS"}, {"key": "w", "label": "W"},
                {"key": "otw", "label": "OTW"}, {"key": "otl", "label": "OTL"}, {"key": "l", "label": "L"},
                {"key": "gf", "label": "GF"}, {"key": "ga", "label": "GA"}]
        for t in tables:
            t["columns"] = cols
            t["note"] = "Regulation win 3 pts · OT/shootout win 2 · OT/shootout loss 1"
        return tables

    def roster(self, team_id, season_id):
        out = []
        for p in self.kit(view="roster", team_id=team_id, season_id=season_id).get("Roster", []):
            if not isinstance(p, dict) or not p.get("last_name"):
                continue
            detail = " · ".join(x for x in [p.get("shoots") and f"Shoots {p['shoots']}", p.get("height"),
                                           p.get("hometown") or p.get("birthplace")] if x)
            out.append({"num": p.get("tp_jersey_number", ""), "name": f"{p['first_name']} {p['last_name']}",
                        "pos": p.get("position", ""), "detail": detail})
        posorder = {"F": 0, "LW": 0, "RW": 0, "C": 0, "D": 1, "G": 2}
        out.sort(key=lambda p: (posorder.get(p["pos"], 3), to_int(p["num"], 99)))
        return out

    def stats(self, team_id, season):
        sid = season["season_id"]
        sk = self.kit(view="statviewtype", type="topscorers", team_id=team_id, season_id=sid,
                      first=0, limit=60).get("Statviewtype", [])
        gk = self.kit(view="statviewtype", type="topgoalies", team_id=team_id, season_id=sid,
                      first=0, limit=10).get("Statviewtype", [])
        sk = [p for p in sk if isinstance(p, dict) and to_int(p.get("games_played"), 0) > 0]
        gk = [p for p in gk if isinstance(p, dict) and to_int(p.get("games_played"), 0) > 0]
        if not sk and not gk:
            return None
        return {
            "title": season["season_name"],
            "skaters": {
                "columns": [{"key": k, "label": l} for k, l in
                            [("gp", "GP"), ("g", "G"), ("a", "A"), ("pts", "PTS"), ("pm", "+/-"),
                             ("pim", "PIM"), ("sog", "SOG")]],
                "rows": [{"num": p.get("jersey_number", ""), "name": p.get("name", ""), "pos": p.get("position", ""),
                          "gp": to_int(p.get("games_played")), "g": to_int(p.get("goals")),
                          "a": to_int(p.get("assists")), "pts": to_int(p.get("points")),
                          "pm": p.get("plus_minus", ""), "pim": to_int(p.get("penalty_minutes")),
                          "sog": to_int(p.get("shots"))} for p in sk],
            },
            "goalies": {
                "columns": [{"key": k, "label": l} for k, l in
                            [("gp", "GP"), ("w", "W"), ("l", "L"), ("otl", "OTL"), ("gaa", "GAA"),
                             ("svp", "SV%"), ("so", "SO")]],
                "rows": [{"num": p.get("jersey_number", ""), "name": p.get("name", ""), "pos": "G",
                          "gp": to_int(p.get("games_played")), "w": to_int(p.get("wins")),
                          "l": to_int(p.get("losses")), "otl": to_int(p.get("ot_losses")),
                          "gaa": p.get("goals_against_average", ""), "svp": p.get("save_percentage", ""),
                          "so": to_int(p.get("shutouts"))} for p in gk],
            },
        }
