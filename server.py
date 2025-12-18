import os
import time
import asyncio
from typing import Dict, Any, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN не задан.\n"
        "Запусти так:\n"
        "  export BOT_TOKEN='123:ABC...'\n"
        "  python server.py\n"
    )

# =========================
# IN-MEMORY STORAGE (MVP)
# =========================
USERS: Dict[int, Dict[str, Any]] = {}        # user_id -> {name, username
LOCATIONS: Dict[int, Dict[str, Any]] = {}    # user_id -> {lat, lon, updated_at, is_live}
FRIENDS: Dict[int, set[int]] = {}            # user_id -> set(friend_id)
INVITES: Dict[str, int] = {}                 # code -> owner_id

def now_ts() -> int:
    return int(time.time())

def add_friend(a: int, b: int):
    FRIENDS.setdefault(a, set()).add(b)
    FRIENDS.setdefault(b, set()).add(a)

# =========================
# WEB (FastAPI)
# =========================
app = FastAPI(title="TG Zenly Simple")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def index():
    with open("webapp.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/me")
def api_me(user_id: int):
    u = USERS.get(user_id, {"id": user_id, "name": "Unknown", "username": None})
    return {"id": user_id, "name": u.get("name"), "username": u.get("username")}

@app.get("/api/friends")
def api_friends(user_id: int):
    return {"friends": sorted(list(FRIENDS.get(user_id, set())))}

@app.get("/api/friends-locations")
def api_friends_locations(user_id: int):
    friend_ids = FRIENDS.get(user_id, set())
    res = []
    for fid in friend_ids:
        loc = LOCATIONS.get(fid)
        if not loc:
            continue
        res.append({
            "user_id": fid,
            "lat": loc["lat"],
            "lon": loc["lon"],
            "updated_at": loc["updated_at"],
            "is_live": loc.get("is_live", False),
        })
    return res

@app.post("/api/invite")
def api_invite(user_id: int):
    import secrets
    code = secrets.token_urlsafe(8)
    INVITES[code] = user_id
    return {"code": code}

@app.post("/api/accept")
def api_accept(user_id: int, code: str):
    owner = INVITES.get(code)
    if not owner or owner == user_id:
        return JSONResponse({"ok": False}, status_code=400)
    add_friend(owner, user_id)
    return {"ok": True}

# =========================
# BOT (aiogram)
# =========================
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🗺 Открыть карту (на ПК)")],
        [KeyboardButton(text="📍 Отправить LIVE-локацию")],
    ],
    resize_keyboard=True,
)

@dp.message(CommandStart())
async def start(m: Message):
    USERS[m.from_user.id] = {
        "id": m.from_user.id,
        "name": (m.from_user.full_name or "User"),
        "username": m.from_user.username,
    }
    await m.answer(
        "✅ Mini-Zenly (очень простой MVP)\n\n"
        "1) Нажми «📍 Отправить LIVE-локацию» и отправь геопозицию (лучше Live).\n"
        "2) Нажми «🗺 Открыть карту (на ПК)» и открой ссылку на компьютере.\n\n"
        "Друзья добавляются по инвайт-коду (в вебке).",
        reply_markup=kb
    )

@dp.message(F.text == "📍 Отправить LIVE-локацию")
async def howto(m: Message):
    await m.answer(
        "В Telegram: 📎 → Геопозиция → «Делиться геопозицией» (Live) → отправь сюда.\n"
        "Я буду сохранять последнюю точку."
    )

@dp.message(F.text == "🗺 Открыть карту (на ПК)")
async def open_map(m: Message):
    # localhost откроется только на том же устройстве.
    await m.answer(
        "Открой на компьютере:\n"
        f"http://localhost:{PORT}/\n\n"
        f"И добавь параметр ?user_id={m.from_user.id}\n"
        f"Например:\n"
        f"http://localhost:{PORT}/?user_id={m.from_user.id}"
    )

@dp.message(F.location)
async def got_location(m: Message):
    loc = m.location
    USERS.setdefault(m.from_user.id, {
        "id": m.from_user.id,
        "name": (m.from_user.full_name or "User"),
        "username": m.from_user.username,
    })
    LOCATIONS[m.from_user.id] = {
        "lat": loc.latitude,
        "lon": loc.longitude,
        "updated_at": now_ts(),
        "is_live": bool(getattr(loc, "live_period", None)),
    }
    await m.answer("✅ Локация обновлена.")

# =========================
# RUN BOTH: FastAPI + Bot polling
# =========================
async def run_bot():
    await dp.start_polling(bot)

async def run_api():
    import uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(run_api(), run_bot())

if __name__ == "__main__":
    asyncio.run(main())
