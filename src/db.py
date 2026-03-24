"""SQLite database for tracking meetings and recordings."""

import aiosqlite
from src.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    meeting_url TEXT,
    start_time TEXT,
    end_time TEXT,
    duration_seconds INTEGER,
    organizer TEXT,
    source TEXT DEFAULT 'email',
    status TEXT DEFAULT 'scheduled',
    recording_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meeting_url, start_time)
);

CREATE TABLE IF NOT EXISTS scheduler_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT,
    status TEXT,
    details TEXT,
    ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    await db.commit()
    await db.close()
