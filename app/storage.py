"""Дерекқор — барлық CRUD функциялар."""

import sqlite3
import json
import secrets
import datetime as dt
from contextlib import contextmanager
from typing import Optional

from app.config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    amount INTEGER NOT NULL,
    pay_url TEXT,
    channel_link TEXT,
    chat_id INTEGER,
    company TEXT,
    company_bin TEXT,
    expires_days INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    receipt_no TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    course_key TEXT NOT NULL,
    amount INTEGER NOT NULL,
    company_bin TEXT,
    kaspi_json TEXT,
    paid_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access (
    course_key TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    granted_at TEXT NOT NULL,
    expires_at TEXT,
    is_active INTEGER DEFAULT 1,
    PRIMARY KEY (course_key, user_id)
);
CREATE TABLE IF NOT EXISTS pending (
    user_id INTEGER PRIMARY KEY,
    course_key TEXT NOT NULL,
    selected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grant_links (
    token TEXT PRIMARY KEY,
    course_key TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    used_by INTEGER,
    used_at TEXT
);
"""

DEFAULT_COURSES = [
    ("course1", "Ризық 1,2,3", 7500, "https://kaspi.kz/", "https://t.me/", 0,
     "ХАДИША", "910420351008", 0),
    ("course2", "Алланың көркем есімдері", 7500, "https://kaspi.kz/", "https://t.me/", 0,
     "ХАДИША", "910420351008", 0),
    ("course3", "Нафәқа, Хайыр, Шүкір", 7500, "https://kaspi.kz/", "https://t.me/", 0,
     "ХАДИША", "910420351008", 0),
    ("course4", "Аят сырлары", 12000, "https://kaspi.kz/", "https://t.me/", 0,
     "BASTAU", "123456789012", 40),
]


def now() -> str:
    return dt.datetime.now().isoformat()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    with db() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
            for k, t, a, p, ch, cid, comp, bin_, d in DEFAULT_COURSES:
                c.execute("""
                    INSERT INTO courses
                    (key, title, amount, pay_url, channel_link, chat_id,
                     company, company_bin, expires_days, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (k, t, a, p, ch, cid, comp, bin_, d, now()))


# === USERS ===
def register_user(uid: int):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", (uid, now()))


# === COURSES ===
def get_courses(active_only: bool = True) -> dict:
    q = "SELECT * FROM courses"
    if active_only:
        q += " WHERE is_active=1"
    q += " ORDER BY created_at"
    with db() as c:
        return {r["key"]: dict(r) for r in c.execute(q).fetchall()}


def get_course(key: str) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT * FROM courses WHERE key=?", (key,)).fetchone()
    return dict(r) if r else None


def course_by_chat(chat_id: int) -> Optional[str]:
    with db() as c:
        r = c.execute("SELECT key FROM courses WHERE chat_id=?", (chat_id,)).fetchone()
    return r["key"] if r else None


def upsert_course(key: str, **fields):
    with db() as c:
        exists = c.execute("SELECT 1 FROM courses WHERE key=?", (key,)).fetchone()
        if exists:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE courses SET {sets} WHERE key=?", (*fields.values(), key))
        else:
            fields["key"] = key
            fields["created_at"] = now()
            cols = ", ".join(fields.keys())
            ph = ", ".join("?" * len(fields))
            c.execute(f"INSERT INTO courses ({cols}) VALUES ({ph})", tuple(fields.values()))


def delete_course(key: str):
    with db() as c:
        c.execute("DELETE FROM courses WHERE key=?", (key,))


# === PENDING ===
def set_pending(uid: int, key: str):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO pending VALUES (?, ?, ?)", (uid, key, now()))


def get_pending(uid: int) -> Optional[str]:
    with db() as c:
        r = c.execute("SELECT course_key FROM pending WHERE user_id=?", (uid,)).fetchone()
    return r["course_key"] if r else None


def clear_pending(uid: int):
    with db() as c:
        c.execute("DELETE FROM pending WHERE user_id=?", (uid,))


# === ACCESS ===
def has_access(key: str, uid: int) -> bool:
    """Тек белсенді әрі мерзімі өтпеген қолжетімділікті растау."""
    with db() as c:
        r = c.execute(
            "SELECT 1 FROM access WHERE course_key=? AND user_id=? AND is_active=1 "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (key, uid, now()),
        ).fetchone()
        if r is None:
            # Мерзімі өткен жазбаны бірден белсенді емес деп белгілейміз.
            c.execute(
                "UPDATE access SET is_active=0 WHERE course_key=? AND user_id=? "
                "AND is_active=1 AND expires_at IS NOT NULL AND expires_at <= ?",
                (key, uid, now()),
            )
    return r is not None


def grant_access(key: str, uid: int, expires_days: int = 0):
    expires_at = None
    if expires_days > 0:
        expires_at = (dt.datetime.now() + dt.timedelta(days=expires_days)).isoformat()
    with db() as c:
        c.execute("""
            INSERT OR REPLACE INTO access
            (course_key, user_id, granted_at, expires_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (key, uid, now(), expires_at))


def revoke_access(key: str, uid: int):
    with db() as c:
        c.execute(
            "UPDATE access SET is_active=0 WHERE course_key=? AND user_id=?",
            (key, uid),
        )


def get_access_info(key: str, uid: int) -> Optional[dict]:
    with db() as c:
        r = c.execute(
            "SELECT * FROM access WHERE course_key=? AND user_id=?", (key, uid)
        ).fetchone()
    return dict(r) if r else None


def user_access_keys(uid: int) -> list[str]:
    with db() as c:
        rows = c.execute("""
            SELECT course_key FROM access
            WHERE user_id=? AND is_active=1
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY granted_at DESC
        """, (uid, now())).fetchall()
    return [r["course_key"] for r in rows]


def get_expired_accesses() -> list[dict]:
    with db() as c:
        rows = c.execute("""
            SELECT * FROM access
            WHERE expires_at IS NOT NULL AND expires_at <= ? AND is_active=1
        """, (now(),)).fetchall()
    return [dict(r) for r in rows]


def get_all_active_access() -> list[dict]:
    with db() as c:
        rows = c.execute("""
            SELECT * FROM access WHERE is_active=1 ORDER BY granted_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


# === PAYMENTS ===
def receipt_used(receipt_no: str) -> bool:
    with db() as c:
        return c.execute(
            "SELECT 1 FROM payments WHERE receipt_no=?", (receipt_no,)
        ).fetchone() is not None


def save_payment(uid: int, key: str, receipt_no: str, amount: int,
                 company_bin: str, kaspi_data: dict, paid_at: Optional[str]) -> bool:
    """True — сақталды, False — чек бұрыннан бар (race-safe)."""
    try:
        with db() as c:
            c.execute("""
                INSERT INTO payments
                (receipt_no, user_id, course_key, amount, company_bin,
                 kaspi_json, paid_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (receipt_no, uid, key, amount, company_bin,
                  json.dumps(kaspi_data, ensure_ascii=False, default=str),
                  paid_at, now()))
        return True
    except sqlite3.IntegrityError:
        return False


def get_stats() -> dict:
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pays = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments"
        ).fetchone()
        active = c.execute(
            "SELECT COUNT(*) FROM access WHERE is_active=1"
        ).fetchone()[0]
    return {"users": users, "payments": pays[0], "revenue": pays[1], "active": active}


# === GRANT LINKS ===
def create_grant(key: str, by: int) -> str:
    token = secrets.token_urlsafe(10).replace("-", "_")
    with db() as c:
        c.execute(
            "INSERT INTO grant_links VALUES (?, ?, ?, ?, NULL, NULL)",
            (token, key, by, now()),
        )
    return token


def get_grant(token: str) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT * FROM grant_links WHERE token=?", (token,)).fetchone()
    return dict(r) if r else None


def consume_grant(token: str, uid: int) -> bool:
    with db() as c:
        cur = c.execute(
            "UPDATE grant_links SET used_by=?, used_at=? WHERE token=? AND used_by IS NULL",
            (uid, now(), token),
        )
    return cur.rowcount > 0
