// Turns joined database rows into the same game objects the pipeline writes into the "latest" snapshot.

const TZ = process.env.PICKS_TZ || 'America/New_York';

function localParts(ms, tz) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) };
}

function startOfDay(dateStr, tz = TZ) {
  const [y, m, d] = dateStr.split('-').map(Number);
  for (let h = 0; h <= 14; h += 1) {
    const ms = Date.UTC(y, m - 1, d, h, 0, 0);
    const p = localParts(ms, tz);
    if (p.date === dateStr && p.hour === 0) return ms;
  }
  throw new Error('cannot resolve ' + dateStr);
}

function addDays(dateStr, n) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

function etBounds(dateStr, tz = TZ) {
  return [new Date(startOfDay(dateStr, tz)).toISOString().replace('.000Z', 'Z'),
    new Date(startOfDay(addDays(dateStr, 1), tz)).toISOString().replace('.000Z', 'Z')];
}

function todayKey(now = Date.now(), tz = TZ) { return localParts(now, tz).date; }

function validDate(s) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(s + 'T00:00:00Z');
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

const SELECT = 'SELECT g.id, g.sport, g.kind, g.event_id, g.event_name, g.start_utc, g.home, g.away, g.venue, g.status, ' +
  'g.home_score, g.away_score, g.winner, g.missed, p.verdict, p.tag, p.market, p.selection, p.odds, p.fair_odds, ' +
  'p.model_prob, p.market_prob, p.edge, p.units, p.confidence, p.top_pick, p.coverage, p.published_utc, p.payload_json, ' +
  'p.hash, gr.grade, gr.reason AS grade_reason, gr.profit_units, gr.closing_odds, gr.clv ' +
  'FROM games g LEFT JOIN picks p ON p.game_id = g.id LEFT JOIN grades gr ON gr.pick_id = p.id ' +
  'WHERE g.start_utc >= ? AND g.start_utc < ? ORDER BY g.start_utc, g.id';

function shapeRows(rows) {
  const first = {};
  rows.forEach((r) => { if (r.kind === 'bout') first[r.event_id] = !first[r.event_id] || r.start_utc < first[r.event_id] ? r.start_utc : first[r.event_id]; });
  return rows.map((r) => {
    const anchor = r.kind === 'bout' ? first[r.event_id] : r.start_utc;
    const lead = (r.kind === 'bout' ? 90 : 30) * 60000;
    const game = {
      id: r.id, sport: r.sport, kind: r.kind, event_name: r.event_name, start_utc: r.start_utc, home: r.home, away: r.away,
      venue: r.venue, status: r.status, home_score: r.home_score, away_score: r.away_score, winner: r.winner,
      publish_at_utc: new Date(Date.parse(anchor) - lead).toISOString().replace('.000Z', 'Z'), pick: null, grade: null, missed: !!r.missed,
    };
    if (r.verdict) {
      const payload = JSON.parse(r.payload_json);
      game.pick = {
        verdict: r.verdict, tag: r.tag, headline: payload.headline, market: r.market, selection: r.selection,
        selection_name: r.selection === 'home' ? payload.home : r.selection === 'away' ? payload.away : null,
        odds: r.odds, fair_odds: r.fair_odds, model_prob: r.model_prob, market_prob: r.market_prob, edge: r.edge,
        units: r.units, confidence: r.confidence, top_pick: !!r.top_pick, coverage: r.coverage,
        published_utc: r.published_utc, narrative: payload.narrative, reason: payload.reason,
        unavailable: payload.unavailable, inputs: payload.inputs, narrative_source: payload.narrative_source, lean_name: payload.lean_name || null, signals: payload.signals || [], lean_side: payload.lean_side || null,
        hash: String(r.hash).slice(0, 12),
      };
      if (r.grade) game.grade = { grade: r.grade, reason: r.grade_reason, profit_units: r.profit_units, closing_odds: r.closing_odds, clv: r.clv };
    }
    return game;
  });
}

module.exports = { etBounds, todayKey, addDays, validDate, shapeRows, SELECT, TZ };
