// Read-only access to Turso over HTTPS (the /v2/pipeline endpoint). No dependencies.
// Only TURSO_READ_TOKEN is used here, never the write token, so a leak of this project can't change data.

function endpoint() {
  const url = (process.env.TURSO_URL || '').replace(/^libsql:\/\//, 'https://').replace(/\/+$/, '');
  if (!url) throw new Error('TURSO_URL is not set');
  return url + '/v2/pipeline';
}

function enc(v) {
  if (v === null || v === undefined) return { type: 'null' };
  if (typeof v === 'number') return Number.isInteger(v) ? { type: 'integer', value: String(v) } : { type: 'float', value: v };
  return { type: 'text', value: String(v) };
}

function dec(cell) {
  switch (cell.type) {
    case 'null': return null;
    case 'integer': return parseInt(cell.value, 10);
    case 'float': return Number(cell.value);
    default: return cell.value;
  }
}

async function query(sql, args = []) {
  const token = process.env.TURSO_READ_TOKEN;
  if (!token) throw new Error('TURSO_READ_TOKEN is not set');
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const res = await fetch(endpoint(), {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ requests: [{ type: 'execute', stmt: { sql, args: args.map(enc) } }, { type: 'close' }] }),
      signal: ctl.signal,
    });
    if (!res.ok) throw new Error('database HTTP ' + res.status);
    const body = await res.json();
    const first = body.results[0];
    if (first.type !== 'ok') throw new Error((first.error && first.error.message) || 'query failed');
    const r = first.response.result;
    const names = r.cols.map((c) => c.name);
    return r.rows.map((row) => Object.fromEntries(row.map((c, i) => [names[i], dec(c)])));
  } finally {
    clearTimeout(timer);
  }
}

async function snapshot(key) {
  const rows = await query('SELECT json, updated_utc FROM snapshots WHERE key = ?', [key]);
  return rows[0] || null;
}

module.exports = { query, snapshot, enc, dec, endpoint };
