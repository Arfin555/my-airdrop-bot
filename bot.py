import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from pymongo import MongoClient
from datetime import datetime

# ─── Logging ───────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── ENV Variables ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")          # BotFather থেকে পাওয়া token
MONGO_URI = os.environ.get("MONGO_URI")          # MongoDB connection string
BOT_USERNAME = os.environ.get("BOT_USERNAME")    # যেমন: myairdrop_bot

# ─── Database ──────────────────────────────────────────────
client = MongoClient(MONGO_URI)
db = client["airdrop_bot"]
users = db["users"]

# ─── Referral Reward ───────────────────────────────────────
REFERRAL_REWARD = 100  # প্রতি referral এ কত coin


# ─── /start ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = int(args[0]) if args else None

    existing = users.find_one({"user_id": user.id})

    if not existing:
        # নতুন user তৈরি করো
        users.insert_one({
            "user_id": user.id,
            "username": user.username or user.first_name,
            "first_name": user.first_name,
            "coins": 0,
            "referrals": 0,
            "referred_by": referred_by,
            "joined_at": datetime.utcnow(),
            "claimed": False
        })

        # Referrer কে reward দাও
        if referred_by and referred_by != user.id:
            users.update_one(
                {"user_id": referred_by},
                {"$inc": {"coins": REFERRAL_REWARD, "referrals": 1}}
            )
            try:
                await context.bot.send_message(
                    chat_id=referred_by,
                    text=f"🎉 নতুন referral! *{user.first_name}* যোগ দিয়েছে!\n"
                         f"আপনি *{REFERRAL_REWARD} coins* পেয়েছেন! 🪙",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    ref_link = f"https://t.me/{BOT_USERNAME}?start={user.id}"

    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("🎁 Claim Airdrop", callback_data="claim")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👋 স্বাগতম, *{user.first_name}*!\n\n"
        f"🪙 প্রতি referral = *{REFERRAL_REWARD} coins*\n\n"
        f"📎 আপনার Referral Link:\n`{ref_link}`\n\n"
        f"বন্ধুদের পাঠান এবং coins জমান! 🚀",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


# ─── Button Handlers ───────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user_data = users.find_one({"user_id": user_id})

    if not user_data:
        await query.edit_message_text("আগে /start দিন!")
        return

    if query.data == "balance":
        await query.edit_message_text(
            f"💰 *আপনার Balance*\n\n"
            f"🪙 Coins: *{user_data['coins']}*\n"
            f"👥 Referrals: *{user_data['referrals']}*",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif query.data == "referrals":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        await query.edit_message_text(
            f"👥 *আপনার Referral Info*\n\n"
            f"মোট Referral: *{user_data['referrals']}*\n"
            f"মোট Coins: *{user_data['coins']}*\n\n"
            f"📎 আপনার Link:\n`{ref_link}`",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif query.data == "leaderboard":
        top_users = users.find().sort("coins", -1).limit(10)
        text = "🏆 *Top 10 Leaderboard*\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, u in enumerate(top_users):
            medal = medals[i] if i < 3 else f"{i+1}."
            name = u.get("first_name", "Unknown")
            text += f"{medal} {name} — *{u['coins']} coins*\n"
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif query.data == "claim":
        if user_data.get("claimed"):
            await query.edit_message_text(
                "⚠️ আপনি আগেই Airdrop Claim করেছেন!",
                reply_markup=back_keyboard()
            )
        elif user_data["coins"] < 500:
            await query.edit_message_text(
                f"❌ Claim করতে কমপক্ষে *500 coins* লাগবে!\n"
                f"আপনার কাছে আছে: *{user_data['coins']} coins*\n\n"
                f"আরও বন্ধু invite করুন! 🚀",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
        else:
            users.update_one({"user_id": user_id}, {"$set": {"claimed": True}})
            await query.edit_message_text(
                f"🎉 *Congratulations!*\n\n"
                f"✅ আপনার *{user_data['coins']} coins* Claim সফল হয়েছে!\n"
                f"শীঘ্রই আপনার wallet এ পাঠানো হবে। 🪙",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )

    elif query.data == "back":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data="balance"),
             InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
            [InlineKeyboardButton("🎁 Claim Airdrop", callback_data="claim")],
        ]
        await query.edit_message_text(
            f"🏠 *Main Menu*\n\n"
            f"📎 আপনার Referral Link:\n`{ref_link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])


# ─── Main ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot চালু হচ্ছে...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
