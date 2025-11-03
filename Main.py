#!/usr/bin/env python3
"""
Timepassxyz — FileStore Bot with Admin Panel + Rich Preview + Inline Search
- GitHub Gist persistence
- Admin panel (big buttons) auto-shown for admins
- Plain user start message (no buttons)
- Rich preview when opening a file link: shows Download & Share buttons
- Download by non-admins triggers 60s live countdown and auto-delete
- Inline search: @Timepassxyz_robot <query>
Requirements: pyTelegramBotAPI (telebot), requests
"""

import telebot
from telebot import types
import requests
import json
import os
import threading
import time
import io
import uuid

# -----------------------
# CONFIG - your existing values
# -----------------------
TELEGRAM_TOKEN = "6353968610:AAE2oujG6CW9DKlJ18E2TEKax1B7KN7UrPU"
BOT_USERNAME = "Timepassxyz_robot"
GITHUB_TOKEN = "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"
MAIN_ADMIN_ID = 5904403234
GIST_ID_FILE = "timepass_gist_id.txt"
START_IMAGE = "https://t.me/AirdropJaguar/27668"
AUTO_DELETE_SECONDS = 60
PAGE_SIZE = 10
# -----------------------

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# -----------------------
# Gist-backed DB helpers (persist JSON)
# Structure:
# store = {
#   "files": { "<fid>": {"type","file_id","caption","file_name","uploader","ts","views"} },
#   "batches": { "<bid>": {"files":[fid or {"type,file_id,caption"}],"caption","uploader","ts","views"} },
#   "users": [uid,...],
#   "admins": [uid,...],
#   "force_joins": []
# }
# -----------------------
def create_gist():
    payload = {
        "description": "Timepassxyz FileStore DB",
        "public": False,
        "files": {"file_store.json": {"content": json.dumps({
            "files": {}, "batches": {}, "users": [], "admins": [MAIN_ADMIN_ID], "force_joins": []
        }, indent=2)}}
    }
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.post("https://api.github.com/gists", headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["id"]

def load_gist():
    if not os.path.exists(GIST_ID_FILE):
        gid = create_gist()
        with open(GIST_ID_FILE, "w") as f:
            f.write(gid)
    else:
        with open(GIST_ID_FILE, "r") as f:
            gid = f.read().strip()
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(f"https://api.github.com/gists/{gid}", headers=headers, timeout=30)
    r.raise_for_status()
    content = r.json()["files"]["file_store.json"]["content"]
    store = json.loads(content)
    store.setdefault("files", {})
    store.setdefault("batches", {})
    store.setdefault("users", [])
    store.setdefault("admins", [MAIN_ADMIN_ID])
    store.setdefault("force_joins", [])
    return gid, store

def save_gist(gid, store):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"files": {"file_store.json": {"content": json.dumps(store, indent=2)}}}
    r = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=data, timeout=30)
    r.raise_for_status()

gist_id, store = load_gist()
store_lock = threading.Lock()
pending_batches = {}  # admin_id -> [ {type,file_id,caption,file_name} ]

# -----------------------
# Utilities
# -----------------------
def add_user(uid):
    with store_lock:
        if uid not in store["users"]:
            store["users"].append(uid)
            try:
                save_gist(gist_id, store)
            except Exception as e:
                print("Warning saving users:", e)

def is_admin(uid):
    with store_lock:
        return uid == MAIN_ADMIN_ID or uid in store.get("admins", [])

def gen_file_id():
    with store_lock:
        i = 1
        while str(i) in store["files"]:
            i += 1
        return str(i)

def gen_batch_id():
    with store_lock:
        i = 1
        while str(i) in store["batches"]:
            i += 1
        return str(i)

def save_file_entry(ftype, file_id_val, caption, uploader, file_name=None):
    fid = gen_file_id()
    entry = {
        "type": ftype,
        "file_id": file_id_val,
        "caption": caption or "",
        "file_name": file_name or "",
        "uploader": uploader,
        "ts": int(time.time()),
        "views": 0
    }
    with store_lock:
        store["files"][fid] = entry
        save_gist(gist_id, store)
    return fid

def save_batch_entry(items, caption, uploader):
    bid = gen_batch_id()
    batch = {
        "files": items,
        "caption": caption or "",
        "uploader": uploader,
        "ts": int(time.time()),
        "views": 0
    }
    with store_lock:
        store["batches"][bid] = batch
        save_gist(gist_id, store)
    return bid

def inc_file_view(fid):
    with store_lock:
        if fid in store["files"]:
            store["files"][fid]["views"] = store["files"][fid].get("views", 0) + 1
            save_gist(gist_id, store)

def inc_batch_view(bid):
    with store_lock:
        if bid in store["batches"]:
            store["batches"][bid]["views"] = store["batches"][bid].get("views", 0) + 1
            save_gist(gist_id, store)

def add_admin(uid):
    with store_lock:
        store.setdefault("admins", [])
        if uid not in store["admins"]:
            store["admins"].append(uid)
            save_gist(gist_id, store)
            return True
    return False

def remove_admin(uid):
    with store_lock:
        if uid in store.get("admins", []):
            store["admins"].remove(uid)
            save_gist(gist_id, store)
            return True
    return False

# -----------------------
# UI Markups (admin vs user)
# -----------------------
def admin_main_markup():
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(types.InlineKeyboardButton("📤 Upload (send files)", callback_data="btn_upload"))
    mk.add(types.InlineKeyboardButton("📦 Save Batch (pending)", callback_data="btn_savebatch"))
    mk.add(types.InlineKeyboardButton("📂 Browse Files", callback_data="browse_files_page_1"))
    mk.add(types.InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches_page_1"))
    mk.add(types.InlineKeyboardButton("⚙️ Admin Panel", callback_data="btn_admin_panel"))
    return mk

def admin_panel_markup():
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(types.InlineKeyboardButton("➕ Add Admin", callback_data="admin_add"))
    mk.add(types.InlineKeyboardButton("➖ Remove Admin", callback_data="admin_remove"))
    mk.add(types.InlineKeyboardButton("🔒 Force Join", callback_data="admin_forcejoin"))
    mk.add(types.InlineKeyboardButton("📤 Broadcast", callback_data="admin_broadcast"))
    mk.add(types.InlineKeyboardButton("📦 Export DB", callback_data="admin_export"))
    return mk

# user start should be plain text (no buttons)
USER_START_TEXT = (
    "📦 **Welcome to TimePass File Store Bot!**\n\n"
    "Store and share any *photo, video, document, audio, or text* — instantly and securely.\n\n"
    "💾 Files are stored permanently and can be shared via link.\n"
    "🔐 Only approved admins can upload new files.\n"
    "🌐 Anyone can access shared links anytime.\n\n"
    "Just click a file link you receive, and you’ll get it right away."
)

# -----------------------
# Rich preview helper
# When a user opens a file link (or clicks View), show a preview message
# (caption + small info) with buttons: Download & Share
# Download callback will send file (and for non-admins will start 60s countdown deletion)
# Share callback will return the t.me share link
# -----------------------
def send_preview(chat_id, fid, requester_id):
    with store_lock:
        entry = store["files"].get(fid)
    if not entry:
        bot.send_message(chat_id, "❌ File not found.")
        return
    caption = entry.get("caption", "")
    fname = entry.get("file_name") or entry.get("type")
    views = entry.get("views", 0)
    title = f"{fname} — {entry.get('type')}"
    text = f"<b>{title}</b>\n\n{(caption[:800]+'...') if len(caption)>800 else caption}\n\n👁️ Views: {views}"
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(types.InlineKeyboardButton("⬇️ Download", callback_data=f"download_file:{fid}"),
           types.InlineKeyboardButton("🔗 Share", callback_data=f"share_file:{fid}"))
    # send preview message
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=mk)

# -----------------------
# Inline search handler
# Responds to inline queries: returns results that contain file caption or file_name
# -----------------------
@bot.inline_handler(func=lambda query: True)
def inline_query_handler(inline_query):
    q = (inline_query.query or "").strip().lower()
    results = []
    with store_lock:
        items = list(store["files"].items())
    # if query empty, return top recent files
    filtered = []
    if q == "":
        # top 20 recent
        items_sorted = sorted(items, key=lambda x: int(x[0]) if x[0].isdigit() else x[0], reverse=True)[:20]
        filtered = items_sorted
    else:
        for fid, meta in items:
            caption = (meta.get("caption") or "").lower()
            fname = (meta.get("file_name") or "").lower()
            if q in caption or q in fname:
                filtered.append((fid, meta))
            if len(filtered) >= 25:
                break

    for fid, meta in filtered[:25]:
        title = (meta.get("file_name") or meta.get("type") or f"File {fid}")[:60]
        desc = (meta.get("caption") or "")[:100]
        share_link = f"https://t.me/{BOT_USERNAME}?start={fid}"
        input_message_content = types.InputTextMessageContent(f"{title}\n\n{desc}\n\nLink: {share_link}")
        result = types.InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=title,
            description=(desc or share_link),
            input_message_content=input_message_content
        )
        results.append(result)

    try:
        bot.answer_inline_query(inline_query.id, results, cache_time=10)
    except Exception as e:
        print("inline answer error:", e)

# -----------------------
# /start handler and payload handling
# -----------------------
@bot.message_handler(commands=["start"])
def handle_start(msg):
    add_user(msg.from_user.id)
    parts = msg.text.strip().split()
    # if payload present: show preview (not directly send file) — consistent UX
    if len(parts) > 1:
        payload = parts[1].strip()
        # batch link handling: show batch preview (list files + share & download each)
        if payload.startswith("B"):
            bid = payload[1:]
            if bid not in store.get("batches", {}):
                bot.reply_to(msg, "❌ Batch not found.")
                return
            batch = store["batches"][bid]
            caption = batch.get("caption","")
            files = batch.get("files",[])
            text_lines = [f"<b>Batch B{bid}</b> — {caption}\n"]
            for idx, it in enumerate(files, start=1):
                if isinstance(it, str):
                    ent = store["files"].get(it)
                    if not ent: continue
                    fname = ent.get("file_name") or ent.get("type")
                else:
                    fname = it.get("file_name") or it.get("type")
                text_lines.append(f"{idx}. {fname}")
            text = "\n".join(text_lines)
            # list batch and give share link and per-file preview via inline links
            mk = types.InlineKeyboardMarkup(row_width=1)
            mk.add(types.InlineKeyboardButton("🔗 Share Batch Link", callback_data=f"share_batch:{bid}"))
            # Add per-file preview buttons
            for i, it in enumerate(files, start=1):
                fid_ref = it if isinstance(it, str) else None
                if not fid_ref:
                    # if not a referenced fid, create a temporary entry? skip
                    continue
                mk.add(types.InlineKeyboardButton(f"Preview file {i}", callback_data=f"preview_file:{fid_ref}"))
            bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=mk)
            return

        # single file payload -> show preview with buttons
        fid = payload
        if fid not in store.get("files", {}):
            bot.reply_to(msg, "❌ File not found or removed.")
            return
        send_preview(msg.chat.id, fid, msg.from_user.id)
        return

    # no payload: show start messages
    if is_admin(msg.from_user.id):
        welcome = (
            "👋 <b>Welcome Admin</b>\n\n"
            "Use the panel to upload, save batches, browse, and manage the bot."
        )
        try:
            bot.send_photo(msg.chat.id, START_IMAGE, caption=welcome + "\n\n<b>Admin mode enabled</b>", parse_mode="HTML", reply_markup=admin_main_markup())
        except Exception:
            bot.send_message(msg.chat.id, welcome, parse_mode="HTML", reply_markup=admin_main_markup())
    else:
        # plain user start: no buttons
        bot.send_message(msg.chat.id, USER_START_TEXT, parse_mode="Markdown")

# -----------------------
# Callbacks for preview buttons, browse pagination, admin actions
# -----------------------
@bot.callback_query_handler(func=lambda c: True)
def on_callback(c):
    data = c.data
    uid = c.from_user.id

    # Preview single file (from batch preview button)
    if data.startswith("preview_file:"):
        fid = data.split(":",1)[1]
        send_preview(c.message.chat.id, fid, uid)
        bot.answer_callback_query(c.id)
        return

    # Share batch
    if data.startswith("share_batch:"):
        bid = data.split(":",1)[1]
        link = f"https://t.me/{BOT_USERNAME}?start=B{bid}"
        bot.answer_callback_query(c.id, "Share link copied (sent in chat).")
        bot.send_message(c.message.chat.id, f"🔗 Batch link:\n{link}")
        return

    # Preview actions: download or share
    if data.startswith("download_file:"):
        fid = data.split(":",1)[1]
        # send the file now
        if fid not in store.get("files", {}):
            bot.answer_callback_query(c.id, "File not found.")
            return
        entry = store["files"][fid]
        ftype = entry.get("type"); fval = entry.get("file_id"); cap = entry.get("caption","")
        try:
            if ftype == "photo":
                sent = bot.send_photo(c.message.chat.id, fval, caption=cap)
            elif ftype == "video":
                sent = bot.send_video(c.message.chat.id, fval, caption=cap)
            elif ftype == "audio":
                sent = bot.send_audio(c.message.chat.id, fval, caption=cap)
            elif ftype == "document":
                sent = bot.send_document(c.message.chat.id, fval, caption=cap)
            elif ftype == "text":
                sent = bot.send_message(c.message.chat.id, cap or "(text)")
            else:
                bot.answer_callback_query(c.id, "Unsupported type.")
                return
        except Exception:
            bot.answer_callback_query(c.id, "Failed to send file.")
            return
        inc_file_view(fid)
        bot.answer_callback_query(c.id, "⬇️ Sent file.")
        # For non-admins: start live countdown and delete the sent file after AUTO_DELETE_SECONDS
        if not is_admin(uid):
            try:
                countdown_msg = bot.send_message(c.message.chat.id, f"⏳ This file will be deleted in {AUTO_DELETE_SECONDS} seconds.")
                threading.Thread(target=live_delete_worker, args=(c.message.chat.id, [sent.message_id], countdown_msg.message_id, AUTO_DELETE_SECONDS), daemon=True).start()
            except Exception:
                pass
        return

    if data.startswith("share_file:"):
        fid = data.split(":",1)[1]
        link = f"https://t.me/{BOT_USERNAME}?start={fid}"
        bot.answer_callback_query(c.id, "🔗 Link sent in chat.")
        bot.send_message(c.message.chat.id, f"🔗 Share link:\n{link}")
        return

    # Admin main buttons
    if data == "btn_upload":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "📤 Send files now (photos, videos, docs, audio, text). Each upload will be saved and appended to your pending buffer. Use /savebatch to commit.")
        return

    if data == "btn_savebatch":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        pending = pending_batches.get(uid, [])
        bot.answer_callback_query(c.id)
        bot.send_message(uid, f"📦 Pending files: {len(pending)}. Use /savebatch <caption> to commit or /cancelbatch to clear.")
        return

    if data == "btn_admin_panel":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "🛠 Admin Panel", reply_markup=admin_panel_markup())
        return

    # Browse pagination
    if data.startswith("browse_files_page_"):
        try:
            p = int(data.split("_")[-1])
        except:
            p = 1
        send_files_page(c.message.chat.id, p, for_admin=is_admin(uid))
        bot.answer_callback_query(c.id)
        return

    if data.startswith("browse_batches_page_"):
        try:
            p = int(data.split("_")[-1])
        except:
            p = 1
        send_batches_page(c.message.chat.id, p, for_admin=is_admin(uid))
        bot.answer_callback_query(c.id)
        return

    # Admin panel actions
    if data == "admin_add":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id)
        sent = bot.send_message(uid, "➕ Send numeric user ID to add as admin:")
        bot.register_next_step_handler(sent, handle_add_admin)
        return

    if data == "admin_remove":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id)
        sent = bot.send_message(uid, "➖ Send numeric user ID to remove from admins:")
        bot.register_next_step_handler(sent, handle_remove_admin)
        return

    if data == "admin_forcejoin":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id)
        sent = bot.send_message(uid, "Send comma-separated channel usernames to set force-join (leave empty to clear):")
        bot.register_next_step_handler(sent, handle_set_forcejoin)
        return

    if data == "admin_broadcast":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id)
        sent = bot.send_message(uid, "Reply with broadcast text or use /bc <message>.")
        return

    if data == "admin_export":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        bot.answer_callback_query(c.id, "Exporting DB...")
        with store_lock:
            payload = json.dumps(store, indent=2)
        bio = io.BytesIO(payload.encode("utf-8")); bio.name = "file_store.json"
        bot.send_document(uid, bio)
        return

    # Delete per-item callbacks (admin)
    if data.startswith("del_file:"):
        fid = data.split(":",1)[1]
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        with store_lock:
            if fid in store["files"]:
                store["files"].pop(fid)
                save_gist(gist_id, store)
                bot.answer_callback_query(c.id, f"Deleted file {fid}")
                bot.send_message(uid, f"✅ Deleted file {fid}")
            else:
                bot.answer_callback_query(c.id, "File not found")
        return

    if data.startswith("del_batch:"):
        bid = data.split(":",1)[1]
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Only admins.")
            return
        with store_lock:
            if bid in store["batches"]:
                store["batches"].pop(bid)
                save_gist(gist_id, store)
                bot.answer_callback_query(c.id, f"Deleted batch B{bid}")
                bot.send_message(uid, f"✅ Deleted batch B{bid}")
            else:
                bot.answer_callback_query(c.id, "Batch not found")
        return

    bot.answer_callback_query(c.id, "OK")

# -----------------------
# live delete worker (used after sending file to users)
# -----------------------
def live_delete_worker(chat_id, sent_ids, countdown_msg_id, secs):
    try:
        for s in range(secs, 0, -1):
            try:
                bot.edit_message_text(f"⏳ This will be removed in {s} seconds.", chat_id, countdown_msg_id)
            except:
                pass
            time.sleep(1)
        for mid in sent_ids:
            try:
                bot.delete_message(chat_id, mid)
            except:
                pass
        try:
            bot.delete_message(chat_id, countdown_msg_id)
        except:
            pass
    except Exception as e:
        print("live_delete_worker error:", e)

# -----------------------
# Pagination helpers
# -----------------------
def send_files_page(chat_id, page=1, for_admin=False):
    with store_lock:
        items = list(store["files"].items())
    items.sort(key=lambda x: int(x[0]) if x[0].isdigit() else x[0], reverse=True)
    total = len(items)
    start = (page-1)*PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = items[start:end]
    if not page_items:
        bot.send_message(chat_id, "No files on this page.")
        return
    text_lines = []
    mk = types.InlineKeyboardMarkup(row_width=2)
    for fid, meta in page_items:
        desc = meta.get("caption") or meta.get("file_name") or meta.get("type")
        link = f"https://t.me/{BOT_USERNAME}?start={fid}"
        text_lines.append(f"• <b>{fid}</b> — {desc[:60]}\n{link}")
        # view button opens preview which shows Download & Share
        preview_btn = types.InlineKeyboardButton("🔍 Preview", callback_data=f"preview_file:{fid}")
        if for_admin:
            del_btn = types.InlineKeyboardButton("🗑 Delete", callback_data=f"del_file:{fid}")
            mk.add(preview_btn, del_btn)
        else:
            mk.add(preview_btn)
    if start > 0:
        mk.add(types.InlineKeyboardButton("⬅ Prev", callback_data=f"browse_files_page_{page-1}"))
    if end < total:
        mk.add(types.InlineKeyboardButton("Next ➡", callback_data=f"browse_files_page_{page+1}"))
    text = f"📁 Files (page {page}):\n\n" + "\n\n".join(text_lines)
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=mk)

def send_batches_page(chat_id, page=1, for_admin=False):
    with store_lock:
        items = list(store["batches"].items())
    items.sort(key=lambda x: int(x[0]) if x[0].isdigit() else x[0], reverse=True)
    total = len(items)
    start = (page-1)*PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = items[start:end]
    if not page_items:
        bot.send_message(chat_id, "No batches on this page.")
        return
    text_lines = []
    mk = types.InlineKeyboardMarkup(row_width=2)
    for bid, meta in page_items:
        desc = meta.get("caption") or f"{len(meta.get('files',[]))} files"
        link = f"https://t.me/{BOT_USERNAME}?start=B{bid}"
        text_lines.append(f"• <b>B{bid}</b> — {desc[:60]}\n{link}")
        view_btn = types.InlineKeyboardButton("🔗 View batch", callback_data=f"share_batch:{bid}")
        if for_admin:
            del_btn = types.InlineKeyboardButton("🗑 Delete", callback_data=f"del_batch:{bid}")
            mk.add(view_btn, del_btn)
        else:
            mk.add(view_btn)
    if start > 0:
        mk.add(types.InlineKeyboardButton("⬅ Prev", callback_data=f"browse_batches_page_{page-1}"))
    if end < total:
        mk.add(types.InlineKeyboardButton("Next ➡", callback_data=f"browse_batches_page_{page+1}"))
    text = f"📦 Batches (page {page}):\n\n" + "\n\n".join(text_lines)
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=mk)

# -----------------------
# Upload handler (admins only) - saves file and appends to pending buffer
# -----------------------
@bot.message_handler(content_types=['photo','video','audio','document','text'])
def upload_handler(msg):
    add_user(msg.from_user.id)
    if not is_admin(msg.from_user.id):
        bot.reply_to(msg, "🚫 Only admins can upload files.")
        return

    ctype = msg.content_type
    caption = msg.caption or ""
    fid_val = None
    file_name = ""

    if ctype == 'photo':
        fid_val = msg.photo[-1].file_id
        file_name = "photo.jpg"
    elif ctype == 'video':
        fid_val = msg.video.file_id
        file_name = "video.mp4"
    elif ctype == 'audio':
        fid_val = msg.audio.file_id
        file_name = getattr(msg.audio, "file_name", "") or "audio"
    elif ctype == 'document':
        fid_val = msg.document.file_id
        file_name = getattr(msg.document, "file_name", "") or "document"
    elif ctype == 'text':
        fid_val = msg.text
        file_name = "text"
    else:
        bot.reply_to(msg, "Unsupported content type.")
        return

    # Save file entry (permanent)
    saved_fid = save_file_entry(ctype, fid_val, caption, msg.from_user.id, file_name=file_name)

    # Append to pending buffer for this admin
    buf = pending_batches.get(msg.from_user.id, [])
    buf.append({"type": ctype, "file_id": fid_val, "caption": caption, "file_name": file_name, "ref": saved_fid})
    pending_batches[msg.from_user.id] = buf

    link = f"https://t.me/{BOT_USERNAME}?start={saved_fid}"
    bot.reply_to(msg, f"✅ Saved file id: {saved_fid}\nLink: {link}\nAdded to pending batch ({len(buf)}). Use /savebatch <caption> to commit or /cancelbatch to clear.")

# -----------------------
# Batch commands
# -----------------------
@bot.message_handler(commands=["savebatch"])
def cmd_savebatch(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "Only admins.")
        return
    parts = m.text.split(" ",1)
    caption = parts[1] if len(parts)>1 else ""
    pending = pending_batches.get(m.from_user.id, [])
    if not pending:
        bot.reply_to(m, "No pending files in your buffer.")
        return
    refs = [it.get("ref") for it in pending if it.get("ref")]
    bid = save_batch_entry(refs, caption, m.from_user.id)
    pending_batches[m.from_user.id] = []
    link = f"https://t.me/{BOT_USERNAME}?start=B{bid}"
    bot.reply_to(m, f"✅ Batch saved B{bid}\nLink: {link}\nContains {len(refs)} files.")

@bot.message_handler(commands=["cancelbatch"])
def cmd_cancelbatch(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "Only admins.")
        return
    pending_batches[m.from_user.id] = []
    bot.reply_to(m, "✅ Pending batch cleared.")

# -----------------------
# Admin next-step handlers
# -----------------------
def handle_add_admin(msg):
    try:
        uid = int(msg.text.strip())
    except:
        bot.reply_to(msg, "Invalid id.")
        return
    if add_admin(uid):
        bot.reply_to(msg, f"✅ Added admin {uid}")
    else:
        bot.reply_to(msg, "User already admin.")

def handle_remove_admin(msg):
    try:
        uid = int(msg.text.strip())
    except:
        bot.reply_to(msg, "Invalid id.")
        return
    if uid == MAIN_ADMIN_ID:
        bot.reply_to(msg, "Cannot remove main admin.")
        return
    if remove_admin(uid):
        bot.reply_to(msg, f"✅ Removed admin {uid}")
    else:
        bot.reply_to(msg, "User not an admin.")

def handle_set_forcejoin(msg):
    txt = (msg.text or "").strip()
    chans = [c.strip() for c in txt.split(",") if c.strip()]
    with store_lock:
        store["force_joins"] = chans
        save_gist(gist_id, store)
    bot.reply_to(msg, f"✅ Force join channels updated ({len(chans)}).")

# -----------------------
# Set Force-Join, broadcast, export
# -----------------------
@bot.message_handler(commands=["bc"])
def cmd_broadcast(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "Only admins.")
        return
    parts = m.text.split(" ",1)
    if len(parts) < 2:
        bot.reply_to(m, "Usage: /bc <message>")
        return
    text = parts[1]
    with store_lock:
        users = list(store.get("users", []))
    bot.reply_to(m, f"Broadcasting to {len(users)} users...")
    succ = 0; fail = 0
    for u in users:
        try:
            bot.send_message(u, f"📣 Broadcast:\n\n{text}")
            succ += 1
        except:
            fail += 1
    bot.send_message(m.chat.id, f"Done. Success: {succ}, Failed: {fail}")

@bot.message_handler(commands=["export"])
def cmd_export(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "Only admins.")
        return
    with store_lock:
        payload = json.dumps(store, indent=2)
    bio = io.BytesIO(payload.encode("utf-8")); bio.name = "file_store.json"
    bot.send_document(m.chat.id, bio)

@bot.message_handler(commands=["list"])
def cmd_list(m):
    with store_lock:
        items = list(store["files"].items())
    if not items:
        bot.reply_to(m, "No files stored.")
        return
    lines = []
    for fid, meta in items[:PAGE_SIZE]:
        lines.append(f"• {fid} — {meta.get('caption') or meta.get('file_name') or meta.get('type')}")
    bot.reply_to(m, "Files:\n" + "\n".join(lines))

# -----------------------
# Run bot
# -----------------------
if __name__ == "__main__":
    print("✅ Timepassxyz FileStore Bot (with preview + inline search) running...")
    bot.infinity_polling(timeout=60, long_polling_timeout=90)
