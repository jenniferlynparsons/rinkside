/* Rinkside — reads the JSON files the GitHub Action writes into data/.
   Every time is shown in Eastern time (config.json: display_timezone),
   wherever the phone happens to be. No framework, no build step. */
(() => {
  "use strict";

  const DATA = "data/";
  const state = { meta: null, teams: {}, loadedAt: 0, lineups: {}, sorts: {} };
  const $main = document.getElementById("main");
  const $nav = document.getElementById("teamnav");
  const $foot = document.getElementById("foot");

  // ------------------------------------------------------------ helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };
  // Formatters are rebuilt once the data says which time zone to use.
  let TZ = "America/New_York";
  let fTime, fDay, fLong, fFull, fStamp, fKey;
  function setZone(tz) {
    TZ = tz || TZ;
    const o = (x) => ({ timeZone: TZ, ...x });
    fTime = new Intl.DateTimeFormat("en-US", o({ hour: "numeric", minute: "2-digit" }));
    fDay = new Intl.DateTimeFormat("en-US", o({ weekday: "short", month: "short", day: "numeric" }));
    fLong = new Intl.DateTimeFormat("en-US", o({ weekday: "long", month: "long", day: "numeric" }));
    fFull = new Intl.DateTimeFormat("en-US", o({ weekday: "long", month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }));
    fStamp = new Intl.DateTimeFormat("en-US", o({ weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }));
    fKey = new Intl.DateTimeFormat("en-CA", o({ year: "numeric", month: "2-digit", day: "2-digit" }));
  }
  setZone(TZ);
  const dayKey = (d) => fKey.format(d);  // YYYY-MM-DD in Eastern time
  function dayLabel(d) {
    const diff = Math.round((Date.parse(dayKey(d)) - Date.parse(dayKey(new Date()))) / 864e5);
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    if (diff === -1) return "Yesterday";
    return fDay.format(d);
  }
  const timeLabel = (g) => (g.tbd ? "TBA" : fTime.format(new Date(g.start)));
  // "today at 2:14 PM EST", "yesterday at 9:40 PM EST", "Sun, Nov 1, 6:05 AM EST"
  function stamp(iso) {
    if (!iso) return "not yet";
    const d = new Date(iso);
    const lbl = dayLabel(d);
    if (lbl !== "Today" && lbl !== "Yesterday") return fStamp.format(d);
    const zone = fStamp.formatToParts(d).find((p) => p.type === "timeZoneName")?.value || "";
    return `${lbl.toLowerCase()} at ${fTime.format(d)} ${zone}`.trim();
  }
  const updatedOf = (key) => state.meta?.sources?.[key]?.updated;
  const started = (g) => g.status === "scheduled" && !g.tbd && new Date(g.start) <= Date.now();
  const teamOf = (key) => state.meta.teams.find((t) => t.key === key) || { key, short: key, color: "" };
  const dot = (key) => `<span class="dot" style="--c:${esc(teamOf(key).color)}" aria-hidden="true"></span>`;

  function perspective(g) {
    const us = g.side === "home" ? g.home : g.away;
    const them = g.side === "home" ? g.away : g.home;
    let result = "";
    if (g.status === "final" && us.score != null && them.score != null) {
      result = us.score > them.score ? "W" : us.score < them.score ? "L" : "T";
    }
    const prefix = g.neutral ? "vs" : g.side === "home" ? "vs" : "at";
    return { us, them, result, prefix };
  }

  function watchHtml(list) {
    list = (list || []).filter((w) => w.region !== "Canada");  // US viewer
    if (!list.length) return "";
    const pill = (w) => {
      const rg = "";
      const cls = "pill" + (w.note ? " unconfirmed" : "");
      const title = w.note ? ` title="${esc(w.note)}"` : "";
      const label = esc(w.name) + (w.note ? "?" : "");
      return w.url
        ? `<a class="${cls}" href="${esc(w.url)}" target="_blank" rel="noopener"${title}>${label}${rg}</a>`
        : `<span class="${cls}"${title}>${label}${rg}</span>`;
    };
    return `<div class="watch">${list.map(pill).join("")}</div>`;
  }

  function scoreHtml(g) {
    const p = perspective(g);
    if (g.status === "live") {
      return `<span class="live-tag">Live</span> <span class="score">${p.us.score ?? 0}–${p.them.score ?? 0}</span>`;
    }
    if (g.status === "final") {
      const extra = (g.statusText || "").match(/\b(OT|SO|\dOT)\b/i)?.[0];
      return `<span class="score"><span class="res ${p.result}">${p.result}</span>${p.us.score}–${p.them.score}${extra ? ` <small>${esc(extra.toUpperCase())}</small>` : ""}</span>`;
    }
    return "";
  }

  function gameRow(g, { showTeam = true } = {}) {
    const p = perspective(g);
    const sub = [g.comp, g.venue].filter(Boolean).map(esc).join(" — ");
    const right = g.status === "scheduled" ? "" : scoreHtml(g);
    return `<div class="game">
      <div class="t">${g.status === "final" ? "Final" : g.status === "live" || started(g) ? "Started" : esc(timeLabel(g))}</div>
      <div>
        <div class="who">${showTeam ? dot(g.team) : ""}<a class="opp" href="#/game/${encodeURIComponent(g.id)}">${showTeam ? esc(teamOf(g.team).short) + " " : ""}<span class="ha">${p.prefix}</span> ${esc(p.them.name)}</a></div>
        ${right ? `<div>${right}</div>` : ""}
        <div class="sub">${sub}</div>
        ${started(g) ? `<div class="sub">Score posts after the final horn.</div>` : ""}
        ${g.status !== "final" ? watchHtml(g.watch) : ""}
      </div>
    </div>`;
  }

  function allGames(filter) {
    const out = [];
    for (const t of Object.values(state.teams)) {
      if (filter && !filter.includes(t.key)) continue;
      for (const g of t.games || []) out.push(g);
    }
    return out.sort((a, b) => a.start.localeCompare(b.start));
  }

  function agenda(games, { showTeam = true, pastDays = 4, futureDays = 21, minFuture = 5 } = {}) {
    const now = Date.now();
    const past = games.filter((g) => g.status === "final" && now - new Date(g.start) < pastDays * 864e5);
    const live = games.filter((g) => g.status === "live");
    let future = games.filter((g) => g.status === "scheduled" && new Date(g.start) - now < futureDays * 864e5 && new Date(g.start) > now - 6 * 36e5);
    if (future.length < minFuture) future = games.filter((g) => g.status === "scheduled" && new Date(g.start) > now - 6 * 36e5).slice(0, minFuture);
    const byDay = (list) => {
      const days = new Map();
      for (const g of list) {
        const d = new Date(g.start); const k = dayKey(d);
        if (!days.has(k)) days.set(k, { d, games: [] });
        days.get(k).games.push(g);
      }
      return [...days.values()].map(({ d, games }) => {
        const today = dayKey(d) === dayKey(new Date());
        return `<section class="day${today ? " today" : ""}"><h2>${esc(dayLabel(d))}</h2>${games.map((g) => gameRow(g, { showTeam })).join("")}</section>`;
      }).join("");
    };
    let html = "";
    if (past.length) html += byDay(past);
    html += `<div class="nowline" role="separator">${live.length ? "Live now" : "Now"}</div>`;
    if (live.length) html += `<section class="day today">${live.map((g) => gameRow(g, { showTeam })).join("")}</section>`;
    html += future.length ? byDay(future) : `<p class="empty">No upcoming games on the schedule yet.</p>`;
    return html;
  }

  // ------------------------------------------------------------ views
  function viewHome() {
    const keys = state.meta.teams.map((t) => t.key);
    let filter = store.get("rinkside.filter", keys).filter((k) => keys.includes(k));
    if (!filter.length) filter = keys;
    const games = allGames(filter);
    const now = Date.now();
    const next = games.find((g) => g.status === "live") ||
      games.find((g) => g.status === "scheduled" && new Date(g.start) > now - 3 * 36e5);

    let hero = "";
    if (next) {
      const p = perspective(next);
      const d = new Date(next.start);
      const live = next.status === "live";
      hero = `<section class="hero${live ? " live" : ""}" aria-label="Next game">
        <div class="when"><small>${live ? "Live now" : started(next) ? "Started at " + esc(fTime.format(d)) + ", score posts after the game" : esc(dayLabel(d) === fDay.format(d) ? fLong.format(d) : dayLabel(d))}</small>${live ? `${p.us.score ?? 0}–${p.them.score ?? 0}` : started(next) ? "Underway" : esc(timeLabel(next))}</div>
        <div class="match">${dot(next.team)}<strong>${esc(teamOf(next.team).name)}</strong> <span>${p.prefix} ${esc(p.them.name)}</span></div>
        <div class="meta">${[next.comp, next.venue].filter(Boolean).map(esc).join(" — ")}</div>
        ${watchHtml(next.watch)}
        <a class="more" href="#/game/${encodeURIComponent(next.id)}">${live || next.lineup ? "Lineups and details" : "Game details"}</a>
      </section>`;
    }
    const filters = state.meta.teams.map((t) =>
      `<button type="button" data-team="${esc(t.key)}" aria-pressed="${filter.includes(t.key)}">${dot(t.key)}${esc(t.short)}</button>`).join("");

    const latest = filter.map(updatedOf).filter(Boolean).sort().pop();
    $main.innerHTML = `${hero}
      <p class="updated">Last updated ${esc(stamp(latest))}</p>
      <div class="filters" role="group" aria-label="Show games for"><span class="lbl">Showing</span>${filters}</div>
      ${agenda(games)}`;
    $main.querySelectorAll(".filters button").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.team;
      let f = store.get("rinkside.filter", keys);
      f = f.includes(k) ? f.filter((x) => x !== k) : [...f, k];
      if (!f.length) f = keys;
      store.set("rinkside.filter", f);
      viewHome();
    }));
  }

  function tableHtml(id, cols, rows, { nameCol = "name", numbered = true, team = "" } = {}) {
    const sort = state.sorts[id];
    let data = [...rows];
    if (sort) {
      data.sort((a, b) => {
        const x = a[sort.key], y = b[sort.key];
        const nx = parseFloat(x), ny = parseFloat(y);
        const c = !isNaN(nx) && !isNaN(ny) ? nx - ny : String(x ?? "").localeCompare(String(y ?? ""));
        return sort.dir === "asc" ? c : -c;
      });
    }
    const th = cols.map((c) => {
      const s = sort?.key === c.key ? ` aria-sort="${sort.dir === "asc" ? "ascending" : "descending"}"` : "";
      return `<th scope="col"><button type="button" data-sort="${esc(c.key)}"${s}>${esc(c.label)}</button></th>`;
    }).join("");
    const color = team ? ` style="--c:${esc(teamOf(team).color)}"` : "";
    return `<div class="tablewrap"><table class="grid" data-table="${esc(id)}"${color}>
      <thead><tr>${numbered ? `<th class="l" scope="col">#</th>` : ""}<th class="l" scope="col">${nameCol === "team" ? "Team" : "Player"}</th>${th}</tr></thead>
      <tbody>${data.map((r) => `<tr class="${r.us ? "us" : ""}">${numbered ? `<td class="n">${esc(r.num || r.rank || "")}</td>` : ""}<td class="l name">${esc(r[nameCol])}${r.pos && nameCol === "name" ? ` <small>${esc(r.pos)}</small>` : ""}</td>${cols.map((c) => `<td>${esc(r[c.key] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>`;
  }
  function wireSort(rerender) {
    $main.querySelectorAll("table.grid th button[data-sort]").forEach((b) => b.addEventListener("click", () => {
      const id = b.closest("table").dataset.table;
      const cur = state.sorts[id];
      state.sorts[id] = { key: b.dataset.sort, dir: cur?.key === b.dataset.sort && cur.dir === "desc" ? "asc" : "desc" };
      rerender();
    }));
  }

  const POS_GROUP = (p) => (/^(G|GK)$/.test(p) ? "Goalies" : /^(D|LD|RD)$/.test(p) ? "Defense" : /^(F|C|LW|RW|W)$/.test(p) ? "Forwards" : "Players");
  function detailSpans(s) {
    return String(s || "").split(" · ").filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join("");
  }
  function playerList(players, team, withStat = false) {
    return `<ul class="roster" style="--c:${esc(teamOf(team).color)}">${players.map((p) => `<li>
      <span class="jersey${p.num ? "" : " empty"}" aria-label="${p.num ? "Number " + esc(p.num) : "No number listed"}">${esc(p.num || "–")}</span>
      <span class="nm">${esc(p.name)}${p.flag && p.flag.length <= 2 ? `<span class="flag" title="${p.flag === "C" ? "Captain" : "Alternate captain"}">${esc(p.flag)}</span>` : ""}${p.pos && withStat ? ` <small>${esc(p.pos)}</small>` : ""}</span>
      ${withStat ? `<span class="stat">${esc(p.stat || "")}</span>` : `<span class="dt">${detailSpans(p.detail)}</span>`}
    </li>`).join("")}</ul>`;
  }

  function viewTeam(key, tab) {
    const t = state.teams[key];
    if (!t) { $main.innerHTML = `<p class="empty">That team isn't in the data yet. <a href="#/">Back to all games</a></p>`; return; }
    tab = tab || "games";
    const tabs = [["games", "Games"], ["standings", "Standings"], ["roster", "Roster"], ["stats", "Stats"]];
    let body = "";
    if (tab === "games") {
      const games = t.games || [];
      const upcoming = games.filter((g) => g.status !== "final");
      const done = games.filter((g) => g.status === "final");
      body = `<section class="block"><h2>Coming up</h2>${upcoming.length ? upcoming.map((g) => gameRowDated(g)).join("") : `<p class="empty">Nothing scheduled right now.</p>`}</section>
        <section class="block"><h2>Results</h2>${done.length ? [...done].reverse().map((g) => gameRowDated(g)).join("") : `<p class="empty">No results yet this season.</p>`}</section>`;
    } else if (tab === "standings") {
      body = (t.standings || []).map((s, i) => `<section class="block"><h2>${esc(s.title)}</h2>
        ${tableHtml(`st-${key}-${i}`, s.columns, s.rows, { nameCol: "team" })}
        ${s.note ? `<p class="note">${esc(s.note)}</p>` : ""}</section>`).join("") || `<p class="empty">Standings will appear once the league posts them.</p>`;
      if (t.bracket?.length) {
        body += `<section class="block"><h2>Medal round</h2><ul class="bracket">${t.bracket.map((b) => {
          const d = new Date(b.start);
          const score = b.hs != null && b.as != null ? `${b.hs}–${b.as}` : `${esc(fDay.format(d))}, ${esc(fTime.format(d))}`;
          return `<li class="${b.us ? "us" : ""}"><span class="ph">${esc(b.phase)}</span><span>${esc(b.home)} vs ${esc(b.away)}</span><span>${score}</span></li>`;
        }).join("")}</ul><p class="note">Opponents fill in as the group stage finishes.</p></section>`;
      }
    } else if (tab === "roster") {
      const players = t.roster?.players || [];
      if (!players.length) body = `<p class="empty">The roster hasn't been posted yet.</p>`;
      else {
        const groups = {};
        for (const p of players) (groups[POS_GROUP(p.pos)] ||= []).push(p);
        body = `<section class="block"><h2>${esc(t.roster.title)}</h2>${["Forwards", "Defense", "Goalies", "Players"].filter((g) => groups[g])
          .map((g) => `<h3 class="posgroup">${g}</h3>${playerList(groups[g], key)}`).join("")}</section>`;
      }
    } else if (tab === "stats") {
      const s = t.stats;
      if (!s || (!s.skaters?.rows?.length && !s.goalies?.rows?.length)) body = `<p class="empty">Stats start with the first game.</p>`;
      else body = `<p class="note">${esc(s.title)}. Tap a column to sort.</p>
        ${s.skaters?.rows?.length ? `<section class="block"><h2>Skaters</h2>${tableHtml(`sk-${key}`, s.skaters.columns, s.skaters.rows, { team: key })}</section>` : ""}
        ${s.goalies?.rows?.length ? `<section class="block"><h2>Goalies</h2>${tableHtml(`gk-${key}`, s.goalies.columns, s.goalies.rows, { team: key })}</section>` : ""}`;
    }
    const rec = t.record ? `${t.record} overall` : "";
    $main.innerHTML = `<div class="teamhead">${dot(key)}<div><h1>${esc(t.name)}</h1><p>${[t.league, t.event, rec].filter(Boolean).map(esc).join(" — ")}</p><p class="updated">Updated ${esc(stamp(updatedOf(key)))}</p></div></div>
      <nav class="tabs" aria-label="${esc(t.name)} sections">${tabs.map(([k, l]) => `<a href="#/team/${key}/${k}"${k === tab ? ' aria-current="page"' : ""}>${l}</a>`).join("")}</nav>
      ${body}`;
    wireSort(() => viewTeam(key, tab));
  }

  function gameRowDated(g) {
    // Team pages: the date matters more than the team dot.
    const d = new Date(g.start);
    const p = perspective(g);
    const sub = [g.comp, g.venue].filter(Boolean).map(esc).join(" — ");
    return `<div class="game">
      <div class="t">${esc(fDay.format(d).split(",")[1]?.trim() || fDay.format(d))}<small>${esc(fDay.format(d).split(",")[0])}${g.status === "final" ? "" : ", " + esc(timeLabel(g))}</small></div>
      <div>
        <div class="who"><a class="opp" href="#/game/${encodeURIComponent(g.id)}"><span class="ha">${p.prefix}</span> ${esc(p.them.name)}</a></div>
        ${g.status !== "scheduled" ? `<div>${scoreHtml(g)}</div>` : ""}
        <div class="sub">${sub}</div>
        ${g.status !== "final" ? watchHtml(g.watch) : ""}
      </div></div>`;
  }

  async function viewGame(id) {
    const g = allGames().find((x) => x.id === id);
    if (!g) { $main.innerHTML = `<p class="empty">That game isn't on any schedule we follow. <a href="#/">Back to all games</a></p>`; return; }
    const d = new Date(g.start);
    const p = perspective(g);
    const mid = g.status === "scheduled"
      ? `${esc(timeLabel(g))}<small>${esc(dayLabel(d))}</small>`
      : `${g.away.score ?? 0}–${g.home.score ?? 0}<small>${g.status === "live" ? '<span class="live-tag">Live</span>' : esc(g.statusText || "Final")}</small>`;
    const links = (g.links || []).map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>`).join(", ");
    $main.innerHTML = `<div class="gamehead">
        <div class="comp">${dot(g.team)} ${esc(teamOf(g.team).name)} — ${esc(g.comp)}</div>
        <div class="board">
          <div class="side">${esc(g.away.name)}<small>${g.neutral ? "" : "Away"}</small></div>
          <div class="mid">${mid}</div>
          <div class="side away">${esc(g.home.name)}<small>${g.neutral ? "" : "Home"}</small></div>
        </div>
        <dl class="facts">
          <dt>When</dt><dd>${g.tbd ? esc(fLong.format(d)) + ", time to be announced" : esc(fFull.format(d))}</dd>
          ${g.venue ? `<dt>Where</dt><dd>${esc(g.venue)}</dd>` : ""}
          ${links ? `<dt>More</dt><dd>${links}</dd>` : ""}
          <dt>Updated</dt><dd>${esc(stamp(updatedOf(g.team)))}${started(g) ? " — the score posts after the final horn" : ""}</dd>
        </dl>
        ${g.watch?.length ? `<section class="block"><h2>Where to watch</h2>${watchHtml(g.watch)}${g.watch.some((w) => w.note) ? `<p class="note">Listings marked ? aren't confirmed for this game yet.</p>` : ""}</section>` : ""}
      </div>
      <section class="block" id="lineup"><h2>Lineups</h2><p class="empty">${g.lineup ? "Loading lineups…" : lineupEmpty(g)}</p></section>`;
    if (!g.lineup) return;
    try {
      const lu = state.lineups[id] || await (await fetch(`${DATA}lineups/${encodeURIComponent(id)}.json?v=${state.loadedAt}`)).json();
      state.lineups[id] = lu;
      renderLineup(g, lu);
    } catch {
      document.querySelector("#lineup .empty").textContent = "Couldn't load the lineups. Try again in a minute.";
    }
  }
  function lineupEmpty(g) {
    if (g.status === "final") return "No lineup was published for this game.";
    if (g.team === "princeton") return "College lineups appear here after the final horn, from the box score.";
    return "Lineups appear here about an hour before puck drop.";
  }

  function renderLineup(g, lu) {
    const ourSide = g.side;
    const sides = ourSide === "home" ? ["home", "away"] : ["away", "home"];
    const col = (s) => {
      const team = lu[s];
      const key = s === ourSide ? g.team : "";
      const groups = (team?.groups || []).map((gr) => `<h3 class="posgroup">${esc(gr.title)}</h3>${playerList(gr.players, key || "_", true)}`).join("");
      return `<div data-side="${s}"${s !== ourSide ? " hidden" : ""}><h3>${esc(team?.name || "")}</h3>${groups || `<p class="empty">No lineup listed.</p>`}</div>`;
    };
    const scoring = (lu.scoring || []).length
      ? `<section class="block"><h2>Scoring</h2><ul class="scoring">${lu.scoring.map((s) => `<li><span class="when">${esc(s.period)} ${esc(s.time)}</span><span><strong>${esc(s.team)}</strong> ${esc(s.text)}</span></li>`).join("")}</ul></section>` : "";
    document.getElementById("lineup").innerHTML = `<h2>Lineups</h2>
      <div class="switch" role="group" aria-label="Choose team">${sides.map((s) => `<button type="button" data-side="${s}" aria-pressed="${s === ourSide}">${esc(lu[s]?.name || s)}</button>`).join("")}</div>
      <div class="lineups">${sides.map(col).join("")}</div>
      <p class="note">From ${esc(lu.source || "the official game report")}.</p>${scoring}`;
    document.querySelectorAll("#lineup .switch button").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#lineup .switch button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      document.querySelectorAll("#lineup .lineups > div").forEach((dv) => { dv.hidden = dv.dataset.side !== b.dataset.side; });
    }));
  }

  // ------------------------------------------------------------ chrome
  function renderNav(route) {
    $nav.innerHTML = state.meta.teams.map((t) =>
      `<a href="#/team/${esc(t.key)}" style="--c:${esc(t.color)}"${route[0] === "team" && route[1] === t.key ? ' aria-current="page"' : ""}>${esc(t.short)}</a>`).join("");
  }
  function renderFoot() {
    const src = Object.entries(state.meta.sources || {});
    const bad = src.filter(([, v]) => !v.ok);
    $foot.innerHTML = `<p>All times Eastern. Scores and lineups update after each game; schedules, rosters and standings once a day.</p>
      ${bad.map(([k, v]) => `<p class="bad">${esc(teamOf(k).short)}: couldn't reach ${esc(v.label)} on the last try. Showing what we had as of ${esc(stamp(v.updated))}.</p>`).join("")}
      <p>Sources: College Hockey News, the PWHL (HockeyTech), and IIHF.com. Always check the broadcaster before settling in.</p>`;
  }

  function route() {
    const r = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    renderNav(r);
    if (r[0] === "team") viewTeam(r[1], r[2]);
    else if (r[0] === "game") viewGame(r.slice(1).join("/"));
    else viewHome();
    renderFoot();
  }

  // ------------------------------------------------------------ data
  async function load(force = false) {
    const v = Math.floor(Date.now() / 60000);
    try {
      const meta = await (await fetch(`${DATA}meta.json?v=${v}`, { cache: force ? "reload" : "default" })).json();
      const teams = await Promise.all(meta.teams.map(async (t) => {
        try { return await (await fetch(`${DATA}teams/${t.key}.json?v=${v}`)).json(); } catch { return null; }
      }));
      state.meta = meta;
      setZone(meta.timezone);
      state.teams = Object.fromEntries(teams.filter(Boolean).map((t) => [t.key, t]));
      state.loadedAt = v;
      state.lineups = {};
      const y = window.scrollY;
      route();
      if (!force) window.scrollTo(0, y);
    } catch {
      if (!state.meta) $main.innerHTML = `<p class="empty">Couldn't load the schedule data. If this is a fresh setup, the first data refresh may still be running — check back in a few minutes.</p>`;
    }
    schedule();
  }
  let timer;
  function schedule() {
    clearTimeout(timer);
    const live = state.meta && allGames().some((g) => g.status === "live");
    timer = setTimeout(() => { if (document.visibilityState === "visible") load(); else schedule(); }, (live ? 3 : 15) * 60000);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() / 60000 - state.loadedAt > 5) load();
  });
  window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); $main.focus({ preventScroll: true }); });
  load();
})();
