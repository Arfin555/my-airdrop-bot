import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_ID = 8722735212
REFERRAL_REWARD = 100
MIN_WITHDRAW = 1000
SPAM_LIMIT = 5
SPAM_WINDOW = 10

client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client["airdrop_bot"]
users = db["users"]
tasks = db["tasks"]
withdrawals = db["withdrawals"]
spam_log = db["spam_log"]

def is_admin(user_id):
    return user_id == ADMIN_ID

def anti_spam(user_id):
    now = datetime.utcnow()
    window = now - timedelta(seconds=SPAM_WINDOW)
    count = spam_log.count_documents({"user_id": user_id, "time": {"$gte": window}})
    if count >= SPAM_LIMIT:
        return False
    spam_log.insert_one({"user_id": user_id, "time": now})
    return True

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("✅ Tasks", callback_data="tasks"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("💎 TON Wallet", callback_data="wallet"),
         InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
    ])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not anti_spam(user.id):
        await update.message.reply_text("⚠️ Spam detected! একটু অপেক্ষা করুন।")
        return
    args = context.args
    referred_by = int(args[0]) if args and args[0].isdigit() else None
    existing = users.find_one({"user_id": user.id})
    if not existing:
        users.insert_one({
            "user_id": user.id,
            "username": user.username or "",
            "first_name": user.first_name,
            "coins": 0,
            "referrals": 0,
            "referred_by": referred_by,
            "joined_at": datetime.utcnow(),
            "ton_wallet": None,
            "completed_tasks": [],
            "is_banned": False,
        })
        if referred_by and referred_by != user.id:
            ref_user = users.find_one({"user_id": referred_by})
            if ref_user and not ref_user.get("is_banned"):
                users.update_one({"user_id": referred_by}, {"$inc": {"coins": REFERRAL_REWARD, "referrals": 1}})
                try:
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=f"🎉 *নতুন Referral!*\n\n👤 {user.first_name} যোগ দিয়েছে!\n🪙 +{REFERRAL_REWARD} coins!",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
    user_data = users.find_one({"user_id": user.id})
    if user_data and user_data.get("is_banned"):
        await update.message.reply_text("🚫 আপনি banned।")
        return
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user.id}"
    await update.message.reply_text(
        f"👋 স্বাগতম, *{user.first_name}*!\n\n"
        f"🪙 প্রতি referral = *{REFERRAL_REWARD} coins*\n"
        f"💸 Minimum withdraw = *{MIN_WITHDRAW} coins*\n\n"
        f"📎 আপনার Referral Link:\n`{ref_link}`",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not anti_spam(user_id):
        await query.answer("⚠️ Spam! একটু অপেক্ষা করুন।", show_alert=True)
        return
    user_data = users.find_one({"user_id": user_id})
    if not user_data:
        await query.edit_message_text("আগে /start দিন!")
        return
    if user_data.get("is_banned"):
        await query.edit_message_text("🚫 আপনি banned।")
        return
    data = query.data

    if data == "balance":
        await query.edit_message_text(
            f"💰 *আপনার Balance*\n\n🪙 Coins: *{user_data['coins']}*\n👥 Referrals: *{user_data['referrals']}*\n💎 Wallet: `{user_data.get('ton_wallet') or 'সংযুক্ত নয়'}`",
            parse_mode="Markdown", reply_markup=back_btn()
        )

    elif data == "referrals":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        await query.edit_message_text(
            f"👥 *Referral Info*\n\nমোট Referral: *{user_data['referrals']}*\nCoins: *{user_data['coins']}*\n\n📎 `{ref_link}`",
            parse_mode="Markdown", reply_markup=back_btn()
        )

    elif data == "leaderboard":
        top = users.find({"is_banned": {"$ne": True}}).sort("coins", -1).limit(10)
        text = "🏆 *Top 10*\n\n"
        medals = ["🥇","🥈","🥉"]
        for i, u in enumerate(top):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {u.get('first_name','?')} — *{u['coins']} coins*\n"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_btn())

    elif data == "tasks":
        all_tasks = list(tasks.find({"active": True}))
        completed = user_data.get("completed_tasks", [])
        if not all_tasks:
            await query.edit_message_text("📋 এখন কোনো task নেই।", reply_markup=back_btn())
            return
        keyboard = []
        for task in all_tasks:
            tid = str(task["_id"])
            status = "✅" if tid in completed else "⬜"
            keyboard.append([InlineKeyboardButton(f"{status} {task['title']} (+{task['reward']} coins)", callback_data=f"task_{tid}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        await query.edit_message_text("✅ *Tasks*\n\nTask সম্পন্ন করুন!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("task_"):
        from bson import ObjectId
        tid = data[5:]
        completed = user_data.get("completed_tasks", [])
        if tid in completed:
            await query.answer("আগেই সম্পন্ন!", show_alert=True)
            return
        task = tasks.find_one({"_id": ObjectId(tid)})
        if not task:
            await query.answer("Task পাওয়া যায়নি!", show_alert=True)
            return
        keyboard = [[InlineKeyboardButton("🔗 Task করুন", url=task["url"]), InlineKeyboardButton("✅ Verify", callback_data=f"verify_{tid}")], [InlineKeyboardButton("🔙 Back", callback_data="tasks")]]
        await query.edit_message_text(f"📌 *{task['title']}*\n\n{task.get('description','')}\n\n🪙 Reward: *{task['reward']} coins*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("verify_"):
        from bson import ObjectId
        tid = data[7:]
        completed = user_data.get("completed_tasks", [])
        if tid in completed:
            await query.answer("আগেই সম্পন্ন!", show_alert=True)
            return
        task = tasks.find_one({"_id": ObjectId(tid)})
        if task:
            users.update_one({"user_id": user_id}, {"$inc": {"coins": task["reward"]}, "$push": {"completed_tasks": tid}})
            await query.answer(f"✅ +{task['reward']} coins!", show_alert=True)
            await query.edit_message_text(f"✅ Task সম্পন্ন! *+{task['reward']} coins*!", parse_mode="Markdown", reply_markup=back_btn())

    elif data == "wallet":
        wallet = user_data.get("ton_wallet")
        if wallet:
            await query.edit_message_text(
                f"💎 *TON Wallet*\n\n✅ সংযুক্ত: `{wallet}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 পরিবর্তন করুন", callback_data="change_wallet")], [InlineKeyboardButton("🔙 Back", callback_data="back")]])
            )
        else:
            context.user_data["waiting_for"] = "wallet"
            await query.edit_message_text("💎 *TON Wallet Connect*\n\nআপনার TON wallet address পাঠান:\n(EQ... দিয়ে শুরু)", parse_mode="Markdown", reply_markup=back_btn())

    elif data == "change_wallet":
        context.user_data["waiting_for"] = "wallet"
        await query.edit_message_text("💎 নতুন TON wallet address পাঠান:", reply_markup=back_btn())

    elif data == "withdraw":
        wallet = user_data.get("ton_wallet")
        coins = user_data.get("coins", 0)
        if not wallet:
            await query.edit_message_text("❌ আগে TON wallet connect করুন!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Wallet Connect", callback_data="wallet")], [InlineKeyboardButton("🔙 Back", callback_data="back")]]))
        elif coins < MIN_WITHDRAW:
            await query.edit_message_text(f"❌ Minimum *{MIN_WITHDRAW} coins* লাগবে!\nআপনার: *{coins} coins*\nআরও দরকার: *{MIN_WITHDRAW-coins} coins*", parse_mode="Markdown", reply_markup=back_btn())
        else:
            context.user_data["waiting_for"] = "withdraw_amount"
            await query.edit_message_text(f"💸 *Withdraw*\n\n💰 Available: *{coins} coins*\n💎 Wallet: `{wallet}`\n\nকত coins withdraw করতে চান?", parse_mode="Markdown", reply_markup=back_btn())

    elif data == "back":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        await query.edit_message_text(f"🏠 *Main Menu*\n\n📎 `{ref_link}`", parse_mode="Markdown", reply_markup=main_keyboard())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    if not anti_spam(user.id):
        await update.message.reply_text("⚠️ Spam! অপেক্ষা করুন।")
        return
    waiting = context.user_data.get("waiting_for")
    if waiting == "wallet":
        if (text.startswith("EQ") or text.startswith("UQ")) and len(text) > 30:
            users.update_one({"user_id": user.id}, {"$set": {"ton_wallet": text}})
            context.user_data.pop("waiting_for", None)
            await update.message.reply_text(f"✅ *TON Wallet সংযুক্ত!*\n\n`{text}`", parse_mode="Markdown", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ সঠিক TON address দিন! (EQ... দিয়ে শুরু)")
    elif waiting == "withdraw_amount":
        if text.isdigit():
            amount = int(text)
            user_data = users.find_one({"user_id": user.id})
            coins = user_data.get("coins", 0)
            if amount < MIN_WITHDRAW:
                await update.message.reply_text(f"❌ Minimum {MIN_WITHDRAW} coins!")
            elif amount > coins:
                await update.message.reply_text(f"❌ আপনার কাছে {coins} coins আছে!")
            else:
                wallet = user_data.get("ton_wallet")
                withdrawals.insert_one({"user_id": user.id, "username": user.username or user.first_name, "amount": amount, "wallet": wallet, "status": "pending", "created_at": datetime.utcnow()})
                users.update_one({"user_id": user.id}, {"$inc": {"coins": -amount}})
                context.user_data.pop("waiting_for", None)
                try:
                    await context.bot.send_message(chat_id=ADMIN_ID, text=f"💸 *নতুন Withdraw Request!*\n\n👤 {user.first_name} (@{user.username})\n🆔 `{user.id}`\n💰 *{amount} coins*\n💎 `{wallet}`", parse_mode="Markdown")
                except Exception:
                    pass
                await update.message.reply_text(f"✅ *Withdraw Request পাঠানো হয়েছে!*\n\n💰 {amount} coins\n💎 `{wallet}`\n\nAdmin শীঘ্রই পাঠাবেন! ⏳", parse_mode="Markdown", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ শুধু সংখ্যা লিখুন!")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    all_users = users.find({"is_banned": {"$ne": True}})
    sent = 0
    for u in all_users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=f"📢 *Admin:*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ {sent} জনকে পাঠানো হয়েছে!")

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        args = " ".join(context.args).split("|")
        tasks.insert_one({"title": args[0].strip(), "url": args[1].strip(), "reward": int(args[2].strip()), "description": args[3].strip() if len(args) > 3 else "", "active": True})
        await update.message.reply_text(f"✅ Task যোগ হয়েছে!")
    except Exception:
        await update.message.reply_text("Usage: /addtask Title|URL|Reward|Description")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    uid = int(context.args[0])
    users.update_one({"user_id": uid}, {"$set": {"is_banned": True}})
    await update.message.reply_text(f"✅ User {uid} banned!")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    uid = int(context.args[0])
    users.update_one({"user_id": uid}, {"$set": {"is_banned": False}})
    await update.message.reply_text(f"✅ User {uid} unbanned!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    total = users.count_documents({})
    banned = users.count_documents({"is_banned": True})
    pending_w = withdrawals.count_documents({"status": "pending"})
    await update.message.reply_text(f"📊 *Stats*\n\n👥 Users: *{total}*\n🚫 Banned: *{banned}*\n💸 Pending: *{pending_w}*", parse_mode="Markdown")

async def pending_w(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    pending = list(withdrawals.find({"status": "pending"}).limit(10))
    if not pending:
        await update.message.reply_text("✅ কোনো pending নেই!")
        return
    text = "💸 *Pending Withdrawals:*\n\n"
    for w in pending:
        text += f"🆔 `{w['_id']}`\n👤 {w['username']} ({w['user_id']})\n💰 {w['amount']} coins\n💎 `{w['wallet']}`\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def approve_w(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    from bson import ObjectId
    wid = context.args[0]
    w = withdrawals.find_one({"_id": ObjectId(wid)})
    if not w:
        await update.message.reply_text("❌ পাওয়া যায়নি!")
        return
    withdrawals.update_one({"_id": ObjectId(wid)}, {"$set": {"status": "approved"}})
    try:
        await context.bot.send_message(chat_id=w["user_id"], text=f"✅ *Withdrawal Approved!*\n\n💰 {w['amount']} coins পাঠানো হয়েছে!\n💎 `{w['wallet']}`", parse_mode="Markdown")
    except Exception:
        pass
    await update.message.reply_text("✅ Approved!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("addtask", add_task))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("pending", pending_w))
    app.add_handler(CommandHandler("approve", approve_w))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot চালু হচ্ছে...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
