"""Барлық клавиатуралар."""

import datetime as dt
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.storage import (
    get_courses, get_course, user_access_keys, get_access_info,
)


def main_menu(admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [["📚 Менің сабақтарым", "📄 Чек жіберу"]]
    if admin:
        rows.append(["👨‍💼 Админ панелі"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["📊 Статистика", "📋 Курстар"],
        ["➕ Курс қосу", "🎁 Грант"],
        ["🔙 Негізгі мәзір"],
    ], resize_keyboard=True)


def purchase(uid: int) -> InlineKeyboardMarkup | None:
    owned = set(user_access_keys(uid))
    rows = [
        [InlineKeyboardButton(f"{c['title']} — {c['amount']}₸", callback_data=f"pick:{k}")]
        for k, c in get_courses().items() if k not in owned
    ]
    return InlineKeyboardMarkup(rows) if rows else None


def my_courses(uid: int) -> InlineKeyboardMarkup | None:
    rows = []
    for key in user_access_keys(uid):
        c = get_course(key)
        if not c:
            continue
        label = c["title"]
        info = get_access_info(key, uid)
        if info and info.get("expires_at"):
            d = (dt.datetime.fromisoformat(info["expires_at"]) - dt.datetime.now()).days
            label += f" ({d}к)" if d > 0 else " (бітті)"
        if c.get("channel_link"):
            rows.append([InlineKeyboardButton(f"🎓 {label}", url=c["channel_link"])])
    return InlineKeyboardMarkup(rows) if rows else None


def pay(key: str) -> InlineKeyboardMarkup:
    c = get_course(key)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"💳 Төлеу — {c['amount']}₸", url=c["pay_url"])
    ]])


def admin_courses() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"{'✅' if c['is_active'] else '❌'} {c['title']}",
            callback_data=f"course:{k}",
        )]
        for k, c in get_courses(active_only=False).items()
    ]
    rows.append([InlineKeyboardButton("🔙 Артқа", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def course_edit(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 ИП-ны чектен алу", callback_data=f"seller:{key}")],
        [InlineKeyboardButton("📝 Атауы", callback_data=f"e:title:{key}")],
        [InlineKeyboardButton("💰 Бағасы", callback_data=f"e:amount:{key}")],
        [InlineKeyboardButton("🔗 Төлем URL", callback_data=f"e:pay_url:{key}")],
        [InlineKeyboardButton("📺 Канал сілтемесі", callback_data=f"e:channel_link:{key}")],
        [InlineKeyboardButton("💬 Chat ID", callback_data=f"e:chat_id:{key}")],
        [InlineKeyboardButton("🏢 ИП атауы (қолмен)", callback_data=f"e:company:{key}")],
        [InlineKeyboardButton("🔢 ЖСН/БСН (қолмен)", callback_data=f"e:company_bin:{key}")],
        [InlineKeyboardButton("⏳ Мерзім (күн)", callback_data=f"e:expires_days:{key}")],
        [InlineKeyboardButton("📊 Белсенділік", callback_data=f"toggle:{key}")],
        [InlineKeyboardButton("🗑️ Жою", callback_data=f"del:{key}")],
        [InlineKeyboardButton("🔙 Артқа", callback_data="admin_courses")],
    ])
