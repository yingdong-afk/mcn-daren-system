CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
 display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','staff')), active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS talents (
 id INTEGER PRIMARY KEY, nickname TEXT NOT NULL,
 douyin_id TEXT NOT NULL COLLATE NOCASE UNIQUE,
 fans INTEGER CHECK(fans >= 0), categories TEXT NOT NULL DEFAULT '',
 content_types TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '',
 historical_gmv_cents INTEGER CHECK(historical_gmv_cents >= 0),
 sales_period TEXT NOT NULL DEFAULT '', data_source TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT '待联系' CHECK(status IN ('待联系','已联系','已回复','已寄样','已拍摄','已发布','已成交')),
 owner_id INTEGER REFERENCES users(id), notes TEXT NOT NULL DEFAULT '',
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activities (
 id INTEGER PRIMARY KEY, talent_id INTEGER NOT NULL REFERENCES talents(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 contacted_at TEXT, reply TEXT NOT NULL DEFAULT '', followup_at TEXT,
 followup_state TEXT NOT NULL DEFAULT '待跟进' CHECK(followup_state IN ('待跟进','跟进中','已完成','无需跟进')),
 notes TEXT NOT NULL DEFAULT '', old_status TEXT, new_status TEXT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS talents_owner_status ON talents(owner_id,status);
CREATE INDEX IF NOT EXISTS activities_talent ON activities(talent_id,created_at);
CREATE INDEX IF NOT EXISTS activities_followup ON activities(followup_at,followup_state);
CREATE TABLE IF NOT EXISTS login_attempts (
 id INTEGER PRIMARY KEY, address TEXT NOT NULL, attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_address ON login_attempts(address,attempted_at);
