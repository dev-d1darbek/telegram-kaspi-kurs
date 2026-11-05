from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ChatJoinRequestHandler, filters,
)

from app import storage
from app.config import TOKEN
from app.handlers import (
    cmd_start, cmd_my, cmd_stats, cmd_add_course, cmd_delete_course,
    cmd_grant, on_pick, on_document, on_join, on_text,
    on_course_view, on_course_edit, on_back,
)


async def expiry_check(app):
    """Мерзімі өткен қолжетімділіктерді тексеріп, арнаға кіруін шектейді."""
    from app.storage import get_expired_accesses, get_course, revoke_access

    for row in get_expired_accesses():
        uid = row["user_id"]
        key = row["course_key"]
        course = get_course(key)
        revoke_access(key, uid)
        if course and course.get("chat_id"):
            try:
                await app.bot.ban_chat_member(course["chat_id"], uid)
                await app.bot.unban_chat_member(course["chat_id"], uid)
            except Exception:
                pass
        try:
            await app.bot.send_message(
                uid,
                f"❌ '{course['title'] if course else key}' курсының мерзімі аяқталды.",
            )
        except Exception:
            pass


async def post_init(app):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(expiry_check, "interval", hours=1, args=[app])
    scheduler.start()
    app.bot_data["expiry_scheduler"] = scheduler
    print("⏰ Мерзімді тексеру жоспарлағышы іске қосылды")


async def post_shutdown(app):
    scheduler = app.bot_data.get("expiry_scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)


def main():
    storage.init()
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("my", cmd_my))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("add_course", cmd_add_course))
    application.add_handler(CommandHandler("delete_course", cmd_delete_course))
    application.add_handler(CommandHandler("grant", cmd_grant))

    async def cancel(update, context):
        context.user_data.pop("edit", None)
        context.user_data.pop("awaiting_seller", None)
        if update.message:
            await update.message.reply_text("❌ Әрекет тоқтатылды.")

    application.add_handler(CommandHandler("cancel", cancel))

    application.add_handler(CallbackQueryHandler(on_pick, pattern=r"^pick:"))
    application.add_handler(CallbackQueryHandler(on_course_view, pattern=r"^course:"))
    application.add_handler(
        CallbackQueryHandler(on_course_edit, pattern=r"^(e:|toggle:|del:|seller:)")
    )
    application.add_handler(
        CallbackQueryHandler(on_back, pattern=r"^(back|admin_courses)$")
    )
    application.add_handler(ChatJoinRequestHandler(on_join))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("🚀 Bot іске қосылды")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
