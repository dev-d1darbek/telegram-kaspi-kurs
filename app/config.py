"""Барлық конфигурация осында."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN: str = os.getenv("TG_BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x.strip()
]

DB_PATH = Path("data/bot.db")
CHECKS_DIR = Path("checks")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
CHECKS_DIR.mkdir(parents=True, exist_ok=True)

if not TOKEN:
    raise RuntimeError("TG_BOT_TOKEN жоқ (.env файлын толтырыңыз)")


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS
