# Rinkside

A small website for following women's hockey: Princeton (ECAC), the New York
Sirens (PWHL), and Team USA and Team Canada at IIHF tournaments.

For each team it shows the schedule and results, standings, the season roster
with jersey numbers, season stats, game-day lineups with jersey numbers, and
where to watch each game in the US. All times are Eastern, and every page
says when its data was last updated.

## How it works

```
GitHub Action wakes every 30 min
  └─ fetch/plan.py: anything worth fetching?  ── no ──▶ stop (no site contacted)
        │ yes
        └─ fetch/fetch.py ──reads──▶ College Hockey News · PWHL (HockeyTech) · Wikipedia API
              └─ writes data/*.json ─▶ published with index.html / app.js to GitHub Pages
```

### When the sources are contacted

Most wake-ups end without contacting anyone. A team's source is read only:

- **Once a day**, the first wake-up after 6 a.m. Eastern: schedule changes, TV
  listings, rosters, standings, stats. (IIHF: daily while a tournament is
  within two weeks, weekly otherwise.)
- **About an hour before a PWHL game**, for the lineups.
- **After a game should be over** (2½ hours after puck drop), and hourly after
  that until the final score is posted, giving up after 12 hours.
- **When you push a change or press Run workflow** on the Actions tab.

A source that fails is left alone for two hours. Each request identifies the
site and links back to the repo. On a game day that's a few dozen requests
spread across the day; on a quiet day, about fifteen.

- **No server, no database, no build step.** The page is plain HTML, CSS and
  JavaScript. The fetcher is Python using only the standard library.
- **If a source is down,** the site keeps showing that team's last good data
  and says so at the bottom of the page.
- **Finished box scores are fetched once** and cached between runs.

| Team | Source | What comes from it |
|---|---|---|
| Princeton | collegehockeynews.com | Schedule, results, TV, ECAC standings, roster, stats, box-score lineups |
| Sirens | thepwhl.com's stats feed (HockeyTech) | Schedule, scores, broadcasters, conference standings, roster, stats, game lineups |
| USA, Canada | Wikipedia's open API (the tournament article and its rosters article) | Schedule, scores, goal scorers, group standings, bracket, rosters with numbers, tournament points |

iihf.com blocks requests from cloud servers like GitHub's, so the IIHF teams
read Wikipedia instead, which editors keep current during tournaments. It
has no game-day lineups, so each game shows both teams' tournament rosters.
(`fetch/iihf.py` still holds a parser for iihf.com, used if you set
`iihf.source` to `"iihf"` in `config.json`.)

## Calendar feeds

Every refresh also writes calendar files next to the site:

- `calendar/all.ics` — every team in one calendar
- `calendar/princeton.ics`, `calendar/sirens.ics`, `calendar/usa.ics`, `calendar/can.ics`

The home page and each team page have **Add to Google Calendar**, **Apple or
Outlook**, and **Copy link** buttons for these. Events are in UTC (your calendar
shows them in your time zone), home games start with 🏠, final scores are added
to the title, and the description lists where to watch and links back to the
game page. Event IDs stay the same, so changes update in place. Google refreshes
subscribed calendars on its own schedule, usually every few hours.

## Set it up (one time, about 10 minutes)

1. On GitHub, create a new **public** repository named `rinkside`. (Public
   repos get GitHub Pages and unlimited Actions minutes for free.)
2. Put these files in a folder, then:
   ```bash
   cd rinkside
   git init -b main
   git add .
   git commit -m "Rinkside: women's hockey schedule site"
   git remote add origin git@github.com:jenniferlynparsons/rinkside.git
   git push -u origin main
   ```
3. In the repo on GitHub: **Settings → Pages → Build and deployment → Source:
   GitHub Actions.**
4. **Actions** tab → **Refresh and publish** → **Run workflow.** The first run
   takes a minute or two. After that it looks after itself (see above).
5. The site lives at `https://jenniferlynparsons.github.io/rinkside/`.
   On your phone, use Share → **Add to Home Screen** for an app-like icon.

## Preview on your own computer

```bash
python3 fetch/fetch.py          # pulls live data into ./data
python3 -m http.server 8000     # then open http://localhost:8000
```

To try the site without touching the live sources:

```bash
python3 fetch/tests/run_offline.py   # runs every parser against saved sample pages
python3 fetch/tests/test_plan.py     # checks when the scheduled run would contact a source
cp -r fetch/tests/sample-data data   # sample data (made-up stats) for previewing
```

## Changing what it follows — `config.json`

- **Next IIHF tournament:** change `iihf.name` / `iihf.wikipedia_title` to the
  Wikipedia article's exact title (for example `2027 IIHF Women's World
  Championship`), `iihf.local_timezone` to the host city's zone
  (`America/Toronto` for Quebec City), and `iihf.path` (`2027/ww`).
- **IIHF broadcasters:** the `iihf.watch` list. An entry with a `note` shows
  with a dashed outline and a `?` so you know it isn't confirmed. Delete the
  `note` once you've confirmed it.
- **Exhibition games** (Rivalry Series and so on) that aren't on an IIHF
  tournament page go in `extra_games`:
  ```json
  "extra_games": [
    { "team": "usa", "opponent": "Canada", "side": "away",
      "start": "2026-12-12T19:00:00-05:00", "comp": "Rivalry Series",
      "venue": "Rogers Place, Edmonton",
      "watch": [{ "name": "NHL Network", "region": "US", "url": "" }] }
  ]
  ```
  Add `"our_score"` and `"their_score"` after the game to show the result.
- **Princeton's season:** `chn.season` (`20272028` next year).

## Things to know

- **No live scores, on purpose.** While a game is on, the page says it has
  started and the score appears after the final horn. Watch the broadcast
  for the live action.
- **Lineups timing.** PWHL lineups appear about an hour before puck drop.
  College lineups come from the box score, so they appear after the game.
  IIHF games show the tournament rosters.
- **IIHF scores come from Wikipedia editors,** usually within minutes of the
  final horn. Tournament points are counted from their goal summaries.
- **Time zone and broadcasters** are set for a US viewer in New Jersey:
  `display_timezone` in `config.json`, and Canadian channels are left out.
- **College opponents' jersey numbers** come from each opponent's roster page.
  If a name is spelled differently on the box score, that player shows a dash
  instead of a number.
- **IIHF group standings** are worked out from the results using IIHF points.
  Tiebreakers between level teams aren't applied.
- **These are public pages, not official APIs.** If a site changes its layout,
  that team's data stops updating and the page footer says which source
  failed. The parsers live in `fetch/college.py`, `fetch/pwhl.py` and
  `fetch/iihf.py`; `fetch/tests/run_offline.py` checks them against saved
  copies of each page.
- **GitHub pauses scheduled workflows** in repos with no commits for 60 days.
  If the data stops refreshing over the summer, push any small change or
  re-enable the workflow from the Actions tab.
