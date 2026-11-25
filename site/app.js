(function () {
  'use strict';
  const SPORTS = { nfl: 'NFL', nba: 'NBA', nhl: 'NHL', mlb: 'MLB', ufc: 'UFC', dwcs: 'DWCS' };
  const SITE_VERSION = '0.3.5';
  const params = new URLSearchParams(location.search);
  const localHost = ['localhost', '127.0.0.1', ''].includes(location.hostname);
  const state = { tz: 'America/New_York', date: null, filter: 'all', latest: null, days: {}, loading: true, error: '', open: new Set(),
    offset: 0, statusOpen: false, health: null, demo: false, animate: true, banner: '', loadError: '' };

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const now = () => Date.now() + state.offset;
  const odds = (n) => (n == null ? '' : n > 0 ? '+' + Math.round(n) : '\u2212' + Math.abs(Math.round(n)));
  const pct = (x) => (x * 100).toFixed(1) + '%';
  const units = (u) => (u > 0 ? '+' : u < 0 ? '\u2212' : '') + Math.abs(u).toFixed(2) + 'u';
  const dash = '\u2013';
  const wlv = (b) => b.w + dash + b.l + dash + b.v;
  const etKey = (ms) => new Intl.DateTimeFormat('en-CA', { timeZone: state.tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms));
  const today = () => etKey(now());
  const addDays = (k, n) => new Date(Date.UTC(+k.slice(0, 4), +k.slice(5, 7) - 1, +k.slice(8, 10) + n)).toISOString().slice(0, 10);
  const validKey = (k) => /^\d{4}-\d{2}-\d{2}$/.test(k || '') && addDays(k, 0) === k;
  const clock = (iso) => new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(iso));
  const fmtDay = (k, o) => new Intl.DateTimeFormat(undefined, Object.assign({ timeZone: 'UTC' }, o)).format(new Date(k + 'T12:00:00Z'));
  const shortDay = (k) => (k === today() ? 'Today' : k === addDays(today(), -1) ? 'Yesterday' : k === addDays(today(), 1) ? 'Tomorrow' : fmtDay(k, { weekday: 'short', month: 'short', day: 'numeric' }));
  const longDay = (k) => fmtDay(k, { weekday: 'long', month: 'short', day: 'numeric' });
  const when = (k) => (k === today() ? 'today' : k === addDays(today(), -1) ? 'yesterday' : 'on ' + longDay(k));
  const mins = (iso) => Math.round((Date.parse(iso) - now()) / 60000);
  const away = (g) => (g.kind === 'bout' ? g.home + ' vs ' + g.away : g.away + ' at ' + g.home);
  const typo = (s) => String(s == null ? '' : s).replace(/(^|[\s(])-(?=\d)/g, '$1\u2212');
  const sum = (a, f) => a.reduce((t, x) => t + f(x), 0);

  /* ---------- data ---------- */
  async function fetchJson(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) {
      let why = '';
      try { const b = await r.json(); why = b.detail || b.error || ''; } catch (e) { /* not JSON */ }
      throw new Error(why || 'HTTP ' + r.status);
    }
    return r.json();
  }
  function hint(msg) {
    if (/is not set/i.test(msg)) return 'A variable is missing in Vercel. Open the project, Settings, Environment Variables, add it for all environments, then Redeploy.';
    if (/401|403|unauthori[sz]ed|forbidden/i.test(msg)) return 'Turso rejected the token. Create a new read-only token, update TURSO_READ_TOKEN in Vercel, then Redeploy.';
    if (/no such table/i.test(msg)) return 'The database exists but is empty. In GitHub, run the Pipeline workflow with task schedule.';
    if (/404|fetch failed|ENOTFOUND|abort/i.test(msg)) return 'Vercel could not reach the database. Check that TURSO_URL looks like libsql://name-org.turso.io.';
    return 'Open /api/health on this site for details.';
  }
  function setLatest(d) {
    state.latest = d;
    state.tz = d.timezone || state.tz;
    state.demo = d.source === 'demo';
    state.offset = state.demo ? Date.parse(d.generated_utc) - Date.now() : 0;
  }
  async function loadLatest() {
    try {
      if (params.has('demo')) throw new Error('demo');
      setLatest(await fetchJson('/api/latest'));
      state.banner = '';
    } catch (e) {
      state.loadError = e.message;
      if (!state.latest && (params.has('demo') || (localHost && !params.has('live')))) {
        try { setLatest(await fetchJson('demo/latest.json')); state.banner = ''; } catch (e2) { state.error = 'Could not load picks.'; }
      } else if (state.latest) state.banner = 'Offline or delayed. Showing the last data received.';
      else state.error = 'Could not load picks: ' + e.message + '. ' + hint(e.message);
    }
  }
  async function loadDay(date, force) {
    if (date === today() || !state.latest && !state.error) return;
    const cached = state.days[date];
    if (cached && !force && Date.now() - cached.at < (date < addDays(today(), -2) ? 3600000 : 60000)) return;
    state.loading = !cached; state.error = '';
    try {
      if (state.demo) state.days[date] = { at: Date.now(), games: state.latest.games.filter((g) => etKey(Date.parse(g.start_utc)) === date) };
      else state.days[date] = { at: Date.now(), games: (await fetchJson('/api/day?date=' + date)).games };
    } catch (e) { if (!cached) state.error = 'Could not load ' + longDay(date) + '.'; }
    state.loading = false;
  }
  function dayGames() {
    if (state.date === today()) return state.latest ? state.latest.games.filter((g) => etKey(Date.parse(g.start_utc)) === state.date) : null;
    return state.days[state.date] ? state.days[state.date].games : null;
  }

  /* ---------- views ---------- */
  function renderNav() {
    const isToday = state.date === today();
    $('#dateLabel').textContent = fmtDay(state.date, { weekday: 'short', month: 'short', day: 'numeric' });
    const input = $('#dateInput'); input.value = state.date;
    const r = state.latest && state.latest.date_range;
    input.min = r && r.min ? r.min : ''; input.max = addDays(today(), 14);
    $('#prev').disabled = !!(r && r.min && state.date <= r.min);
    $('#next').disabled = state.date >= addDays(today(), 14);
    $('#todayBtn').hidden = isToday;
  }

  function dayRecord(games) {
    const b = { w: 0, l: 0, v: 0, units: 0, pending: 0 };
    games.forEach((g) => {
      if (!g.pick || g.pick.verdict !== 'PLAY') return;
      if (g.grade && ['W', 'L', 'V'].includes(g.grade.grade)) { b[g.grade.grade.toLowerCase()] += 1; b.units += g.grade.profit_units || 0; } else b.pending += 1;
    });
    return b;
  }

  function renderSummary(all, games) {
    const el = $('#summary');
    if (!all) { el.innerHTML = '<h1>&nbsp;</h1>'; return; }
    const plays = games.filter((g) => g.pick && g.pick.verdict === 'PLAY');
    const analysed = games.filter((g) => g.pick).length;
    const rec = dayRecord(games);
    const label = state.filter === 'all' ? '' : SPORTS[state.filter] + ' ';
    let h, p;
    if (!games.length) { h = 'No ' + label + 'games ' + when(state.date); p = state.date > today() ? 'The schedule for this day has not been published yet.' : 'Nothing is stored for this day. Leagues in their off-season simply have no games.'; }
    else if (plays.length) {
      h = plays.length + ' ' + label + (plays.length === 1 ? 'play ' : 'plays ') + when(state.date);
      const bits = [games.length + (games.length === 1 ? ' game' : ' games')];
      if (rec.w + rec.l + rec.v) bits.push(rec.w + ' won, ' + rec.l + ' lost' + (rec.v ? ', ' + rec.v + ' void' : ''));
      if (rec.pending) bits.push(rec.pending + ' to settle');
      p = esc(bits.join('. ')) + '.' + (rec.w + rec.l ? ' <span class="' + (rec.units >= 0 ? 'pos' : 'neg') + '">' + units(rec.units) + '</span>' : '');
    } else if (analysed) {
      h = 'No ' + label + 'plays ' + when(state.date); p = analysed + ' of ' + games.length + ' games analysed, and every one was a pass.';
      const best = games.filter((g) => g.pick && g.pick.edge != null && g.pick.lean_name).sort((a, b) => b.pick.edge - a.pick.edge)[0];
      const min = state.latest && state.latest.thresholds ? state.latest.thresholds.play_min_edge : 0.025;
      if (best) p += ' Closest to a play: ' + best.pick.lean_name + ' at ' + (best.pick.edge >= 0 ? '+' : '\u2212') + Math.abs(best.pick.edge * 100).toFixed(1) + '% edge, against a ' + (min * 100).toFixed(1) + '% minimum.';
    }
    else { h = games.length + ' ' + label + (games.length === 1 ? 'game ' : 'games ') + when(state.date); p = 'Analysis posts about 30 minutes before each game and 90 minutes before the first fight on a card.'; }
    const ov = state.latest && state.latest.records && (state.filter === 'all' ? state.latest.records.overall : (state.latest.records.by_sport || {})[state.filter]);
    const record = ov ? '<div class="record"><span>Overall <b>' + wlv(ov) + '</b>' + (ov.win_pct != null ? ', ' + ov.win_pct + '%' : '') + (ov.units ? ', ' + units(ov.units) : '') + '</span></div>' : '';
    el.innerHTML = '<h1>' + esc(h) + '</h1><p>' + (p.includes('<span') ? p : esc(p)) + '</p>' + record;
  }

  function renderTabs(all) {
    const present = new Set((all || []).map((g) => g.sport)); present.add(state.filter === 'all' ? 'all' : state.filter);
    const keys = ['all'].concat(Object.keys(SPORTS).filter((k) => present.has(k)));
    $('#tabs').innerHTML = keys.map((k) => '<button class="tab" data-sport="' + k + '" aria-pressed="' + (state.filter === k) + '">' + (k === 'all' ? 'All' : SPORTS[k]) + '</button>').join('');
  }

  function detail(g) {
    const p = g.pick, n = p.narrative || {};
    const rows = [['Market', n.market], ['Matchup', n.matchup], ['Context', n.context], ['Projection', n.projection], ['Risk', n.risk]]
      .filter((r) => r[1]).map((r) => '<dt>' + r[0] + '</dt><dd>' + esc(typo(r[1])) + '</dd>').join('');
    const res = g.grade && ['W', 'L', 'V'].includes(g.grade.grade)
      ? '<p><b class="' + g.grade.grade.toLowerCase() + '">Result: ' + g.grade.grade + '</b>, ' + esc(g.grade.reason || '') +
        (g.grade.closing_odds != null ? '. Closing line ' + odds(g.grade.closing_odds) + (g.grade.clv != null ? ', closing-line value ' + (g.grade.clv * 100).toFixed(1) + '%' : '') : '') + '.</p>' : '';
    const inputs = Object.entries(p.inputs || {}).map(([k, v]) => esc(k.replace('_', ' ')) + (v.available ? '' : ' (unavailable)')).join(', ');
    return '<p><b>' + esc(typo(p.headline)) + '</b></p>' + res +
      '<ul>' + (n.thesis || []).map((t) => '<li>' + esc(typo(t)) + '</li>').join('') + '</ul><dl>' + rows + '</dl>' +
      '<p class="fine">Coverage ' + Math.round(p.coverage * 100) + '%' + (p.unavailable && p.unavailable.length ? ', missing ' + esc(p.unavailable.join(', ')) : '') +
      '. Inputs: ' + inputs + '. Posted ' + esc(clock(p.published_utc)) + (p.tag === 'LATE' ? ' (late)' : '') + ', locked as <code>' + esc(p.hash) + '</code>.</p>';
  }

  function row(g, kind) {
    const p = g.pick; const open = state.open.has(g.id);
    let l1, l2 = '', out = '';
    if (kind === 'plays') {
      l1 = esc(p.selection_name) + ' ' + odds(p.odds);
      l2 = (p.top_pick ? '<span class="top">Top pick</span>, ' : '') + (g.kind === 'bout' ? 'vs ' + esc(p.selection === 'home' ? g.away : g.home) : p.selection === 'home' ? 'vs ' + esc(g.away) : 'at ' + esc(g.home));
      if (g.grade && ['W', 'L', 'V'].includes(g.grade.grade)) out = '<span class="big ' + g.grade.grade.toLowerCase() + '">' + g.grade.grade + '</span><span class="sub">' + (g.grade.grade === 'V' ? 'void' : units(g.grade.profit_units || 0)) + '</span>';
      else out = '<span class="big">' + p.units + 'u</span>' + (g.status === 'in_progress' ? '<span class="sub">Live</span>' : g.status === 'final' ? '<span class="sub">Checking</span>' : '');
    } else if (kind === 'passed') {
      const sig = (p.signals || []).join(', ');
      l1 = esc(away(g));
      l2 = p.lean_name ? 'Leans ' + esc(p.lean_name) + (p.lean_side ? ' (' + p.lean_side + ')' : '') + (sig ? ', ' + esc(sig) : '') : esc(p.reason || 'No edge');
      const edge = p.edge != null && p.lean_name ? '<span class="big q">' + (p.edge >= 0 ? '+' : '\u2212') + Math.abs(p.edge * 100).toFixed(1) + '%</span>' : '';
      const tail = g.status === 'final' && g.home_score != null ? Math.round(g.away_score) + dash + Math.round(g.home_score) : g.status === 'in_progress' ? 'Live' : edge ? 'edge' : '';
      out = edge + (tail ? '<span class="sub">' + tail + '</span>' : '');
    } else if (kind === 'waiting') {
      const m = mins(g.publish_at_utc);
      l1 = esc(away(g)); l2 = 'Analysis posts ' + esc(clock(g.publish_at_utc)) + (m > 0 ? ', in ' + (m >= 60 ? Math.floor(m / 60) + ' h ' + (m % 60) + ' min' : m + ' min') : ', due now');
    } else {
      l1 = esc(away(g));
      l2 = (g.missed ? 'Posting window missed, so it is not recorded' : ['cancelled', 'postponed'].includes(g.status) ? g.status[0].toUpperCase() + g.status.slice(1) : 'Not analysed');
      if (g.status === 'final' && g.home_score != null) out = '<span class="sub">' + Math.round(g.away_score) + dash + Math.round(g.home_score) + '</span>';
    }
    const inner = '<span class="when">' + esc(clock(g.start_utc)) + '<small>' + esc(SPORTS[g.sport]) + '</small></span><span class="what"><span class="l1">' + l1 + '</span><span class="l2">' + l2 + '</span></span><span class="out">' + out + '</span>';
    if (!p) return '<div class="row"><div class="row-btn">' + inner + '</div></div>';
    return '<div class="row"><button type="button" class="row-btn" data-id="' + esc(g.id) + '" aria-expanded="' + open + '">' + inner + '</button>' +
      '<div class="panel" data-open="' + open + '"><div><div class="detail">' + detail(g) + '</div></div></div></div>';
  }

  function renderList(games) {
    const el = $('#list'); el.setAttribute('aria-busy', String(state.loading));
    if (games == null) {
      el.innerHTML = state.error ? '<p class="empty">' + esc(state.error) + '<button class="retry" id="retry">Try again</button></p>' : '<div class="sk"></div>'.repeat(5);
      return;
    }
    const f = games.filter((g) => state.filter === 'all' || g.sport === state.filter).sort((a, b) => (a.start_utc < b.start_utc ? -1 : a.start_utc > b.start_utc ? 1 : a.id < b.id ? -1 : 1));
    const plays = f.filter((g) => g.pick && g.pick.verdict === 'PLAY').sort((a, b) => (b.pick.top_pick - a.pick.top_pick) || (a.start_utc < b.start_utc ? -1 : 1));
    const allPassed = f.filter((g) => g.pick && g.pick.verdict !== 'PLAY');
    const bare = allPassed.filter((g) => g.pick.model_prob == null);
    const passed = allPassed.filter((g) => g.pick.model_prob != null).sort((a, b) => ((b.pick.edge == null ? -9 : b.pick.edge) - (a.pick.edge == null ? -9 : a.pick.edge)) || (a.start_utc < b.start_utc ? -1 : 1));
    const waiting = f.filter((g) => !g.pick && !g.missed && g.status === 'scheduled');
    const other = f.filter((g) => !g.pick && !(!g.missed && g.status === 'scheduled'));
    const group = (title, list, kind, cls, note) => (list.length ? '<section class="group ' + cls + '"><h2>' + title + ' ' + list.length + (note ? '<span class="note">' + note + '</span>' : '') + '</h2>' + list.map((g) => row(g, kind)).join('') + '</section>' : '');
    el.innerHTML = '<div class="' + (state.animate ? 'enter' : '') + '">' + group('Plays', plays, 'plays', 'plays') + group('Passed', passed, 'passed', 'quiet', 'largest edge first') + (bare.length ? '<details class="group quiet bare"><summary>' + bare.length + (bare.length === 1 ? ' game' : ' games') + ' without odds or enough data</summary>' + bare.map((g) => row(g, 'passed')).join('') + '</details>' : '') +
      group('Waiting for analysis', waiting, 'waiting', 'quiet') + group('Not analysed', other, 'other', 'quiet') + '</div>';
    if (!f.length) el.innerHTML = '';
  }

  function backtestText(b) {
    const rows = Object.entries(b || {}).filter(([, v]) => v.games);
    if (!rows.length) return 'Not run yet. Run the backfill task.';
    return rows.map(([k, v]) => SPORTS[k] + ' ' + (v.accuracy * 100).toFixed(1) + '% of ' + v.games + ' winners, log loss ' + v.log_loss + ' vs ' + v.baseline_log_loss + ' naive').join('; ');
  }

  function staleNote() {
    const d = state.latest;
    if (!d || d.source !== 'live' || !d.health || !d.health.last_tick_utc) return '';
    const gap = (now() - Date.parse(d.health.last_tick_utc)) / 60000;
    if (gap <= 30) return '';
    return 'New picks are delayed: the updater last ran ' + (gap >= 120 ? Math.round(gap / 60) + ' hours' : Math.round(gap) + ' minutes') + ' ago.';
  }

  const TAG = { ok: 'Working', warn: 'Check', bad: 'Failing', off: 'Not set up', idle: 'Waiting', info: '' };
  function renderStatus() {
    const el = $('#status'); el.hidden = !state.statusOpen;
    if (!state.statusOpen) return;
    const d = state.latest || {}; const h = d.health || {}; const api = state.health;
    const items = (h.integrations && h.integrations.items) || [];
    const groups = ['Updates', 'Odds', 'AI text', 'Data', 'System'];
    const row = (i) => '<div class="st-row"><span class="dot ' + i.state + '"></span><div><b>' + esc(i.name) + '</b>' + (TAG[i.state] ? ' <span class="tag ' + i.state + '">' + TAG[i.state] + '</span>' : '') + '<span class="st-detail">' + esc(i.detail) + '</span></div></div>';
    let html = '<h2>Status</h2>';
    if (!items.length) html += '<p class="empty">' + (state.loadError ? esc(state.loadError) : 'No status has been written yet. It appears after the first updater run.') + '</p>';
    html += groups.map((g) => { const rows = items.filter((i) => i.group === g); return rows.length ? '<section class="st-group"><h3>' + g + '</h3>' + rows.map(row).join('') + '</section>' : ''; }).join('');
    const site = [{ name: 'Website version', state: 'info', detail: SITE_VERSION + (h.integrations && h.integrations.version && h.integrations.version !== SITE_VERSION ? ', but the updater is on ' + h.integrations.version + '. One of them has not been upgraded.' : '.') },
      { name: 'Deployed commit', state: api ? (api.ok ? 'info' : 'bad') : 'idle', detail: api ? (api.commit || 'unknown').slice(0, 7) + (api.ok ? '' : ', database error: ' + (api.error || '')) : 'Checking.' }];
    html += '<section class="st-group"><h3>Website</h3>' + site.map(row).join('') + '</section>';
    el.innerHTML = html;
  }

  function render() {
    const all = dayGames();
    const games = (all || []).filter((g) => state.filter === 'all' || g.sport === state.filter);
    renderNav(); renderSummary(all, games); renderTabs(all); renderList(all);
    const b = $('#banner'); const msg = [state.banner, state.latest && state.latest.demo_note, staleNote()].filter(Boolean).join(' '); b.hidden = !msg; b.textContent = msg;
    renderStatus(); state.animate = false;
  }

  /* ---------- actions ---------- */
  function writeHash() {
    const p = [];
    if (state.date !== today()) p.push('d=' + state.date);
    if (state.filter !== 'all') p.push('s=' + state.filter);
    history.replaceState(null, '', p.length ? '#' + p.join('&') : location.pathname + location.search);
  }
  async function setDate(k) {
    if (!validKey(k) || k === state.date) return;
    state.date = k; state.animate = true; state.error = ''; writeHash(); render();
    await loadDay(k, false); state.animate = true; render();
  }
  function setFilter(k) { state.filter = k; state.animate = true; try { localStorage.setItem('picks.filter', k); } catch (e) { /* storage may be blocked */ } writeHash(); render(); }
  function readHash() {
    const h = location.hash.replace('#', ''); const out = {};
    if (SPORTS[h]) out.s = h; else new URLSearchParams(h).forEach((v, k) => { out[k] = v; });
    return out;
  }

  async function init() {
    const h = readHash(); let saved = null; try { saved = localStorage.getItem('picks.filter'); } catch (e) { /* ignore */ }
    state.filter = SPORTS[h.s] ? h.s : SPORTS[saved] ? saved : 'all';
    state.date = validKey(h.d) ? h.d : today();
    render();
    await loadLatest();
    if (!validKey(h.d)) state.date = today();
    await loadDay(state.date, true);
    state.animate = true; render();

    $('#prev').addEventListener('click', () => setDate(addDays(state.date, -1)));
    $('#next').addEventListener('click', () => setDate(addDays(state.date, 1)));
    $('#todayBtn').addEventListener('click', () => setDate(today()));
    $('#dateInput').addEventListener('change', (e) => setDate(e.target.value));
    $('#statusBtn').addEventListener('click', async () => {
      state.statusOpen = !state.statusOpen; $('#statusBtn').setAttribute('aria-expanded', String(state.statusOpen)); renderStatus();
      if (state.statusOpen && !state.demo) { try { state.health = await fetchJson('/api/health'); } catch (e) { state.health = { ok: false, commit: null }; } renderStatus(); }
    });
    document.addEventListener('click', (e) => {
      const tab = e.target.closest('.tab'); if (tab) return setFilter(tab.dataset.sport);
      if (e.target.closest('#retry')) { state.error = ''; state.loading = true; render(); loadDay(state.date, true).then(render); return; }
      const btn = e.target.closest('.row-btn[data-id]'); if (!btn) return;
      const id = btn.dataset.id; const panel = btn.nextElementSibling; const open = !state.open.has(id);
      open ? state.open.add(id) : state.open.delete(id);
      btn.setAttribute('aria-expanded', String(open)); panel.dataset.open = String(open);
    });
    window.addEventListener('hashchange', () => { const x = readHash(); if (validKey(x.d)) setDate(x.d); else if (!x.d && state.date !== today()) setDate(today()); if (x.s && SPORTS[x.s] && x.s !== state.filter) setFilter(x.s); });
    const refresh = async () => { if (document.hidden) return; await loadLatest(); if (state.date > addDays(today(), -1) && state.date !== today()) await loadDay(state.date, true); render(); };
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    setInterval(refresh, 60000);
    setInterval(() => { if (!document.hidden) render(); }, 30000);
  }
  init();
})();
