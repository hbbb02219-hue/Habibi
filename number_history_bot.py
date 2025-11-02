# filename: number_history_bot.py
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message
import motor.motor_asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "12345"))
API_HASH = os.getenv("API_HASH", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())

PHONE_RE = re.compile(r'(\+?\d[\d\s\-]{6,}\d)')

def normalize_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    m = PHONE_RE.search(raw)
    if not m:
        return None
    digits = re.sub(r'\D', '', m.group(1))
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) > 10 and digits.startswith("0"):
        return "+" + digits.lstrip("0")
    if raw.startswith("+"):
        return "+" + digits
    return "+" + digits

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["number_history_db"]
histories = db["histories"]

app = Client("numhist", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

def make_entry(submitter_id: int, submitter_name: str, etype: str, title: str, desc: str, visibility="public"):
    return {
        "id": str(uuid.uuid4()),
        "type": etype,
        "title": title[:200],
        "description": desc[:2000],
        "submitted_by": submitter_id,
        "submitted_name": submitter_name or "",
        "timestamp": datetime.utcnow(),
        "approved": False,
        "visibility": visibility,
    }

@app.on_message(filters.private & filters.command("start"))
async def start(_, msg: Message):
    await msg.reply_text(
        "📌 Number History Bot\n\nCommands:\n"
        "/addhistory <number> | <type> | <description>\n"
        "/history <number>\n"
        "/myuploads\n\n⚠️ All submissions go to moderation."
    )

@app.on_message(filters.private & filters.command("addhistory"))
async def addhistory(_, msg: Message):
    text = msg.text.partition(" ")[2].strip()
    if not text:
        return await msg.reply_text("Usage:\n/addhistory <number> | <type> | <description>")
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        return await msg.reply_text("Provide: number | type | description")

    raw_num, etype, desc = parts[0], parts[1].lower(), parts[2]
    if etype not in ("call","message","note","business","spam-report"):
        return await msg.reply_text("Type must be: call,message,note,business,spam-report")

    phone = normalize_phone(raw_num)
    if not phone:
        return await msg.reply_text("Invalid number!")

    entry = make_entry(msg.from_user.id, msg.from_user.first_name, etype, f"{etype} entry", desc)

    await histories.update_one(
        {"phone": phone},
        {
            "$setOnInsert": {"phone": phone, "created_at": datetime.utcnow()},
            "$push": {"entries": entry},
            "$set": {"last_updated": datetime.utcnow()}
        },
        upsert=True
    )

    await msg.reply_text("✅ Submitted for moderation!")

@app.on_message(filters.command("history"))
async def history(_, msg: Message):
    text = msg.text.partition(" ")[2].strip()
    if not text:
        return await msg.reply_text("Usage: /history <number>")

    phone = normalize_phone(text)
    if not phone:
        return await msg.reply_text("Invalid number")

    doc = await histories.find_one({"phone": phone})
    if not doc:
        return await msg.reply_text("❌ No history found.")

    approved = [e for e in doc["entries"] if e.get("approved")]

    if not approved:
        return await msg.reply_text("No approved public entries found!")

    lines = [f"✅ History for {phone}:\n"]
    for e in approved[:8]:
        t = e["timestamp"].strftime("%Y-%m-%d")
        lines.append(f"• {e['type'].upper()} ({t})\n{e['description']}\n")

    await msg.reply_text("\n".join(lines))

@app.on_message(filters.private & filters.command("myuploads"))
async def myuploads(_, msg: Message):
    uid = msg.from_user.id
    cur = histories.find({"entries.submitted_by": uid})
    out=[]
    async for doc in cur:
        for e in doc["entries"]:
            if e.get("submitted_by")==uid:
                out.append(f"{e['id']} | {doc['phone']} | approved: {e.get('approved')}")
    if not out:
        return await msg.reply_text("No uploads.")
    await msg.reply_text("\n".join(out))

@app.on_message(filters.user(ADMIN_IDS) & filters.command("approve"))
async def approve(_, msg: Message):
    eid = msg.text.partition(" ")[2].strip()
    if not eid:
        return await msg.reply_text("Usage: /approve id")
    res = histories.update_one(
        {"entries.id": eid},
        {"$set": {"entries.$.approved": True, "entries.$.approved_at": datetime.utcnow()}}
    )
    await msg.reply_text(f"✅ Approved {eid}")

if __name__ == "__main__":
    print("Starting bot...")
    app.run()