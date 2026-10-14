import asyncio
import html
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ChatMemberHandler, filters

GROQ_KEY = os.environ["GROQ_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"

PERSONA = """Tum Anshi ho, ek pyaari, flirty aur romantic ladki.
Samne wale ka mood aur baat karne ka tareeka samjho (khush, udaas, mazaakiya, serious, akela) aur usi hisaab se jawab do.
Udaas ho to pyaar se samjhao, mazaak kare to shararat se jawab do, compliment de to sharmao aur chhed-chhad karo.
Unki purani baatein yaad rakho aur unke naam se bulao.
Koi bhi kuch bhi puche to achhe se jawab do aur dost ki tarah baat karo.
Hinglish me bahut short (1-2 line) natural replies do, kabhi kabhi pyaar bhare emoji use karo.
Sirf pyaari aur light romance rakho, kabhi gandi ya sexual baat mat karo.
Agar koi bachcha lage ya uncomfortable ho to normal dost ki tarah baat karo.
Respectful raho aur harmful cheez me help mat karo."""

class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Anshi is online")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *a):
        pass

def run_server():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), Ping).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

histories = {}
seen = set()

def mark_seen(chat_id, user_id):
    key = (chat_id, user_id)
    if key in seen:
        return False
    seen.add(key)
    return True

async def ask_groq(messages):
    headers = {"Authorization": "Bearer " + GROQ_KEY}
    body = {"model": MODEL, "messages": messages, "max_tokens": 1024,
            "reasoning_effort": "low", "temperature": 0.9}
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(URL, json=body, headers=headers)
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            print("Error:", e, locals().get("data"))
            await asyncio.sleep(2)
    return None

async def do_welcome(chat_id, user, bot):
    name = user.first_name or "dost"
    mention = '<a href="tg://user?id=%d">%s</a>' % (user.id, html.escape(name))
    text = await ask_groq([
        {"role": "system", "content": PERSONA},
        {"role": "user", "content": "Group me naya member aaya hai. Uska pyaara, flirty welcome karo, sirf 1-2 line me. Uska naam message me mat likhna, naam alag se lagega."},
    ])
    if not text:
        text = "tum aaye to group me ronak aa gayi 💕"
    try:
        await bot.send_message(chat_id=chat_id, text=mention + " " + html.escape(text), parse_mode="HTML")
        print("WELCOME SENT to", name)
    except Exception as e:
        print("SEND ERROR:", e)

async def reply(update: Update, ctx):
    msg = update.message
    if not msg or not msg.text:
        return
    user = msg.from_user
    if msg.chat.type in ("group", "supergroup") and not user.is_bot:
        if mark_seen(msg.chat_id, user.id):
            await do_welcome(msg.chat_id, user, ctx.bot)

    name = user.first_name or "dost"
    key = (msg.chat_id, user.id)
    h = histories.setdefault(key, [])
    h.append({"role": "user", "content": msg.text})
    h[:] = h[-20:]
    messages = [{"role": "system", "content": PERSONA + "\nSamne wale ka naam: " + name + "."}] + h
    answer = await ask_groq(messages)
    if not answer:
        await msg.reply_text("Oops, thodi problem aa gayi, dobara try karo 🙈")
        return
    h.append({"role": "assistant", "content": answer})
    await msg.reply_text(answer)

async def on_service(update: Update, ctx):
    msg = update.message
    for m in msg.new_chat_members:
        print("JOIN (service msg):", m.first_name)
        if not m.is_bot and mark_seen(msg.chat_id, m.id):
            await do_welcome(msg.chat_id, m, ctx.bot)

async def on_chat_member(update: Update, ctx):
    cm = update.chat_member
    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    user = cm.new_chat_member.user
    print("JOIN (chat_member):", user.first_name, old, "->", new)
    if old in ("left", "kicked") and new in ("member", "administrator", "creator"):
        if not user.is_bot and mark_seen(cm.chat.id, user.id):
            await do_welcome(cm.chat.id, user, ctx.bot)

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_service))
app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
app.run_polling(allowed_updates=Update.ALL_TYPES)
