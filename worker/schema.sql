-- line-agent-kit の D1 の表（wrangler d1 execute <DB名> --remote --file=worker/schema.sql）
-- お客様のメッセージ本文は保存しない。持つのは「誰が・いつ・どの段にいるか」だけ。

CREATE TABLE IF NOT EXISTS friends (
  user_id      TEXT PRIMARY KEY,          -- LINE の userId（U から始まる33文字）
  ref          TEXT NOT NULL UNIQUE,      -- 外に出してよい札（決済リンクに付ける・userId は外に出さない）
  status       TEXT NOT NULL DEFAULT 'active',  -- active / blocked
  followed_at  INTEGER NOT NULL,          -- 秒（UTC）
  updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
  user_id    TEXT NOT NULL,
  tag        TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

CREATE TABLE IF NOT EXISTS enrollments (
  user_id     TEXT NOT NULL,
  scenario_id TEXT NOT NULL,
  started_at  INTEGER NOT NULL,
  next_step   INTEGER NOT NULL DEFAULT 0,
  next_at     INTEGER,                     -- 次の便を送る時刻（秒・UTC）
  status      TEXT NOT NULL DEFAULT 'active',  -- active / done / stopped
  PRIMARY KEY (user_id, scenario_id)
);
CREATE INDEX IF NOT EXISTS idx_enr_due ON enrollments(status, next_at);

CREATE TABLE IF NOT EXISTS answers (
  user_id     TEXT NOT NULL,
  survey_id   TEXT NOT NULL,
  question_id TEXT NOT NULL,
  value       TEXT NOT NULL,
  answered_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, survey_id, question_id)
);

CREATE TABLE IF NOT EXISTS bookings (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  starts_at  INTEGER NOT NULL,
  title      TEXT NOT NULL,
  url        TEXT,
  status     TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled / cancelled / done
  sent       TEXT NOT NULL DEFAULT '[]',          -- 送り終えたリマインド（分）の JSON 配列
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_due ON bookings(status, starts_at);

-- 同じ Webhook が2回届いても1回だけ処理するための控え（LINE の webhookEventId・Stripe の event id）
CREATE TABLE IF NOT EXISTS seen_events (
  id          TEXT PRIMARY KEY,
  received_at INTEGER NOT NULL
);

-- 送った記録（通数を数えるため・本文は残さない）
CREATE TABLE IF NOT EXISTS send_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT NOT NULL,     -- step / reminder / delivery
  ref_id      TEXT,              -- scenario:step や booking id
  recipients  INTEGER NOT NULL,
  status      INTEGER NOT NULL,  -- LINE の HTTP ステータス
  sent_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
  event_id    TEXT PRIMARY KEY,  -- Stripe の event id
  user_id     TEXT,
  product_id  TEXT,
  amount      INTEGER,
  currency    TEXT,
  created_at  INTEGER NOT NULL
);
