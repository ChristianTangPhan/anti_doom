"""SQLite storage: which IG chat goes to which Discord channel, plus seen message IDs."""
import sqlite3
import time

DB_FILE = "anti_doom.db"


class Store:
    def __init__(self, path=DB_FILE):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS bridges (
                thread_id   TEXT PRIMARY KEY,
                channel_id  INTEGER NOT NULL UNIQUE,
                webhook_url TEXT NOT NULL,
                title       TEXT NOT NULL,
                muted       INTEGER NOT NULL DEFAULT 0,
                last_seen   REAL NOT NULL DEFAULT 0   -- unix time of newest relayed message
            );
            CREATE TABLE IF NOT EXISTS ig_calls (
                at   REAL NOT NULL,                   -- unix time of an IG request
                kind TEXT NOT NULL                    -- 'api' or 'login'
            );
            CREATE TABLE IF NOT EXISTS seen (
                msg_id  TEXT PRIMARY KEY,             -- relayed to Discord, or sent by the bot
                seen_at REAL NOT NULL
            );
            """
        )
        self.db.commit()

    # ---- bridges ----
    def add(self, thread_id, channel_id, webhook_url, title, last_seen):
        self.db.execute(
            "INSERT INTO bridges (thread_id, channel_id, webhook_url, title, last_seen) VALUES (?, ?, ?, ?, ?)",
            (str(thread_id), channel_id, webhook_url, title, last_seen),
        )
        self.db.commit()

    def remove(self, thread_id):
        self.db.execute("DELETE FROM bridges WHERE thread_id = ?", (str(thread_id),))
        self.db.commit()

    def all(self):
        return self.db.execute("SELECT * FROM bridges ORDER BY title").fetchall()

    def by_channel(self, channel_id):
        return self.db.execute("SELECT * FROM bridges WHERE channel_id = ?", (channel_id,)).fetchone()

    def thread_ids(self):
        return {row["thread_id"] for row in self.db.execute("SELECT thread_id FROM bridges")}

    def set_muted(self, thread_id, muted, last_seen=None):
        if last_seen is None:
            self.db.execute("UPDATE bridges SET muted = ? WHERE thread_id = ?", (int(muted), str(thread_id)))
        else:
            self.db.execute(
                "UPDATE bridges SET muted = ?, last_seen = ? WHERE thread_id = ?",
                (int(muted), last_seen, str(thread_id)),
            )
        self.db.commit()

    def set_last_seen(self, thread_id, last_seen):
        self.db.execute("UPDATE bridges SET last_seen = ? WHERE thread_id = ?", (last_seen, str(thread_id)))
        self.db.commit()

    # ---- seen message IDs ----
    def mark_seen(self, msg_id):
        self.db.execute("INSERT OR IGNORE INTO seen (msg_id, seen_at) VALUES (?, ?)", (str(msg_id), time.time()))
        self.db.commit()

    def was_seen(self, msg_id):
        return self.db.execute("SELECT 1 FROM seen WHERE msg_id = ?", (str(msg_id),)).fetchone() is not None

    def prune_seen(self, older_than_days=3):
        self.db.execute("DELETE FROM seen WHERE seen_at < ?", (time.time() - older_than_days * 86400,))
        self.db.commit()

    # ---- IG request log (survives restarts) ----
    def record_calls(self, count, kind="api"):
        now = time.time()
        self.db.executemany("INSERT INTO ig_calls (at, kind) VALUES (?, ?)", [(now, kind)] * count)
        self.db.commit()

    def recent_calls(self, seconds):
        rows = self.db.execute(
            "SELECT at FROM ig_calls WHERE at > ? ORDER BY at", (time.time() - seconds,)
        ).fetchall()
        return [r["at"] for r in rows]

    def recent_logins(self, seconds):
        return self.db.execute(
            "SELECT COUNT(*) FROM ig_calls WHERE kind = 'login' AND at > ?", (time.time() - seconds,)
        ).fetchone()[0]

    def prune_calls(self, older_than_days=1):
        self.db.execute("DELETE FROM ig_calls WHERE at < ?", (time.time() - older_than_days * 86400,))
        self.db.commit()
