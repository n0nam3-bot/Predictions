import { createRequire } from 'node:module';
import test from 'node:test';
import assert from 'node:assert/strict';

const L = createRequire(import.meta.url)('../../site/lib.js');
const near = (a, b) => Math.abs(a - b) < 1e-9;

test('to win is the profit at the posted price, the same numbers as the Python profit_units', () => {
  assert.ok(near(L.toWin(-150, 2), 1.3333333333333333));   // risk 2 to win 1.33
  assert.ok(near(L.toWin(-110, 1), 0.9090909090909091));
  assert.ok(near(L.toWin(130, 1), 1.3));
  assert.ok(near(L.toWin(+150, 2), 3));
  assert.ok(near(L.toWin(-243, 3), 1.2345679012345678));   // the demo's Summit Ravens play
});

test('to win says nothing rather than guess when the price or stake is missing', () => {
  assert.equal(L.toWin(null, 1), null);
  assert.equal(L.toWin(undefined, 1), null);
  assert.equal(L.toWin(0, 1), null);
  assert.equal(L.toWin('abc', 1), null);
  assert.equal(L.toWin(-110, 'x'), null);
});

test('the risk meter fills 1 to 3 bars and never more', () => {
  assert.deepEqual([1, 2, 3, 4, 0, null, 'x'].map(L.meter), [1, 2, 3, 3, 0, 0, 0]);
});

test('units print without noise', () => {
  assert.equal(L.plain(2), '2');
  assert.equal(L.plain(1.5), '1.5');
  assert.equal(L.plain(11.254), '11.25');
  assert.equal(L.signed(1.3333), '+1.33u');
  assert.equal(L.signed(-2), '\u22122.00u');
  assert.equal(L.signed(0), '0.00u');
});
