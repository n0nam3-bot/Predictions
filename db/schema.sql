-- Statements are separated by lines that contain only "-- split". Safe to run repeatedly.
-- Bouts use home = corner 1 and away = corner 2.
CREATE TABLE IF NOT EXISTS games (
  id TEXT PRIMARY KEY, sport TEXT NOT NULL, kind TEXT NOT NULL, event_id TEXT, event_name TEXT,
  start_utc TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL, venue TEXT,
  status TEXT NOT NULL DEFAULT 'scheduled', home_score REAL, away_score REAL, winner TEXT, method TEXT,
  home_record TEXT, away_record TEXT, odds_json TEXT, missed INTEGER NOT NULL DEFAULT 0,
  updated_utc TEXT NOT NULL
)
-- split
CREATE INDEX IF NOT EXISTS idx_games_start ON games(start_utc)
-- split
CREATE TABLE IF NOT EXISTS odds_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, taken_utc TEXT NOT NULL, book TEXT,
  home_ml REAL, away_ml REAL, spread_home REAL, total REAL, over_odds REAL, under_odds REAL
)
-- split
CREATE INDEX IF NOT EXISTS idx_odds_game ON odds_snapshots(game_id, taken_utc)
-- split
CREATE TABLE IF NOT EXISTS facts (
  game_id TEXT PRIMARY KEY, packet_json TEXT NOT NULL, coverage REAL NOT NULL, built_utc TEXT NOT NULL
)
-- split
CREATE TABLE IF NOT EXISTS picks (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, game_id TEXT NOT NULL UNIQUE,
  sport TEXT NOT NULL, start_utc TEXT NOT NULL, published_utc TEXT NOT NULL, tag TEXT NOT NULL,
  verdict TEXT NOT NULL, market TEXT, selection TEXT, line REAL, odds REAL, fair_odds REAL,
  model_prob REAL, market_prob REAL, edge REAL, units INTEGER, confidence INTEGER,
  top_pick INTEGER NOT NULL DEFAULT 0, rank_score REAL, coverage REAL, payload_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL
)
-- split
CREATE TRIGGER IF NOT EXISTS picks_no_update BEFORE UPDATE ON picks
BEGIN SELECT RAISE(ABORT, 'picks are insert-only'); END
-- split
CREATE TRIGGER IF NOT EXISTS picks_no_delete BEFORE DELETE ON picks
BEGIN SELECT RAISE(ABORT, 'picks are insert-only'); END
-- split
CREATE TABLE IF NOT EXISTS grades (
  pick_id TEXT PRIMARY KEY, grade TEXT NOT NULL, reason TEXT, home_score REAL, away_score REAL,
  profit_units REAL, closing_odds REAL, clv REAL, graded_utc TEXT NOT NULL, source TEXT
)
-- split
CREATE TRIGGER IF NOT EXISTS grades_final_is_final BEFORE UPDATE ON grades
WHEN OLD.grade != 'PENDING_REVIEW'
BEGIN SELECT RAISE(ABORT, 'a graded pick cannot change'); END
-- split
CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, json TEXT NOT NULL, updated_utc TEXT NOT NULL)
-- split
CREATE TABLE IF NOT EXISTS quota (key TEXT PRIMARY KEY, used INTEGER NOT NULL DEFAULT 0, cap INTEGER NOT NULL, updated_utc TEXT NOT NULL)
-- split
CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, at_utc TEXT NOT NULL, detail TEXT)
-- split
CREATE TABLE IF NOT EXISTS inbox_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT NOT NULL, zip TEXT, sha256 TEXT, result TEXT, commit_sha TEXT, detail TEXT)
