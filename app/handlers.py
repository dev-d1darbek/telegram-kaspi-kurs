"""Барлық handler функциялар."""

import datetime as dt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatJoinRequest
from telegram.ext import ContextTypes

from app.config import is_admin, CHECKS_DIR, ADMIN_IDS
from app.keyboards import (
    main_menu, admin_menu, purchase, my_courses, pay,
    admin_courses, course_edit,
)
from app.storage import (
    register_user, get_courses, get_course, course_by_chat,
    set_pending, get_pending, clear_pending,
    has_access, grant_access, revoke_access, get_access_info,
    user_access_keys, receipt_used, save_payment, get_stats,
    create_grant, get_grant, consume_grant, upsert_course, delete_course,
)
from app.verifier import verify, extract_seller_info


# ============================================================
# USER
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    register_user(u.id)
    uid = u.id

    # Грант
    if context.args and context.args[0].startswith("gl_"):
        token = context.args[0][3:]
        g = get_grant(token)
        if not g:
            await update.message.reply_text("❌ Сілтеме жарамсыз.")
            return
        if g["used_by"] and g["used_by"] != uid:
            await update.message.reply_text("❌ Пайдаланылған.")
            return
        if not consume_grant(token, uid):
            await update.message.reply_text("❌ Қате.")
            return
        c = get_course(g["course_key"])
        if not c:
            await update.message.reply_text("❌ Курс жоқ.")
            return
        grant_access(g["course_key"], uid, c.get("expires_days") or 0)
        if c.get("chat_id"):
            try:
                await context.bot.approve_chat_join_request(c["chat_id"], uid)
            except Exception:
                pass
        await update.message.reply_text(
            f"✅ Сізге '{c['title']}' берілді.",
            reply_markup=my_courses(uid),
        )
        return

    # Тікелей курс
    if context.args:
        c = get_course(context.args[0])
        if c:
            if has_access(c["key"], uid):
                await update.message.reply_text(
                    f"✅ Сізде '{c['title']}' бар.",
                    reply_markup=my_courses(uid),
                )
                return
            set_pending(uid, c["key"])
            await update.message.reply_text(
                f"✅ Таңдалды: '{c['title']}'\nҚұны: {c['amount']} ₸\n\n"
                f"Төлеп, PDF чекті жіберіңіз.",
                reply_markup=pay(c["key"]),
            )
            return

    # Негізгі
    await update.message.reply_text(
        "📚 *Құрманғазы жабық арнасына қош келдіңіз!*",
        parse_mode="Markdown",
    )
    mine = my_courses(uid)
    if mine:
        await update.message.reply_text("✅ Сізде бар сабақтар:", reply_markup=mine)
    p = purchase(uid)
    if p:
        await update.message.reply_text("🛒 Жаңа сабақ таңдаңыз:", reply_markup=p)
    await update.message.reply_text(
        "Мәзір:", reply_markup=main_menu(admin=is_admin(uid))
    )


async def cmd_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mine = my_courses(uid)
    if mine:
        await update.message.reply_text("✅ Сізде бар сабақтар:", reply_markup=mine)
    else:
        await update.message.reply_text("📭 Сабақтар жоқ.")
    p = purchase(uid)
    if p:
        await update.message.reply_text("🛒 Сатып алу:", reply_markup=p)


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = (q.data or "").split(":", 1)[1]
    uid = q.from_user.id
    c = get_course(key)
    if not c or not c["is_active"]:
        await q.edit_message_text("❌ Курс жоқ.")
        return
    if has_access(key, uid):
        await q.edit_message_text(f"Бұл сабақ сізде бар: '{c['title']}'")
        return
    set_pending(uid, key)
    await q.edit_message_text(
        f"✅ Таңдалды: '{c['title']}'\nҚұны: {c['amount']} ₸\n\n"
        f"Төлеп, PDF чекті жіберіңіз.",
        reply_markup=pay(key),
    )


async def on_check_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pending = get_pending(uid)
    if pending:
        c = get_course(pending)
        await update.message.reply_text(
            f"📄 Kaspi PDF чекті жіберіңіз.\nТаңдалған: '{c['title']}' — {c['amount']} ₸"
        )
    else:
        p = purchase(uid)
        await update.message.reply_text("Алдымен сабақ таңдаңыз:", reply_markup=p)


async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Каналға кіру өтінішін өңдеу."""
    req: ChatJoinRequest = update.chat_join_request
    uid = req.from_user.id
    chat_id = req.chat.id
    chat_title = req.chat.title or "канал"

    # Курсты табу
    key = course_by_chat(chat_id)
    if not key:
        try:
            await context.bot.decline_chat_join_request(chat_id, uid)
        except Exception:
            pass
        return

    c = get_course(key)
    if not c:
        try:
            await context.bot.decline_chat_join_request(chat_id, uid)
        except Exception:
            pass
        return

    # Қолжетімділік бар ма?
    if has_access(key, uid):
        try:
            await context.bot.approve_chat_join_request(chat_id, uid)
        except Exception:
            # Approve сәтсіз болса, өтінішті қабылдамауға тырысамыз.
            try:
                await context.bot.decline_chat_join_request(chat_id, uid)
            except Exception:
                pass
            return

        expires_info = ""
        info = get_access_info(key, uid)
        if info and info.get("expires_at"):
            try:
                d = (dt.datetime.fromisoformat(info["expires_at"]) - dt.datetime.now()).days
                expires_info = f"\n⏳ Қолжетімділік: {d} күн" if d > 0 else "\n⏳ Мерзімі өтті"
            except (TypeError, ValueError):
                pass

        try:
            await context.bot.send_message(
                uid,
                f"✅ *Қош келдіңіз!*\n\n"
                f"Сіз '{c['title']}' каналына қосылдыңыз.{expires_info}",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    # Қолжетімділік жоқ: хабарлама жіберіп, өтінішті қабылдамау.
    try:
        await context.bot.send_message(
            uid,
            f"❌ *'{c['title']}' каналына кіру үшін сатып алу қажет.*\n\n"
            f"Курс бағасы: *{c['amount']} ₸*\n\n"
            "Сатып алу үшін /start басыңыз.",
            parse_mode="Markdown",
            reply_markup=purchase(uid),
        )
    except Exception:
        pass

    try:
        await context.bot.decline_chat_join_request(chat_id, uid)
    except Exception:
        pass


# ============================================================
# DOCUMENT (ЧЕК)
# ============================================================
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return
    uid = update.effective_user.id
    fname = (doc.file_name or "").lower()

    # Админ курс үшін сатушы деректерін тест чектен шығарып жатыр.
    awaiting_key = context.user_data.get("awaiting_seller")
    if awaiting_key and is_admin(uid):
        await _handle_seller_check(update, context, awaiting_key)
        return
    if not (doc.mime_type == "application/pdf" or fname.endswith(".pdf")):
        await update.message.reply_text("❌ Тек PDF чек жіберіңіз.")
        return

    pending = get_pending(uid)
    if not pending:
        await update.message.reply_text(
            "Алдымен сабақ таңдаңыз.", reply_markup=purchase(uid)
        )
        return

    course = get_course(pending)
    if not course:
        clear_pending(uid)
        await update.message.reply_text("❌ Курс табылмады.")
        return

    msg = await update.message.reply_text("🔎 Чек Kaspi базасымен тексерілуде...")

    # Жүктеу
    try:
        f = await doc.get_file()
        pdf_bytes = bytes(await f.download_as_bytearray())
    except Exception as e:
        await msg.edit_text(f"❌ Файл жүктелмеді: {e}")
        return
    if len(pdf_bytes) > 10 * 1024 * 1024:
        await msg.edit_text("❌ Файл тым үлкен (10 MB).")
        return

    # Тексеру
    result = verify(
        pdf_bytes,
        expected_amount=course["amount"],
        expected_bin=course.get("company_bin") or "",
    )

    if result.get("error"):
        await msg.edit_text(f"❌ {result['error']}")
        return

    if not result["valid"]:
        bad = [c for c in result["checks"] if not c["ok"]]
        txt = "❌ *Чекте қайшылық*\n\n"
        for c in bad:
            txt += f"• {c['name']}: күтілді `{c['pdf']}`, Kaspi-де `{c['kaspi']}`\n"
        await msg.edit_text(txt, parse_mode="Markdown")
        return

    rno = result["kaspi"].get("receipt_no")
    if receipt_used(rno):
        await msg.edit_text(f"❌ Бұл чек бұрын пайдаланылған: `{rno}`", parse_mode="Markdown")
        return

    kp = result["kaspi"]
    params = kp.get("params") or {}
    saved = save_payment(
        uid, pending, rno, int(kp["amount"]),
        str(params.get("ИИН/БИН продавца", "")),
        kp, params.get("Дата и время по Астане"),
    )
    if not saved:
        await msg.edit_text("❌ Чек бір уақытта өңделуде. Қайталаңыз.")
        return

    # PDF сақтау
    try:
        month = dt.datetime.now().strftime("%Y-%m")
        d = CHECKS_DIR / pending / month
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{uid}_{rno}.pdf").write_bytes(pdf_bytes)
    except Exception:
        pass

    grant_access(pending, uid, course.get("expires_days") or 0)

    if course.get("chat_id"):
        try:
            await context.bot.approve_chat_join_request(course["chat_id"], uid)
        except Exception:
            # Пайдаланушы әлі join request жібермеген — қалыпты жағдай.
            pass

    clear_pending(uid)

    expires_info = (
        f"\n⏳ Мерзім: {course['expires_days']} күн"
        if course.get("expires_days") else ""
    )

    has_link = bool(course.get("channel_link"))
    channel_instruction = (
        f"\n\n📺 Каналға кіру:\n"
        f"1. Төмендегі батырманы басыңыз\n"
        f"2. 'Кіруге өтініш жіберу' басыңыз\n"
        f"3. Бот автоматты мақұлдайды (5-10 секунд)"
        if has_link else
        f"\n\n⚠️ Канал сілтемесі орнатылмаған. Админге хабарласыңыз."
    )

    reply_kb = None
    if has_link:
        reply_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"📺 {course['title']} каналына кіру",
                url=course["channel_link"],
            )
        ]])

    await msg.edit_text(
        f"✅ Чек түпнұсқа деп расталды!\n\n"
        f"🎓 {course['title']}\n"
        f"💳 {kp['amount']} ₸\n"
        f"📄 {rno}\n"
        f"🏢 ИП: {course.get('company', '—')} ({course.get('company_bin', '—')})"
        f"{expires_info}"
        f"{channel_instruction}",
        reply_markup=reply_kb,
        disable_web_page_preview=True,
    )

    admin_txt = (
        f"🛒 *Жаңа төлем*\n\n"
        f"👤 `{uid}`\n"
        f"🎓 {course['title']}\n"
        f"💳 {kp['amount']} ₸\n"
        f"📄 `{rno}`\n"
        f"🏢 {course.get('company', '—')} / `{course.get('company_bin', '—')}`"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, admin_txt, parse_mode="Markdown")
        except Exception:
            pass


# ============================================================
# ADMIN
# ============================================================
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = get_stats()
    await update.message.reply_text(
        f"📊 *Статистика*\n\n"
        f"👥 Пайдаланушылар: *{s['users']}*\n"
        f"💳 Төлемдер: *{s['payments']}*\n"
        f"💰 Табыс: *{s['revenue']} ₸*\n"
        f"🎓 Белсенді: *{s['active']}*",
        parse_mode="Markdown",
    )


async def cmd_add_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Курс қосу; сатушының ЖСН/БСН-ы кейін тест чектен алынады."""
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "📋 *Курс қосу пішімі:*\n\n"
            "`/add_course key|Атауы|Баға|PayURL|ChannelLink|ChatID|Күн`\n\n"
            "*Мысал:*\n"
            "`/add_course c5|Жаңа сабақ|7500|https://kaspi.kz/|https://t.me/+abc123xyz|-1001234567890|30`\n\n"
            "*Маңызды:*\n"
            "• *ChannelLink* — каналдан `Invite Link` (`https://t.me/+...`)\n"
            "• *ChatID* — канал ID (минуспен: `-1001234567890`)\n"
            "• ChatID білу үшін каналға хабарлама жіберіп, "
            "@userinfobot арқылы алыңыз\n\n"
            "⚠️ _Курс қосылған соң бот ИП-ны тест чектен алуды ұсынады._",
            parse_mode="Markdown",
        )
        return

    try:
        parts = " ".join(context.args).split("|")
        if len(parts) != 7:
            raise ValueError("7 параметр қажет: key|title|amount|pay|link|chat|days")
        key, title, amount, pay_url, link, chat, days = [p.strip() for p in parts]
        if not key or not title:
            raise ValueError("Курс коды мен атауы бос болмауы керек")
        if get_course(key):
            await update.message.reply_text(f"❌ `{key}` бұрыннан бар.", parse_mode="Markdown")
            return
        amount_i, chat_i, days_i = int(amount), int(chat), int(days)
        if amount_i <= 0:
            raise ValueError("Баға 0-ден үлкен болуы керек")
        if days_i < 0:
            raise ValueError("Мерзім теріс болмауы керек")

        upsert_course(
            key, title=title, amount=amount_i, pay_url=pay_url,
            channel_link=link, chat_id=chat_i, expires_days=days_i,
            company=None, company_bin=None, is_active=1,
        )
        context.user_data["awaiting_seller"] = key
        await update.message.reply_text(
            f"✅ *Курс қосылды:* `{key}` — {title} — {amount_i} ₸\\n\\n"
            "🧾 *Енді сатушы деректерін орнатыңыз.*\\n"
            "Осы курсқа тиесілі PDF Kaspi чегін жіберіңіз. "
            "Бот чек мәтінінен ИП атауы мен ЖСН/БСН-ды алуға тырысады.\\n\\n"
            "Бас тарту: /cancel",
            parse_mode="Markdown",
        )
    except (ValueError, TypeError) as e:
        await update.message.reply_text(f"❌ Қате: {e}")


async def cmd_delete_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("`/delete_course <key>`", parse_mode="Markdown")
        return
    key = context.args[0]
    if not get_course(key):
        await update.message.reply_text("❌ Жоқ.")
        return
    delete_course(key)
    await update.message.reply_text(f"✅ '{key}' жойылды.")


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("`/grant <course_key>`", parse_mode="Markdown")
        return
    key = context.args[0]
    if not get_course(key):
        await update.message.reply_text("❌ Курс жоқ.")
        return
    token = create_grant(key, update.effective_user.id)
    me = await context.bot.get_me()
    await update.message.reply_text(
        f"🎁 `https://t.me/{me.username}?start=gl_{token}`",
        parse_mode="Markdown",
    )


async def on_course_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    key = (q.data or "").split(":", 1)[1]
    c = get_course(key)
    if not c:
        try:
            await q.edit_message_text("❌ Жоқ.", reply_markup=admin_courses())
        except Exception:
            pass
        return
    status = "✅" if c["is_active"] else "❌"
    text = (
        f"🔑 {key}\n"
        f"📝 {c['title']}\n"
        f"💰 {c['amount']} ₸\n"
        f"🏢 {c['company'] or '—'} / {c['company_bin'] or '—'}\n"
        f"🔗 {c['pay_url'] or '—'}\n"
        f"📺 {c['channel_link'] or '—'}\n"
        f"💬 {c['chat_id'] or 0}\n"
        f"⏳ {c['expires_days']} күн\n"
        f"📊 {status}"
    )
    try:
        await q.edit_message_text(
            text,
            reply_markup=course_edit(key),
            disable_web_page_preview=True,
        )
    except Exception as e:
        # "Message is not modified" — қалыпты жағдай
        if "not modified" not in str(e).lower():
            print(f"❌ on_course_view edit error: {e}")

async def on_course_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    data = q.data or ""

    if data.startswith("seller:"):
        key = data.split(":", 1)[1]
        c = get_course(key)
        context.user_data["awaiting_seller"] = key

        has_chat = bool(c and c.get("chat_id"))
        has_link = bool(c and c.get("channel_link"))
        warn = ""
        if not has_chat or not has_link:
            warn = (
                "\n⚠️ Назар аударыңыз: канал ID немесе сілтеме толық емес. "
                "Оларды алдымен толтырыңыз.\n"
            )

        text = (
            f"🧾 ИП-ны чектен алу\n\n"
            f"Курс: {key}\n"
            f"{warn}\n"
            f"📄 Тест чек жіберіңіз (10 ₸ — кез келген сома):\n"
            f"бот ИП аты мен ЖСН/БСН-ды автоматты алады.\n\n"
            f"Бас тарту: /cancel"
        )
        try:
            await q.edit_message_text(text)
        except Exception as e:
            if "not modified" not in str(e).lower():
                print(f"❌ seller edit error: {e}")
        return

    if data.startswith("toggle:"):
        key = data.split(":", 1)[1]
        c = get_course(key)
        if c:
            upsert_course(key, is_active=0 if c["is_active"] else 1)
            await on_course_view(update, context)
        return

    if data.startswith("del:"):
        key = data.split(":", 1)[1]
        delete_course(key)
        await q.edit_message_text(
            f"✅ '{key}' жойылды.", reply_markup=admin_courses()
        )
        return

    if data.startswith("e:"):
        _, field, key = data.split(":", 2)
        context.user_data["edit"] = (key, field)
        await q.edit_message_text(
            f"`{field}` үшін жаңа мәнді жіберіңіз:\n(бас тарту: /cancel)"
        )


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    try:
        await q.edit_message_text("Курстар:", reply_markup=admin_courses())
    except Exception as e:
        if "not modified" not in str(e).lower():
            print(f"❌ on_back error: {e}")

# ============================================================
# TEXT ROUTER
# ============================================================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    if text.lower() in ("/cancel", "cancel", "болдырмау"):
        context.user_data.pop("edit", None)
        context.user_data.pop("awaiting_seller", None)
        await update.message.reply_text("❌ Әрекет тоқтатылды.")
        return

    # Курс өрісін өзгерту режимі
    if is_admin(uid) and "edit" in context.user_data:
        key, field = context.user_data.pop("edit")
        if text == "/cancel":
            await update.message.reply_text("Бас тартылды.")
            return
        try:
            value = int(text) if field in ("amount", "chat_id", "expires_days") else text
            upsert_course(key, **{field: value})
            await update.message.reply_text(f"✅ `{field}` = `{value}`", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Қате: {e}")
        return

    if text == "📚 Менің сабақтарым":
        await cmd_my(update, context)
    elif text == "📄 Чек жіберу":
        await on_check_btn(update, context)
    elif text == "👨‍💼 Админ панелі" and is_admin(uid):
        await update.message.reply_text("Админ панелі:", reply_markup=admin_menu())
    elif text == "📊 Статистика" and is_admin(uid):
        await cmd_stats(update, context)
    elif text == "📋 Курстар" and is_admin(uid):
        await update.message.reply_text("Курстар:", reply_markup=admin_courses())
    elif text == "➕ Курс қосу" and is_admin(uid):
        await cmd_add_course(update, context)
    elif text == "🎁 Грант" and is_admin(uid):
        await update.message.reply_text(
            "`/grant <course_key>`", parse_mode="Markdown"
        )
    elif text == "🔙 Негізгі мәзір":
        await update.message.reply_text(
            "Мәзір:", reply_markup=main_menu(admin=is_admin(uid))
        )
    else:
        await update.message.reply_text(
            "Түсінбедім.", reply_markup=main_menu(admin=is_admin(uid))
        )


async def _handle_seller_check(
    update: Update, context: ContextTypes.DEFAULT_TYPE, course_key: str
):
    """Админ жіберген PDF-тен курс сатушысының деректерін шығарып, сақтайды."""
    doc = update.message.document
    fname = (doc.file_name or "").lower()
    if not (doc.mime_type == "application/pdf" or fname.endswith(".pdf")):
        await update.message.reply_text("❌ PDF чек жіберіңіз немесе /cancel басыңыз.")
        return

    msg = await update.message.reply_text("🔎 Чектен сатушы деректері алынуда...")
    try:
        telegram_file = await doc.get_file()
        pdf_bytes = bytes(await telegram_file.download_as_bytearray())
    except Exception as exc:
        await msg.edit_text(f"❌ Файл жүктелмеді: {exc}")
        return

    if len(pdf_bytes) > 10 * 1024 * 1024:
        await msg.edit_text("❌ Файл тым үлкен (10 MB-тан аспауы керек).")
        return

    course = get_course(course_key)
    if not course:
        context.user_data.pop("awaiting_seller", None)
        await msg.edit_text("❌ Курс табылмады. Қайтадан таңдаңыз.")
        return

    info = extract_seller_info(pdf_bytes)
    if not info.get("company_bin"):
        await msg.edit_text(
            "❌ Чектен сатушының 12 таңбалы ЖСН/БСН-ы табылмады.\\n\\n"
            "Басқа PDF чек жіберіңіз немесе /cancel басыңыз."
        )
        return

    upsert_course(
        course_key,
        company=info.get("company") or course.get("company") or "Белгісіз сатушы",
        company_bin=info["company_bin"],
    )
    context.user_data.pop("awaiting_seller", None)
    updated = get_course(course_key) or course
    await msg.edit_text(
        "✅ *Сатушы деректері сақталды*\\n\\n"
        f"🏢 {updated.get('company') or 'Белгісіз сатушы'}\\n"
        f"🔢 `{updated['company_bin']}`\\n\\n"
        f"Курс: *{updated['title']}* — {updated['amount']} ₸\\n\\n"
        "Ескерту: деректер PDF-тен автоматты шығарылды. "
        "Төлемді қабылдамас бұрын ИП/ЖСН/БСН дұрыстығын қолмен растаңыз.",
        parse_mode="Markdown",
    )
