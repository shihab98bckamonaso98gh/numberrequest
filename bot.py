import asyncio
import logging
from datetime import datetime

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

import config
from database import Database

# ---------- Quiet logging ----------
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# -----------------------------------

ASK_USERNAME = 0
ASK_AMOUNT = 1
SET_USERNAME_ADD = 2

db = Database()

# ---------- Keyboards ----------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📩 Number Request")],
            [KeyboardButton("👤 Set Username")],
            [KeyboardButton("📜 History")]
        ],
        resize_keyboard=True
    )

def set_username_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Add")],
            [KeyboardButton("➖ Remove")],
            [KeyboardButton("🔙 Back")]
        ],
        resize_keyboard=True
    )

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu_keyboard())

async def set_username_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Manage your saved username:", reply_markup=set_username_menu_keyboard())

async def set_username_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me the username you want to save:")
    return SET_USERNAME_ADD

async def set_username_add_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_username = update.message.text.strip()
    await db.set_user_custom_username(update.effective_user.id, new_username)
    await update.message.reply_text(f"✅ Username '{new_username}' saved.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def set_username_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.remove_user_custom_username(update.effective_user.id)
    await update.message.reply_text("✅ Saved username removed.", reply_markup=main_menu_keyboard())

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Main menu:", reply_markup=main_menu_keyboard())

async def number_request_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stored_username = await db.get_user_custom_username(user_id)

    if stored_username:
        context.user_data["custom_username"] = stored_username
        await update.message.reply_text(
            f"Using saved username: <b>{stored_username}</b>\nHow many numbers do you need?",
            parse_mode=ParseMode.HTML
        )
        return ASK_AMOUNT
    else:
        await update.message.reply_text("Please send me your username (not your Telegram username).")
        return ASK_USERNAME

async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["custom_username"] = update.message.text.strip()
    await update.message.reply_text("How many numbers do you need?")
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid positive number.")
        return ASK_AMOUNT

    user = update.effective_user
    custom_username = context.user_data["custom_username"]

    request_id = await db.add_request(
        user_id=user.id,
        full_name=user.full_name,
        telegram_username=user.username or "none",
        custom_username=custom_username,
        amount=amount
    )

    admin_text = (
        f"📥 <b>New Number Request</b>\n\n"
        f"👤 User: {user.full_name} (ID: <code>{user.id}</code>)\n"
        f"📧 Telegram: @{user.username or 'none'}\n"
        f"🏷 Custom Username: {custom_username}\n"
        f"🔢 Amount: {amount}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📌 Status: <b>Pending</b>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Complete", callback_data=f"complete_{request_id}")]
    ])

    try:
        msg = await context.bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=admin_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        await db.update_admin_message(request_id, msg.chat_id, msg.message_id)
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
        await update.message.reply_text("Request saved but admin notification failed. Please contact support.")
    else:
        await update.message.reply_text("✅ Your request is pending. We will notify you once it's completed.")

    context.user_data.clear()
    await update.message.reply_text("Main menu:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Request cancelled.", reply_markup=main_menu_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

async def complete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("complete_"):
        return
    try:
        request_id = int(data.split("_")[1])
    except (IndexError, ValueError):
        await query.edit_message_text("Invalid request ID.")
        return

    request = await db.complete_request(request_id)
    if not request:
        await query.edit_message_text("Request not found or already completed.")
        return

    original_text = query.message.text or query.message.caption
    new_text = original_text.replace("📌 Status: <b>Pending</b>", "📌 Status: <b>✅ Completed</b>")
    await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=None)

    try:
        await context.bot.send_message(
            chat_id=request["user_id"],
            text="🎉 Your number request has been completed!"
        )
    except Exception as e:
        logger.error(f"Could not notify user {request['user_id']}: {e}")

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == config.ADMIN_USER_ID)

    if is_admin:
        requests = await db.get_all_requests("completed")
    else:
        requests = await db.get_user_requests(user_id, "completed")

    if not requests:
        await update.message.reply_text("No completed requests found.")
        return

    lines = []
    for r in requests[:10]:
        lines.append(
            f"🆔 <code>{r['id']}</code> | {r['custom_username']} | {r['amount']} numbers | "
            f"👤 {r['user_full_name']} | {r['created_at']}"
        )
    text = "<b>📜 Recent Completed Requests:</b>\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ---------- Main ----------
async def main():
    await db.connect()
    logger.info(f"Bot starting. Admin chat: {config.ADMIN_CHAT_ID}, Admin user: {config.ADMIN_USER_ID}")
    logger.info("Bot started polling")

    # Build application with python-telegram-bot 20.10+
    app = Application.builder().token(config.BOT_TOKEN).build()

    number_request_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📩 Number Request$"), number_request_entry)],
        states={
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_username)],
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    set_username_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Add$"), set_username_add_prompt)],
        states={
            SET_USERNAME_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_username_add_save)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(number_request_conv)
    app.add_handler(set_username_conv)
    app.add_handler(MessageHandler(filters.Regex("^👤 Set Username$"), set_username_entry))
    app.add_handler(MessageHandler(filters.Regex("^➖ Remove$"), set_username_remove))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Back$"), back_to_main))
    app.add_handler(CallbackQueryHandler(complete_request_callback, pattern="^complete_"))
    app.add_handler(MessageHandler(filters.Regex("^📜 History$"), show_history))
    app.add_error_handler(error_handler)

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db.close()
        logger.info("Bot stopped gracefully")

if __name__ == "__main__":
    asyncio.run(main())