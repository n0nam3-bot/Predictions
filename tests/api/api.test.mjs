import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const db = require('../../api/_lib/db.js');
const latest = require('../../api/latest.js');
const health = require('../../api/health.js');
const game = require('../../api/game.js');
const record = require('../../api/record.js');

function res() {
  const r = { headers: {}, code: 0, body: undefined };
  r.setHeader = (k, v) => { r.headers[k.toLowerCase()] = v; };
  r.status = (c) => { r.code = c; return r; };
  r.send = (b) => { r.body = b; return r; };
  r.json = (b) => { r.body = JSON.stringify(b); return r; };
  return r;
}

function mockTurso(rowsByCall) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(init.body);
    calls.push({ url, auth: init.headers.Authorization, body });
    const rows = rowsByCall.shift();
    if (rows instanceof Error) throw rows;
    if (rows === 'http500') return { ok: false, status: 500, json: async () => ({}) };
    const cols = rows.length ? Object.keys(rows[0]).map((name) => ({ name })) : [];
    const cell = (v) => (v === null ? { type: 'null' } : typeof v === 'number' ? { type: 'integer', value: String(v) } : { type: 'text', value: v });
    return { ok: true, status: 200, json: async () => ({ results: [{ type: 'ok', response: { type: 'execute', result: { cols, rows: rows.map((r) => Object.values(r).map(cell)) } } }, { type: 'ok', response: { type: 'close' } }] }) };
  };
  return calls;
}

test.beforeEach(() => {
  process.env.TURSO_URL = 'libsql://demo-org.turso.io';
  process.env.TURSO_READ_TOKEN = 'read-only-token';
  process.env.TURSO_WRITE_TOKEN = 'must-never-be-used';
  process.env.VERCEL_GIT_COMMIT_SHA = 'abc1234deadbeef';
});

test('latest passes the stored JSON through with CDN cache headers and uses only the read token', async () => {
  const calls = mockTurso([[{ json: '{"schema":1,"games":[]}', updated_utc: 't' }]]);
  const r = res();
  await latest({ method: 'GET' }, r);
  assert.equal(r.code, 200);
  assert.equal(r.body, '{"schema":1,"games":[]}');
  assert.match(r.headers['cache-control'], /s-maxage=20/);
  assert.equal(calls[0].url, 'https://demo-org.turso.io/v2/pipeline');
  assert.equal(calls[0].auth, 'Bearer read-only-token');
  assert.match(calls[0].body.requests[0].stmt.sql, /^SELECT/);
});

test('empty database returns an explicit empty document', async () => {
  mockTurso([[]]);
  const r = res();
  await record({ method: 'GET' }, r);
  assert.equal(JSON.parse(r.body).empty, true);
});

test('database failure is a 503 that is never cached', async () => {
  mockTurso([new Error('network down')]);
  const r = res();
  await latest({ method: 'GET' }, r);
  assert.equal(r.code, 503);
  assert.equal(r.headers['cache-control'], 'no-store');
});

test('refuses to run without a read token (never falls back to the write token)', async () => {
  delete process.env.TURSO_READ_TOKEN;
  mockTurso([[]]);
  const r = res();
  await latest({ method: 'GET' }, r);
  assert.equal(r.code, 503);
});

test('health reports the deployed commit in the exact shape the inbox workflow greps for', async () => {
  mockTurso([[{ json: '{"last_tick_utc":"x"}', updated_utc: new Date(Date.now() - 90000).toISOString() }]]);
  const r = res();
  await health({ method: 'GET' }, r);
  assert.ok(r.body.includes('"commit":"abc1234deadbeef"'));
  const out = JSON.parse(r.body);
  assert.equal(out.ok, true);
  assert.ok(out.snapshot_age_s >= 89 && out.snapshot_age_s <= 95);
  assert.equal(r.headers['cache-control'], 'no-store');
});

test('health stays up and says so when the database is down', async () => {
  mockTurso(['http500']);
  const r = res();
  await health({ method: 'GET' }, r);
  assert.equal(r.code, 200);
  assert.equal(JSON.parse(r.body).db, 'error');
});

test('game validates the id and returns the parsed analysis', async () => {
  let r = res();
  await game({ method: 'GET', query: { id: "x'; DROP TABLE picks;--" } }, r);
  assert.equal(r.code, 400);
  const calls = mockTurso([[{ id: 'g1', verdict: 'PLAY', payload_json: '{"headline":"PLAY"}' }], []]);
  r = res();
  await game({ method: 'GET', query: { id: 'espn:nba:9001' } }, r);
  assert.equal(JSON.parse(r.body).analysis.headline, 'PLAY');
  assert.deepEqual(calls[0].body.requests[0].stmt.args, [{ type: 'text', value: 'espn:nba:9001' }]);
  r = res();
  await game({ method: 'GET', query: { id: 'nope' } }, r);
  assert.equal(r.code, 404);
});

test('only GET and HEAD are allowed', async () => {
  const r = res();
  await latest({ method: 'POST' }, r);
  assert.equal(r.code, 405);
});

test('pasted values with quotes, spaces and newlines still work', async () => {
  process.env.TURSO_URL = ' "libsql://demo-org.turso.io"\n';
  process.env.TURSO_READ_TOKEN = "'read-only-token'\n";
  const calls = mockTurso([[{ json: '{}', updated_utc: 't' }]]);
  const r = res();
  await latest({ method: 'GET' }, r);
  assert.equal(r.code, 200);
  assert.equal(calls[0].url, 'https://demo-org.turso.io/v2/pipeline');
  assert.equal(calls[0].auth, 'Bearer read-only-token');
});

test('health explains a database error without leaking secrets', async () => {
  delete process.env.TURSO_READ_TOKEN;
  mockTurso([[]]);
  const r = res();
  await health({ method: 'GET' }, r);
  const out = JSON.parse(r.body);
  assert.equal(out.db, 'error');
  assert.equal(out.error, 'TURSO_READ_TOKEN is not set');
});

test('value encoding round-trips', () => {
  assert.deepEqual(db.enc(5), { type: 'integer', value: '5' });
  assert.deepEqual(db.enc(1.5), { type: 'float', value: 1.5 });
  assert.equal(db.dec({ type: 'integer', value: '7' }), 7);
  assert.equal(db.dec({ type: 'null' }), null);
});
