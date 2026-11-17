import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const day = require('../../api/day.js');
const shape = require('../../api/_lib/shape.js');

function res() {
  const r = { headers: {}, code: 0, body: undefined };
  r.setHeader = (k, v) => { r.headers[k.toLowerCase()] = v; };
  r.status = (c) => { r.code = c; return r; };
  r.send = (b) => { r.body = b; return r; };
  r.json = (b) => { r.body = JSON.stringify(b); return r; };
  return r;
}

const base = { id: 'g1', sport: 'nba', kind: 'team', event_id: 'g1', event_name: 'x', start_utc: '2026-11-15T23:30:00Z', home: 'Harbor City Anglers',
  away: 'Lakeview Herons', venue: 'v', status: 'final', home_score: 101, away_score: 96, winner: 'home', missed: 0, verdict: 'PLAY', tag: 'ON_TIME',
  market: 'ML', selection: 'home', odds: -110, fair_odds: -124, model_prob: 0.55, market_prob: 0.5, edge: 0.05, units: 2, confidence: 6, top_pick: 1,
  coverage: 1, published_utc: '2026-11-15T22:55:00Z', hash: 'abcdef0123456789',
  payload_json: JSON.stringify({ headline: 'PLAY: Harbor City Anglers moneyline -110', home: 'Harbor City Anglers', away: 'Lakeview Herons', narrative: { thesis: [] }, reason: null, unavailable: [], inputs: {}, narrative_source: 'template' }),
  grade: 'W', grade_reason: 'home won', profit_units: 1.82, closing_odds: -110, clv: 0 };

function mock(rows) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push(JSON.parse(init.body));
    const cols = Object.keys(rows[0] || { x: 1 }).map((name) => ({ name }));
    const cell = (v) => (v === null || v === undefined ? { type: 'null' } : typeof v === 'number' ? (Number.isInteger(v) ? { type: 'integer', value: String(v) } : { type: 'float', value: v }) : { type: 'text', value: String(v) });
    return { ok: true, status: 200, json: async () => ({ results: [{ type: 'ok', response: { type: 'execute', result: { cols, rows: rows.map((r) => Object.keys(rows[0]).map((k) => cell(r[k]))) } } }, { type: 'ok', response: { type: 'close' } }] }) };
  };
  return calls;
}

test.beforeEach(() => { process.env.TURSO_URL = 'libsql://x.turso.io'; process.env.TURSO_READ_TOKEN = 't'; });

test('New York day bounds handle standard and daylight time', () => {
  assert.deepEqual(shape.etBounds('2026-11-15'), ['2026-11-15T05:00:00Z', '2026-11-16T05:00:00Z']);
  assert.deepEqual(shape.etBounds('2026-07-04'), ['2026-07-04T04:00:00Z', '2026-07-05T04:00:00Z']);
  assert.deepEqual(shape.etBounds('2026-11-01'), ['2026-11-01T04:00:00Z', '2026-11-02T05:00:00Z']);   // 25-hour day
});

test('date validation', () => {
  assert.ok(shape.validDate('2026-02-28'));
  assert.ok(!shape.validDate('2026-02-30') && !shape.validDate('x') && !shape.validDate("2026-11-15'; DROP"));
});

test('day returns shaped games with the pick and result', async () => {
  const calls = mock([base]);
  const r = res();
  await day({ method: 'GET', query: { date: shape.todayKey() } }, r);
  const out = JSON.parse(r.body);
  assert.equal(r.code, 200);
  assert.equal(out.games[0].pick.selection_name, 'Harbor City Anglers');
  assert.equal(out.games[0].pick.top_pick, true);
  assert.equal(out.games[0].pick.hash, 'abcdef012345');
  assert.deepEqual(out.games[0].grade, { grade: 'W', reason: 'home won', profit_units: 1.82, closing_odds: -110, clv: 0 });
  assert.equal(out.games[0].publish_at_utc, '2026-11-15T23:00:00Z');
  assert.equal(calls[0].requests[0].stmt.args.length, 2);
  assert.match(r.headers['cache-control'], /s-maxage=20/);
});

test('old days are cached for an hour; bad or far dates are rejected', async () => {
  mock([base]);
  let r = res();
  await day({ method: 'GET', query: { date: shape.addDays(shape.todayKey(), -10) } }, r);
  assert.match(r.headers['cache-control'], /s-maxage=3600/);
  for (const date of ['nope', '2026-13-01', shape.addDays(shape.todayKey(), 90), '1999-01-01']) {
    r = res();
    await day({ method: 'GET', query: { date } }, r);
    assert.equal(r.code, 400);
  }
});

test('games without a pick come back with null pick and grade', () => {
  const [g] = shape.shapeRows([{ ...base, verdict: null, grade: null, payload_json: null, hash: null }]);
  assert.equal(g.pick, null);
  assert.equal(g.grade, null);
});
