(function () {
  'use strict';
  const SPORTS = [['all', 'All'], ['mlb', 'MLB'], ['nfl', 'NFL'], ['nba', 'NBA'], ['nhl', 'NHL'], ['ufc', 'UFC'], ['dwcs', 'DWCS']];
  const LABEL = Object.fromEntries(SPORTS);
  const POLL_MS = 60000;
  const params = new URLSearchParams(location.search);
  const localHost = ['localhost', '127.0.0.1', ''].includes(location.hostname);
  const state = { data: null, filter: 'all', open: new Set(), offset: 0, banner: '', health: null, statusOpen: false, fetchedAt: 0 };

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const now = () => Date.now() + state.offset;
  const odds = (n) => (n == null ? '' : n > 0 ? '+' + Math.round(n) : '\u2212' + Math.abs(Math.round(n)));
  const pct = (x, d = 1) => (x == null ? '' : (x * 100).toFixed(d) + '%');
  const units = (u) => (u > 0 ? '+' : u < 0 ? '\u2212' : '') + Math.abs(u).toFixed(2) + 'u';
  const tz = () => (state.data && state.data.timezone) || 'America/New_York';
  const fmt = (iso, opts, zone) => new Intl.DateTimeFormat(undefined, Object.assign({ timeZone: zone }, opts)).format(new Date(iso));
  const hm = { hour: 'numeric', minute: '2-digit' };
  const localTime = (iso) => fmt(iso, hm);
  const etTime = (iso) => fmt(iso, hm, tz());
  const etKey = (iso) => new Intl.DateTimeFormat('en-CA', { timeZone: tz(), year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso));
  const mins = (iso) => Math.round((Date.parse(iso) - now()) / 60000);
  const blank = () => ({ w: 0, l: 0, v: 0, pending: 0, win_pct: null, units: 0, roi: null });
  const wlv = (b) => b.w + '\u2013' + b.l + '\u2013' + b.v;

  function sameZone() { return localTime('2026-01-15T17:00:00Z') === etTime('2026-01-15T17:00:00Z'); }
  function timeCell(iso) {
    return '<span class="time">' + esc(localTime(iso)) + (sameZone() ? '' : '<small>' + esc(etTime(iso)) + ' ET</small>') + '</span>';
  }

  function matches(g) { return state.filter === 'all' || g.sport === state.filter; }

  function todayFromGames(games) {
    const key = etKey(new Date(now()).toISOString());
    const b = blank();
    games.forEach((g) => {
      if (!g.pick || g.pick.verdict !== 'PLAY' || etKey(g.start_utc) !== key) return;
      if (g.grade && ['W', 'L', 'V'].includes(g.grade.grade)) { b[g.grade.grade.toLowerCase()] += 1; b.units += g.grade.profit_units || 0; } else b.pending += 1;
    });
    return b;
  }

  function renderLedger() {
    const d = state.data; if (!d || !d.records) { $('#ledger').innerHTML = ''; return; }
    const r = d.records;
    const all = state.filter === 'all';
    const today = all ? r.today : todayFromGames(d.games.filter(matches));
    const overall = all ? r.overall : (r.by_sport && r.by_sport[state.filter]) || blank();
    const meta = (b, extra) => '<span class="meta">' + (b.win_pct == null ? 'No decided picks yet' : '<b>' + b.win_pct + '%</b> wins') +
      (b.units ? ', <b class="' + (b.units >= 0 ? 'pos' : 'neg') + '">' + units(b.units) + '</b>' : '') +
      (b.roi != null ? ', ROI ' + b.roi + '%' : '') + (b.pending ? ', ' + b.pending + ' pending' : '') + (extra || '') + '</span>';
    const strip = (r.history || []).map((h) => {
      const cls = h.w > h.l ? 'w' : h.l > h.w ? 'l' : (h.w + h.l + h.v) ? 'v' : '';
      const total = h.w + h.l + h.v + h.pending;
      return '<i class="' + cls + '" style="height:' + (18 + Math.min(total, 5) * 16) + '%" title="' + esc(h.date + ': ' + h.w + '-' + h.l + '-' + h.v) + '"></i>';
    }).join('');
    $('#ledger').innerHTML =
      '<div class="rec"><span class="lbl">Today' + (all ? '' : ', ' + LABEL[state.filter]) + '</span><span class="num">' + wlv(today) + '</span>' + meta(today) + '</div>' +
      '<div class="rec"><span class="lbl">Since launch' + (all ? '' : ', ' + LABEL[state.filter]) + '</span><span class="num">' + wlv(overall) + '</span>' +
      meta(overall, all && r.streak ? ', streak <b>' + esc(r.streak) + '</b>' : '') + '</div>' +
      '<div class="strip" role="img" aria-label="Daily results for the last 30 days, all sports">' + strip + '</div>' +
      '<p class="strip-note">Last 30 days, all sports. Green: more wins, red: more losses, amber: even or voids.</p>';
  }

  function renderChips() {
    $('#chips').innerHTML = SPORTS.map(([k, l]) => '<button class="chip" data-sport="' + k + '" aria-pressed="' + (state.filter === k) + '">' + l + '</button>').join('');
  }

  function resultPill(g) {
    if (g.grade) {
      const x = g.grade.grade;
      if (x === 'W' || x === 'L' || x === 'V') return '<span class="pill ' + x.toLowerCase() + '">' + x + '</span><small>' + (x === 'V' ? 'void' : units(g.grade.profit_units || 0)) + '</small>';
      return '<span class="pill late">Checking</span>';
    }
    return '';
  }

  function slip(g) {
    const p = g.pick;
    const cls = g.grade ? (g.grade.grade === 'W' ? ' done-w' : g.grade.grade === 'L' ? ' done-l' : '') : '';
    return '<article class="slip' + cls + '"><div class="main"><span class="vs">' + esc(LABEL[g.sport]) + ', ' + esc(g.kind === 'bout' ? g.home + ' vs ' + g.away : g.away + ' at ' + g.home) + '</span>' +
      '<h3>' + esc(p.selection_name) + ' moneyline ' + odds(p.odds) + '</h3>' +
      '<div class="nums"><span>Edge <b>' + pct(p.edge) + '</b></span><span>Fair <b>' + odds(p.fair_odds) + '</b></span><span>Confidence <b>' + p.confidence + '/10</b></span></div>' +
      '<div class="nums"><span>' + esc(localTime(g.start_utc)) + '</span>' + (g.grade ? '<span class="right">' + resultPill(g) + '</span>' : '') + '</div></div>' +
      '<div class="stub"><span class="units">' + p.units + 'u</span><small>stake</small></div></article>';
  }

  function renderTop() {
    const d = state.data; const el = $('#top');
    if (!d) { el.innerHTML = ''; return; }
    const tops = d.games.filter((g) => g.pick && g.pick.top_pick && matches(g))
      .sort((a, b) => (!!a.grade - !!b.grade) || (a.start_utc < b.start_utc ? -1 : 1)).slice(0, 6);
    el.innerHTML = '<h2 id="topH">Top picks</h2>' + (tops.length
      ? '<p class="hint">The strongest plays, marked when posted. Up to five a day.</p><div class="slips">' + tops.map(slip).join('') + '</div>'
      : '<p class="empty">No top picks right now. Plays only appear when the edge, the data coverage and the price all clear the bar.</p>');
  }

  function dayLabel(key) {
    const todayKey = etKey(new Date(now()).toISOString());
    const tomorrowKey = etKey(new Date(now() + 86400000).toISOString());
    if (key === todayKey) return 'Today';
    if (key === tomorrowKey) return 'Tomorrow';
    return new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', weekday: 'long', month: 'short', day: 'numeric' }).format(new Date(key + 'T12:00:00Z'));
  }

  function rightCell(g) {
    const p = g.pick;
    if (g.grade && p) return resultPill(g);
    if (p) {
      const live = g.status === 'in_progress' ? '<span class="pill live">Live</span>' : '';
      if (p.verdict === 'PLAY') return live || '<span class="pill play">PLAY</span>' + (p.tag === 'LATE' ? '<small>posted late</small>' : '') ;
      return live || '<span class="pill pass">PASS</span>';
    }
    if (g.missed) return '<span class="pill late">No pick</span><small>window missed</small>';
    if (['cancelled', 'postponed'].includes(g.status)) return '<span class="pill v">' + esc(g.status) + '</span>';
    if (g.status === 'final' || g.status === 'in_progress') return '<span class="pill pass">No pick</span>';
    const m = mins(g.publish_at_utc);
    return '<span class="pill">Posts ' + esc(localTime(g.publish_at_utc)) + '</span><small>' + (m > 0 ? 'in ' + (m >= 60 ? Math.floor(m / 60) + ' h ' + (m % 60) + ' min' : m + ' min') : 'due now') + '</small>';
  }

  function detail(g) {
    const p = g.pick;
    if (!p) {
      const when = esc(localTime(g.publish_at_utc));
      return g.missed ? '<p>The posting window passed before an analysis could be locked, so no pick exists for this game. It is excluded from every record.</p>'
        : '<p>Analysis posts at ' + when + (sameZone() ? '' : ' (' + esc(etTime(g.publish_at_utc)) + ' ET)') + '. Picks are locked when posted and never edited.</p>';
    }
    const n = p.narrative || {};
    const lowCov = p.coverage < 0.8;
    const rows = [['Market', n.market], ['Matchup', n.matchup], ['Context', n.context], ['Projection', n.projection], ['Risk', n.risk]]
      .filter((r) => r[1]).map((r) => '<dt>' + r[0] + '</dt><dd>' + esc(r[1]) + '</dd>').join('');
    const inputs = Object.entries(p.inputs || {}).map(([k, v]) => esc(k.replace('_', ' ')) + (v.available ? ' (' + esc(v.source) + ')' : ' (unavailable)')).join(', ');
    const grade = g.grade && g.grade.grade !== 'PENDING_REVIEW' ? '<p><b>Result: ' + g.grade.grade + '</b>, ' + esc(g.grade.reason || '') +
      (g.grade.closing_odds != null ? '. Closing ' + odds(g.grade.closing_odds) + (g.grade.clv != null ? ', closing-line value ' + (g.grade.clv * 100).toFixed(1) + '%' : '') : '') + '.</p>' : '';
    return '<p><b>' + esc(p.headline) + '</b></p>' + grade +
      '<ul>' + (n.thesis || []).map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul><dl>' + rows + '</dl>' +
      '<p class="fine"><span class="cov' + (lowCov ? ' low' : '') + '">Data coverage ' + Math.round(p.coverage * 100) + '%</span>' +
      (p.unavailable && p.unavailable.length ? 'Unavailable: ' + esc(p.unavailable.join(', ')) + '. ' : '') + '</p>' +
      '<p class="fine">Inputs: ' + inputs + '. Posted ' + esc(localTime(p.published_utc)) + (p.tag === 'LATE' ? ' (late)' : '') + ', locked as ' + esc(p.hash) + ', text by ' + esc(p.narrative_source) + '.</p>';
  }

  function row(g) {
    const open = state.open.has(g.id);
    const p = g.pick;
    const scoreLine = g.home_score != null && g.away_score != null ? ' <span class="pickline">' + Math.round(g.away_score) + '\u2013' + Math.round(g.home_score) + ' (away\u2013home)</span>' : '';
    const pickline = p && p.verdict === 'PLAY' ? esc(p.selection_name) + ' ' + odds(p.odds) + ', ' + p.units + 'u' : p ? 'No bet' : '';
    return '<div class="row"><button type="button" data-id="' + esc(g.id) + '" aria-expanded="' + open + '">' + timeCell(g.start_utc) +
      '<span class="teams"><span class="sport">' + esc(LABEL[g.sport]) + '</span>' + esc(g.kind === 'bout' ? g.home + ' vs ' + g.away : g.away + ' at ' + g.home) +
      '<span class="pickline">' + pickline + '</span>' + (g.status === 'final' ? scoreLine : '') + '</span><span class="right">' + rightCell(g) + '</span></button>' +
      '<div class="detail"' + (open ? '' : ' hidden') + '>' + detail(g) + '</div></div>';
  }

  function renderSlate() {
    const d = state.data; const el = $('#slate');
    if (!d) { el.innerHTML = ''; return; }
    const games = d.games.filter(matches);
    const firstStart = {};
    games.forEach((g) => { if (g.kind === 'bout') firstStart[g.event_name] = !firstStart[g.event_name] || g.start_utc < firstStart[g.event_name] ? g.start_utc : firstStart[g.event_name]; });
    const key = (g) => (g.kind === 'bout' ? firstStart[g.event_name] : g.start_utc) + '|' + g.start_utc + '|' + g.id;
    games.sort((a, b) => (key(a) < key(b) ? -1 : 1));
    let html = '<h2 id="slateH">Slate</h2>';
    if (!games.length) html += '<p class="empty">' + (d.empty ? 'Nothing has been published yet.' : 'No games in this window' + (state.filter === 'all' ? '' : ' for ' + LABEL[state.filter]) + '. Leagues in their off-season simply have nothing to show.') + '</p>';
    let day = '', ev = '';
    games.forEach((g) => {
      const k = etKey(g.kind === 'bout' ? firstStart[g.event_name] : g.start_utc);
      if (k !== day) { day = k; ev = ''; html += '<div class="day">' + esc(dayLabel(k)) + '</div>'; }
      if (g.kind === 'bout' && g.event_name !== ev) { ev = g.event_name; html += '<div class="hint"><b>' + esc(ev) + '</b>, card posts ' + esc(localTime(g.publish_at_utc)) + '</div>'; }
      html += row(g);
    });
    el.innerHTML = html;
  }

  function renderBanner() {
    const d = state.data; const msgs = [];
    if (state.banner) msgs.push(state.banner);
    if (d && d.demo_note) msgs.push(d.demo_note);
    if (d && d.source === 'live' && d.generated_utc) {
      const age = (now() - Date.parse(d.generated_utc)) / 60000;
      const overdue = d.games.some((g) => !g.pick && !g.missed && g.status === 'scheduled' && mins(g.publish_at_utc) < -5 && mins(g.start_utc) > 0);
      if (age > 15 && overdue) msgs.push('Data may be delayed: the last update was ' + Math.round(age) + ' minutes ago.');
    }
    if (d && d.empty) msgs.push('The database is connected but nothing has been published yet.');
    const el = $('#banner'); el.hidden = !msgs.length; el.textContent = msgs.join(' ');
  }

  function renderStatus() {
    const el = $('#status'); el.hidden = !state.statusOpen;
    if (!state.statusOpen) return;
    const d = state.data || {}; const h = d.health || {}; const api = state.health;
    const src = Object.entries(h.sources || {});
    const bad = src.filter(([, v]) => !v.ok);
    const row = (a, b) => '<tr><td>' + a + '</td><td>' + b + '</td></tr>';
    const t = (iso) => (iso ? esc(localTime(iso)) + ' (' + Math.max(0, Math.round((now() - Date.parse(iso)) / 60000)) + ' min ago)' : 'never');
    el.innerHTML = '<h2>Status</h2><table>' +
      row('Data source', esc(d.source || 'none')) + row('Last update', t(d.generated_utc)) + row('Last tick', t(h.last_tick_utc)) + row('Last pick posted', t(h.last_publish_utc)) +
      row('Data feeds', src.length ? (bad.length ? '<span class="bad">' + bad.length + ' failing</span>: ' + esc(bad.map(([k, v]) => k + ' (' + v.detail + ')').join('; ')) : '<span class="ok">all ' + src.length + ' ok</span>') : 'none yet') +
      row('Free LLM budget today', Object.keys(h.quota || {}).length ? esc(Object.entries(h.quota).map(([k, v]) => k.split(':')[1] + ' ' + v.used + '/' + v.cap).join(', ')) : 'not used (template text)') +
      row('Ledger check', h.ledger && h.ledger.ok === true ? '<span class="ok">clean</span>' : h.ledger && h.ledger.ok === false ? '<span class="bad">problems: ' + esc((h.ledger.problems || []).join('; ')) + '</span>' : 'not run yet') +
      row('Deployed commit', api ? esc((api.commit || 'unknown').slice(0, 7)) + (api.ok ? '' : ' <span class="bad">(database error)</span>') : 'checking') +
      row('Model', h.experimental ? 'Experimental baseline, not backtested' : 'n/a') + '</table>';
  }

  function renderAll() { renderBanner(); renderLedger(); renderChips(); renderTop(); renderSlate(); renderStatus(); }

  async function fetchJson(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  async function load() {
    let data = null;
    if (!params.has('demo')) {
      try { data = await fetchJson('/api/latest'); state.banner = ''; } catch (e) { state.banner = state.data ? 'Offline or delayed: showing the last data received.' : ''; }
    }
    if (!data && !state.data && (params.has('demo') || localHost)) {
      try { data = await fetchJson('demo/latest.json'); state.banner = ''; } catch (e) { /* fall through */ }
    }
    if (!data && !state.data) state.banner = 'Could not load picks. Retrying every minute.';
    if (data) {
      state.data = data;
      state.offset = data.source === 'demo' ? Date.parse(data.generated_utc) - Date.now() : 0;
      state.fetchedAt = Date.now();
    }
    renderAll();
  }

  function setFilter(k) {
    state.filter = k;
    try { localStorage.setItem('picks.filter', k); } catch (e) { /* storage can be unavailable */ }
    history.replaceState(null, '', k === 'all' ? location.pathname + location.search : '#' + k);
    renderAll();
  }

  function init() {
    const fromHash = location.hash.replace('#', '');
    let saved = null; try { saved = localStorage.getItem('picks.filter'); } catch (e) { /* ignore */ }
    state.filter = LABEL[fromHash] ? fromHash : LABEL[saved] ? saved : 'all';
    document.addEventListener('click', (e) => {
      const chip = e.target.closest('.chip'); if (chip) return setFilter(chip.dataset.sport);
      const rowBtn = e.target.closest('.row > button');
      if (rowBtn) { const id = rowBtn.dataset.id; state.open.has(id) ? state.open.delete(id) : state.open.add(id); renderSlate(); const again = document.querySelector('.row > button[data-id="' + CSS.escape(id) + '"]'); if (again) again.focus({ preventScroll: true }); }
    });
    $('#statusBtn').addEventListener('click', async () => {
      state.statusOpen = !state.statusOpen; $('#statusBtn').setAttribute('aria-expanded', String(state.statusOpen)); renderStatus();
      if (state.statusOpen && state.data && state.data.source !== 'demo') { try { state.health = await fetchJson('/api/health'); } catch (e) { state.health = { ok: false, commit: null }; } renderStatus(); }
    });
    window.addEventListener('hashchange', () => { const k = location.hash.replace('#', ''); if (LABEL[k] && k !== state.filter) { state.filter = k; renderAll(); } });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
    setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    setInterval(() => { if (!document.hidden && state.data) { renderSlate(); renderBanner(); } }, 30000);
    renderChips();
    load();
  }

  init();
})();
