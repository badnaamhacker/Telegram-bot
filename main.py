import asyncio
import logging
import sqlite3
import time
import secrets
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = "8127637308:AAGUUn1TcOjVrTSJVaOH4VtSRJCXo0-j5Bo"
OWNER_ID = 5156942271
FORCE_JOIN_CHANNEL_ID = -1002525453355   # 0 rakhoge to force-join off
FORCE_JOIN_LINK = "https://t.me/PresentMovie/17"
AUTO_DELETE_SECONDS = 1800  # 30 min

# ================= LOG =================
logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)""")
cur.execute("""CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY)""")
cur.execute("""
CREATE TABLE IF NOT EXISTS files (
    file_key TEXT PRIMARY KEY,
    file_id TEXT,
    file_type TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS bundles (
    bundle_key TEXT PRIMARY KEY,
    file_keys TEXT
)
""")
db.commit()

# ================= HELPERS =================
def gen_key(prefix):
    return prefix + secrets.token_urlsafe(6)

def save_file(file_id, file_type):
    key = gen_key("FILE_")
    cur.execute(
        "INSERT INTO files VALUES (?,?,?)",
        (key, file_id, file_type)
    )
    db.commit()
    return key

def save_bundle(keys):
    key = gen_key("BUNDLE_")
    cur.execute(
        "INSERT INTO bundles VALUES (?,?)",
        (key, ",".join(keys))
    )
    db.commit()
    return key

async def force_join_check(user_id, bot):
    if FORCE_JOIN_CHANNEL_ID == 0:
        return True
    try:
        member = await bot.get_chat_member(FORCE_JOIN_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

async def auto_delete(bot, chat_id, msg_id):
    await asyncio.sleep(AUTO_DELETE_SECONDS)
    try:
        await bot.delete_message(chat_id, msg_id)
    except:
        pass

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cur.execute("INSERT OR IGNORE INTO users VALUES (?)", (user.id,))
    db.commit()

    if not context.args:
        await update.message.reply_text("👋 Bot ready. Group me upload the file.")
        return

    key = context.args[0]

    if not await force_join_check(user.id, context.bot):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Join Channel", url=FORCE_JOIN_LINK)],
            [InlineKeyboardButton("🔄 Retry", callback_data=f"retry|{key}")]
        ])
        await update.message.reply_text(
            "❌ Pehle channel join karo",
            reply_markup=kb
        )
        return

    await deliver(update, context, key)

# ================= DELIVERY =================
async def deliver(update, context, key):
    chat_id = update.effective_chat.id

    cur.execute("SELECT file_id, file_type FROM files WHERE file_key=?", (key,))
    row = cur.fetchone()
    if row:
        fid, ftype = row
        msg = await send_file(context, chat_id, fid, ftype)
        asyncio.create_task(auto_delete(context.bot, chat_id, msg.message_id))
        return

    cur.execute("SELECT file_keys FROM bundles WHERE bundle_key=?", (key,))
    row = cur.fetchone()
    if row:
        keys = row[0].split(",")
        for k in keys:
            await deliver(update, context, k)
            await asyncio.sleep(0.4)
        return

    await context.bot.send_message(chat_id, "❌ Invalid / expired link")

async def send_file(context, chat_id, fid, ftype):
    if ftype == "photo":
        return await context.bot.send_photo(chat_id, fid)
    if ftype == "video":
        return await context.bot.send_video(chat_id, fid)
    if ftype == "audio":
        return await context.bot.send_audio(chat_id, fid)
    return await context.bot.send_document(chat_id, fid)

# ================= GROUP FILE HANDLER =================
BUFFER = {}

async def handle_group_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    user_id = update.effective_user.id

    if chat.type == "private":
        return

    cur.execute("INSERT OR IGNORE INTO groups VALUES (?)", (chat.id,))
    db.commit()

    if msg.document:
        ftype, fid = "document", msg.document.file_id
    elif msg.video:
        ftype, fid = "video", msg.video.file_id
    elif msg.audio:
        ftype, fid = "audio", msg.audio.file_id
    elif msg.photo:
        ftype, fid = "photo", msg.photo[-1].file_id
    else:
        return

    key = (chat.id, user_id)
    BUFFER.setdefault(key, []).append((fid, ftype))

    await asyncio.sleep(2)

    if key not in BUFFER:
        return

    files = BUFFER.pop(key)

    botname = context.bot.username

    # ✅ SINGLE FILE (FIXED)
    if len(files) == 1:
        fid, ftype = files[0]
        fkey = save_file(fid, ftype)
        link = f"https://t.me/{botname}?start={fkey}"
        await msg.reply_text(f"🔗 File Link:\n{link}")
        return

    # ✅ MULTIPLE FILES
    keys = [save_file(f[0], f[1]) for f in files]
    bundle_key = save_bundle(keys)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Single Link", callback_data=f"bundle|{bundle_key}")],
        [InlineKeyboardButton("🔗 Separate Links", callback_data=f"multi|{bundle_key}")]
    ])
    await msg.reply_text("📂 Multiple files detected", reply_markup=kb)

# ================= CALLBACK =================
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, key = q.data.split("|")

    botname = context.bot.username

    if action == "retry":
        await q.message.delete()
        await deliver(update, context, key)

    elif action == "bundle":
        link = f"https://t.me/{botname}?start={key}"
        await q.edit_message_text(f"📦 Bundle Link:\n{link}")

    elif action == "multi":
        cur.execute("SELECT file_keys FROM bundles WHERE bundle_key=?", (key,))
        keys = cur.fetchone()[0].split(",")
        text = ""
        for i, k in enumerate(keys, 1):
            text += f"{i}. https://t.me/{botname}?start={k}\n"
        await q.edit_message_text(text)

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")]
    ])
    await update.message.reply_text("🛠 Admin Panel", reply_markup=kb)

async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if update.effective_user.id != OWNER_ID:
        return

    if q.data == "stats":
        u = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        g = cur.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
        f = cur.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        await q.edit_message_text(
            f"📊 Stats\nUsers: {u}\nGroups: {g}\nFiles: {f}"
        )

    elif q.data == "broadcast":
        context.user_data["bc"] = True
        await q.edit_message_text("📢 Send message to broadcast")

async def broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.user_data.get("bc"):
        return

    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()

    for (uid,) in users:
        try:
            await update.message.copy(uid)
            await asyncio.sleep(0.05)
        except:
            pass

    context.user_data["bc"] = False
    await update.message.reply_text("✅ Broadcast sent")

# ================= RUN =================
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CallbackQueryHandler(admin_cb, pattern="^(stats|broadcast)$"))
app.add_handler(CallbackQueryHandler(callback))
app.add_handler(MessageHandler(filters.ChatType.GROUPS & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO), handle_group_files))
app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, broadcast_msg))

app.run_polling()