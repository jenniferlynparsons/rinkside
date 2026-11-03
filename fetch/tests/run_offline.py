#!/usr/bin/env python3
"""Offline test: runs the whole refresh against saved fixture pages instead
of the live sites, checks the output, and leaves a sample data folder you
can preview the site with.

    python3 fetch/tests/run_offline.py            # writes fetch/tests/sample-data
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.dirname(HERE))

import college  # noqa: E402
import common  # noqa: E402
import iihf  # noqa: E402
import pwhl  # noqa: E402
import wiki  # noqa: E402
import fetch  # noqa: E402


def fx(name):
    with open(os.path.join(FIX, name)) as fh:
        return fh.read()


# ------------------------------------------------------------- PWHL fakes
SEASONS = {"SiteKit": {"Seasons": [
    {"season_id": "11", "season_name": "2026-27 Regular Season", "career": "1", "playoff": "0",
     "start_date": "2026-12-04", "end_date": "2027-04-19"},
    {"season_id": "10", "season_name": "2026-27 Pre-Season", "career": "0", "playoff": "0",
     "start_date": "2026-10-01", "end_date": "2026-11-30"},
    {"season_id": "9", "season_name": "2026 Playoffs", "career": "1", "playoff": "1",
     "start_date": "2026-04-28", "end_date": "2026-05-28"},
    {"season_id": "8", "season_name": "2025-26 Regular Season", "career": "1", "playoff": "0",
     "start_date": "2025-11-21", "end_date": "2026-04-27"},
    {"season_id": "7", "season_name": "2025-26 Preseason", "career": "0", "playoff": "0",
     "start_date": "2025-06-01", "end_date": "2025-11-19"},
]}}


def pg(gid, iso, h, hc, hid, v, vc, vid, venue, loc, b=None, final=False, hs="0", vs="0", status=""):
    return {"id": gid, "game_id": gid, "GameDateISO8601": iso, "home_team": hid, "visiting_team": vid,
            "home_team_name": h, "home_team_code": hc, "visiting_team_name": v, "visiting_team_code": vc,
            "home_goal_count": hs, "visiting_goal_count": vs, "final": "1" if final else "0",
            "started": "1" if final else "0", "game_status": status or "3:00 pm EST", "time_tbd": "0",
            "date_tbd": "0", "venue_name": venue, "venue_location": loc, "broadcasters": b or []}


NY, BOS, OTT, TOR, DET = ("New York Sirens", "NY", "4"), ("Boston Fleet", "BOS", "1"), \
    ("Ottawa Charge", "OTT", "5"), ("Toronto Sceptres", "TOR", "6"), ("PWHL Detroit", "DET", "10")
SCHED = {
    "10": [pg("350", "2026-11-21T13:00:00-05:00", *BOS, *NY, "Boston Sports Institute | Wellesley", "Wellesley, MA",
              final=True, hs="2", vs="3", status="Final")],
    "11": [
        pg("369", "2026-12-06T15:00:00-05:00", *NY, *BOS, "Prudential Center | Newark", "Newark, NJ"),
        pg("372", "2026-12-12T12:00:00-05:00", *DET, *NY, "Little Caesars Arena | Detroit", "Detroit, MI",
           b={"home_video_fr": [{"name": "Ion", "url": ""}], "home_video": [{"name": "SportsNet", "url": ""}]}),
        pg("380", "2026-12-19T19:00:00-05:00", *NY, *OTT, "Prudential Center | Newark", "Newark, NJ",
           b={"home_video_fr": [{"name": "Ion", "url": ""}], "home_video": [{"name": "TSN", "url": ""}]}),
        pg("385", "2026-12-22T19:00:00-05:00", *TOR, *NY, "Coca-Cola Coliseum | Toronto", "Toronto, ON",
           b={"home_video": [{"name": "Prime Video", "url": ""}]}),
        pg("390", "2026-12-06T15:00:00-05:00", *BOS, *OTT, "Agganis Arena | Boston", "Boston, MA"),
    ],
}
EAST = [{"repeatheader": 1, "name": "Eastern Conference"}] + [
    {"team_id": tid, "name": n, "rank": str(i), "games_played": "0", "regulation_wins": "0", "non_reg_wins": "0",
     "non_reg_losses": "0", "reg_losses": "0", "points": "0", "goals_for": "0", "goals_against": "0"}
    for i, (tid, n) in enumerate([("1", "Boston Fleet"), ("3", "Montréal Victoire"), ("4", "New York Sirens"),
                                  ("5", "Ottawa Charge"), ("6", "Toronto Sceptres"), ("11", "PWHL Hamilton")], 1)]
WEST = [{"repeatheader": 1, "name": "Western Conference"},
        {"team_id": "2", "name": "Minnesota Frost", "rank": "1", "games_played": "0", "points": "0"}]
ROSTER10 = [{"first_name": f, "last_name": l, "tp_jersey_number": n, "position": p, "shoots": s, "height": h,
             "hometown": ht} for f, l, n, p, s, h, ht in [
    ("Sarah", "Fillier", "10", "F", "R", "5'5", "Georgetown, ON"), ("Micah", "Zandee-Hart", "28", "D", "L", "5'9", "Saanichton, BC"),
    ("Casey", "O'Brien", "26", "F", "L", "5'7", "Milton, MA"), ("Kaley", "Doyle", "1", "G", "L", "5'8", "Sudbury, ON")]]
SCORERS8 = [{"name": "Sarah Fillier", "jersey_number": "10", "position": "F", "games_played": "29", "goals": "9",
             "assists": "14", "points": "23", "plus_minus": "-5", "penalty_minutes": "14", "shots": "104"}]
GOALIES8 = [{"name": "Kayle Osborne", "jersey_number": "82", "games_played": "27", "wins": "11", "losses": "14",
             "ot_losses": "1", "goals_against_average": "2.47", "save_percentage": "0.906", "shutouts": "4"}]
SUMMARY = {"GC": {"Gamesummary": {
    "home_team_lineup": {"goalies": [{"first_name": "Aerin", "last_name": "Frankel", "jersey_number": "31", "start": "1",
                                      "time": "60:00", "saves": 28, "goals_against": 3}],
                         "players": [{"first_name": "Megan", "last_name": "Keller", "jersey_number": "5", "position_str": "LD",
                                      "status": "C", "goals": 1, "assists": 1}]},
    "visitor_team_lineup": {"goalies": [{"first_name": "Kaley", "last_name": "Doyle", "jersey_number": "1", "start": "1",
                                         "time": "60:00", "saves": 30, "goals_against": 2}],
                            "players": [{"first_name": "Sarah", "last_name": "Fillier", "jersey_number": "10",
                                         "position_str": "C", "status": "A", "goals": 2, "assists": 0},
                                        {"first_name": "Micah", "last_name": "Zandee-Hart", "jersey_number": "28",
                                         "position_str": "RD", "status": "C", "goals": 0, "assists": 2}]},
    "goals": [{"period_id": "2", "time": "4:11", "power_play": "1", "goal_scorer": {
        "team_code": "NY", "jersey_number": "10", "first_name": "Sarah", "last_name": "Fillier"},
        "assist1_player": {"first_name": "Micah", "last_name": "Zandee-Hart"}, "scorer_goal_num": "1"}],
    "totalShots": {"home": 32, "visitor": 31}}}}


def fake_get(url, *, params=None, as_json=False, **kw):
    p = params or {}
    if "hockeytech" in url:
        view, feed, sid = p.get("view"), p.get("feed"), str(p.get("season_id", ""))
        if feed == "gc":
            return SUMMARY
        if view == "seasons":
            return SEASONS
        if view == "schedule":
            return {"SiteKit": {"Schedule": SCHED.get(sid, [])}}
        if view == "statviewtype" and p.get("type") == "standings":
            return {"SiteKit": {"Statviewtype": WEST + EAST}}
        if view == "roster":
            return {"SiteKit": {"Roster": ROSTER10 if sid == "10" else [[]]}}
        if view == "statviewtype" and p.get("type") == "topscorers":
            return {"SiteKit": {"Statviewtype": SCORERS8 if sid == "8" else []}}
        if view == "statviewtype" and p.get("type") == "topgoalies":
            return {"SiteKit": {"Statviewtype": GOALIES8 if sid == "8" else []}}
        raise AssertionError(f"unexpected PWHL call {p}")
    if "collegehockeynews" in url:
        path = url.split(".com", 1)[1]
        if path.startswith("/women/team/Princeton"):
            return fx("chn_schedule.html")
        if path.startswith("/schedules/team-cal.php"):
            return fx("chn_cal.ics")
        if path.startswith("/women/roster/Princeton"):
            return fx("chn_roster.html")
        if path.startswith("/women/roster/"):
            return fx("chn_roster_yale.html")
        if path.startswith("/women/stats/team/Princeton"):
            return fx("chn_stats.html")
        if path.startswith("/women/ratings.php"):
            return fx("chn_npi.html")
        if path.startswith("/women/standings.php"):
            return fx("chn_standings.html")
        if path.startswith("/box/final/20261031"):
            return fx("chn_box.html")
        if path.startswith("/box/"):
            raise RuntimeError("GET failed: (no fixture for this box score)")
        raise AssertionError(f"unexpected CHN call {path}")
    if "wikipedia.org" in url:
        page = p.get("page", "")
        return {"parse": {"wikitext": fx("wiki_rosters.txt" if page.endswith("rosters") else "wiki_event.txt")}}
    if "iihf.com" in url:
        if url.endswith("/schedule"):
            return fx("iihf_schedule.html")
        if url.endswith("/teams"):
            return fx("iihf_teams.html")
        if "/teams/roster/" in url:
            return fx("iihf_roster.html")
        if "/gamecenter/lineup/" in url:
            return fx("iihf_lineup.html")
        raise AssertionError(f"unexpected IIHF call {url}")
    raise AssertionError(f"unexpected call {url}")


def main():
    for mod in (college, iihf, pwhl, wiki, common):
        mod.http_get = fake_get
    # Pretend "now" is the first weekend of Worlds so the lineup logic runs.
    out = os.path.join(HERE, "sample-data")
    cache = os.path.join(HERE, ".cache-test")
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    sys.argv = ["fetch.py", "--out", out, "--cache", cache]
    fetch.main()

    def load(*p):
        with open(os.path.join(out, *p)) as fh:
            return json.load(fh)
    meta = load("meta.json")
    assert all(v["ok"] for v in meta["sources"].values()), meta["sources"]

    pr = load("teams", "princeton.json")
    assert pr["record"] == "6-0-0", pr["record"]
    g0 = pr["games"][0]
    assert g0["start"] == "2026-10-16T22:00:00Z", g0["start"]          # 6:00 ET in October = 22:00 UTC
    assert g0["comp"] == "Non-conference" and g0["home"]["name"] == "Princeton"
    assert g0["venue"].startswith("Hobey Baker"), g0["venue"]
    dela = next(g for g in pr["games"] if "Delaware" in g["away"]["name"])
    assert dela["start"] == "2026-11-24T15:30:00Z", dela["start"]      # 10:30 am ET after DST ends
    minn = next(g for g in pr["games"] if "Minnesota" in g["away"]["name"])
    assert minn["neutral"] and "Arlington" in minn["venue"], minn
    harv = next(g for g in pr["games"] if "Harvard" in g["away"]["name"])
    assert [w["name"] for w in harv["watch"]] == ["SNY", "ESPN+"], harv["watch"]
    rpi = next(g for g in pr["games"] if g["home"]["name"] == "Rensselaer")
    assert rpi["side"] == "away" and rpi["comp"] == "ECAC" and rpi["away"]["score"] == 4
    yale = next(g for g in pr["games"] if g["away"]["name"] == "Yale")
    assert yale["lineup"], "Yale box score should give a lineup"
    lu = load("lineups", f"{yale['id']}.json")
    prs = lu["home"]["groups"]
    assert prs[0]["title"] == "Goalies" and prs[0]["players"][0]["num"] == "30", prs
    sk = {p["name"]: p for p in prs[1]["players"]}
    assert sk["Riley Sorokan"]["num"] == "9" and sk["Riley Sorokan"]["stat"] == "2G", sk
    assert "Uma Corniea" not in sk
    yale_nums = {p["name"]: p["num"] for p in lu["away"]["groups"][1]["players"]}
    assert yale_nums == {"Cami Bell": "7", "Mariya Rauf": "12"}, lu["away"]   # numbers from Yale's own roster
    assert len(lu["scoring"]) == 3
    assert pr["standings"][0]["rows"][0]["us"] and pr["standings"][0]["rows"][0]["pts"] == 11
    assert pr["roster"]["players"][0]["name"] == "Mackenzie Alexander"
    assert {p["pos"] for p in pr["roster"]["players"]} == {"F", "D", "G"}
    srows = pr["stats"]["skaters"]["rows"]
    assert srows[0]["num"] == "2" and srows[0]["pts"] == 8 and len(srows) == 3, srows
    assert pr["stats"]["goalies"]["rows"][0]["svp"] == ".974"

    sr = load("teams", "sirens.json")
    assert [g["id"] for g in sr["games"]] == ["pwhl-350", "pwhl-369", "pwhl-372", "pwhl-380", "pwhl-385"]
    assert sr["games"][0]["comp"] == "Preseason" and sr["games"][0]["lineup"]
    det = sr["games"][2]
    regions = {w["name"]: w["region"] for w in det["watch"]}
    assert regions == {"ION": "US", "PWHL YouTube": "US"}, regions   # Canadian channels dropped
    assert sr["standings"][0]["title"] == "Eastern Conference"
    assert sr["roster"]["title"].startswith("2026-27 Pre-Season") and len(sr["roster"]["players"]) == 4
    assert "last season" in sr["stats"]["title"]
    lu = load("lineups", "pwhl-350.json")
    assert lu["away"]["groups"][1]["players"][0]["name"] == "Sarah Fillier", lu["away"]

    us = load("teams", "usa.json")
    ids = [g["id"] for g in us["games"]]
    assert ids == ["iihf-20261106-sui-usa", "iihf-20261108-usa-ger"], ids
    g0 = us["games"][0]
    assert g0["start"] == "2026-11-06T18:00:00Z", g0["start"]          # 19:00 in Denmark = 1 pm ET
    assert g0["status"] == "final" and g0["away"]["score"] == 6 and g0["side"] == "away"
    assert g0["venue"] == "Granly Hockey Arena, Esbjerg" and g0["lineup"]
    assert [w["name"] for w in g0["watch"]] == ["NHL Network"]
    grp = us["standings"][0]["rows"]
    assert grp[0]["code"] == "USA" and grp[0]["pts"] == 3, grp
    cze = next(r for r in grp if r["code"] == "CZE")
    assert cze["pts"] == 2 and cze["otw"] == 1, cze
    assert [b["phase"] for b in us["bracket"]] == ["Quarterfinal", "Gold medal game"]
    names = {p["name"]: p for p in us["roster"]["players"]}
    assert names["Hilary Knight"]["num"] == "21" and names["Hilary Knight"]["flag"] == "C", names
    assert names["Kendall Coyne Schofield"]["flag"] == "A" and names["Aerin Frankel"]["pos"] == "G"
    assert names["Megan Keller"]["detail"] == "Boston Fleet"
    st = {r["name"]: r for r in us["stats"]["skaters"]["rows"]}
    assert (st["Hilary Knight"]["g"], st["Hilary Knight"]["a"]) == (3, 1), st["Hilary Knight"]
    assert (st["Kendall Coyne Schofield"]["g"], st["Kendall Coyne Schofield"]["a"]) == (2, 2), st
    assert (st["Megan Keller"]["g"], st["Megan Keller"]["a"]) == (1, 2), st["Megan Keller"]
    lu = load("lineups", "iihf-20261106-sui-usa.json")
    assert lu["away"]["groups"][0]["title"] == "Goalies" and lu["away"]["groups"][0]["players"][0]["num"] == "31"
    assert len(lu["scoring"]) == 6 and lu["scoring"][0]["text"].startswith("Hilary Knight — from Kendall Coyne Schofield")
    assert "[PP1]" in lu["scoring"][1]["text"] and "[EN]" in lu["scoring"][-1]["text"]
    ca = load("teams", "can.json")
    assert ca["games"][0]["away"]["score"] == 4 and ca["standings"][0]["title"].endswith("Group B")
    cst = {r["name"]: r for r in ca["stats"]["skaters"]["rows"]}
    assert cst["Laura Stacey"]["g"] == 2 and cst["Laura Stacey"]["a"] == 1 and cst["Sarah Fillier"]["g"] == 2
    lu = load("lineups", "iihf-20261106-swe-can.json")
    assert [x["team"] for x in lu["scoring"]] == ["CAN", "SWE", "CAN", "CAN", "CAN"], lu["scoring"]
    assert lu["scoring"][3]["text"] == "Sarah Fillier" and lu["scoring"][2]["text"] == "Sarah Fillier — from Laura Stacey"
    # Captains, home games and opponent rankings
    prn = {p["name"]: p for p in pr["roster"]["players"]}
    assert prn["Uma Corniea"]["flag"] == "C" and prn["Riley Sorokan"]["flag"] == "", prn["Uma Corniea"]
    lu = load("lineups", f"{yale['id']}.json")
    assert lu["home"]["groups"][0]["players"][0]["flag"] == "C"           # Corniea in the box-score lineup
    assert pr["ranking"] == {"scope": "NPI", "describe": "national NPI ranking", "us": 2}, pr["ranking"]
    col = next(g for g in pr["games"] if g["away"]["name"] == "Colgate")
    assert col["rank"] == {"them": 5, "us": 2, "scope": "NPI"}, col.get("rank")
    minn = next(g for g in pr["games"] if g["away"]["name"] == "Minnesota")
    assert minn["rank"]["them"] == 3 and minn["neutral"]
    assert "rank" not in next(g for g in pr["games"] if g["away"]["name"] == "Cornell")   # not in the NPI table
    assert {p["name"]: p["flag"] for p in sr["roster"]["players"]}["Micah Zandee-Hart"] == "C"   # from latest lineup
    assert sr["ranking"]["us"] is None and "rank" not in sr["games"][1]                # no games played yet
    assert us["ranking"]["us"] == 1 and us["games"][1]["rank"] == {"them": 3, "us": 1, "scope": "Group A"}, us["games"][1]
    cap = {p["name"]: p["flag"] for p in us["roster"]["players"]}
    assert cap["Hilary Knight"] == "C" and cap["Kendall Coyne Schofield"] == "A"

    print("\nAll offline checks passed. Sample data in", out)


if __name__ == "__main__":
    main()
