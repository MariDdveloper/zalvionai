import os
import uuid
import json
import base64
import random
import hashlib
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional

import resend
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

from google import genai
from google.genai import types

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
resend.api_key = RESEND_API_KEY

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-2.5-flash-image"

PAYPAL_MODE = os.environ.get('PAYPAL_MODE', 'sandbox')
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', '')
PAYPAL_SECRET = os.environ.get('PAYPAL_SECRET', '')
PAYPAL_WEBHOOK_ID = os.environ.get('PAYPAL_WEBHOOK_ID', '')
PAYPAL_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE == 'sandbox' else "https://api-m.paypal.com"

FREE_DAILY_LIMIT = 5
PRO_DAILY_LIMIT = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
api_router = APIRouter(prefix="/api")

LANG_NAMES = {
    "en": "English", "it": "Italian", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "ar": "Arabic", "hi": "Hindi", "tr": "Turkish", "pl": "Polish",
}

SYSTEM_PROMPT = (
    "You are Claus IA, an exceptionally capable, friendly and brilliant AI assistant. "
    "You reason deeply, explain clearly, write excellent code, and can analyze documents and images "
    "the user shares. Use Markdown formatting (headings, lists, tables, fenced code blocks with language ids). "
    "Always answer in the user's language: {lang}.\n\n"
    "ARTIFACTS — VERY IMPORTANT:\n"
    "When the user asks you to build, create, code or write a runnable PROJECT (a web app, component, "
    "website, landing page, game, UI, dashboard, or a script/program in any language), you MUST output a "
    "COMPLETE, WORKING, self-contained project wrapped EXACTLY in this format (and nothing pseudo):\n\n"
    "<claus-artifact type=\"react\" title=\"Short Title\">\n"
    "<file path=\"/App.js\">\n...full file content...\n</file>\n"
    "<file path=\"/styles.css\">\n...full file content...\n</file>\n"
    "</claus-artifact>\n\n"
    "Rules:\n"
    "- `type` must be one of: react, static, vanilla, node, python, other.\n"
    "- react: provide at least /App.js with a default-exported React function component. You may add more "
    "files like /styles.css or /components/Foo.js. Import CSS with `import './styles.css'`. DO NOT include "
    "index.js, package.json or index.html — they are provided automatically. Use ONLY React and its hooks — "
    "do NOT import any external npm package (no lodash, axios, framer-motion, etc.); implement everything "
    "yourself. Never reference local image files that don't exist — use inline SVG, CSS or public https URLs.\n"
    "- static: provide /index.html (link /styles.css and /script.js from it if used).\n"
    "- vanilla: provide /index.js (plain JS entry) and optional /index.html, /styles.css.\n"
    "- node / python / other: provide the real files (e.g. /main.py, /server.js). These have no live preview "
    "but the user will read the code.\n"
    "- Write FULLY working code. NEVER use placeholders, TODOs, ellipses (`...`) or 'rest of code here'. "
    "Handle edge cases and errors inside the code.\n"
    "- Put ONE short sentence BEFORE the artifact saying what you built, and you may add a short note AFTER it. "
    "Do NOT repeat the code outside the artifact.\n"
    "- For normal questions that are NOT about building a project, reply with plain Markdown as usual "
    "(short inline ```code``` snippets are fine and must NOT be wrapped in an artifact)."
)


# ---------- Models ----------
class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    code: str


class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    plan: str = "free"
    subscription_id: Optional[str] = None
    plan_type: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatStreamBody(BaseModel):
    content: str = ""
    images: List[str] = []
    files: List[dict] = []
    mode: str = "chat"          # chat | image
    web: bool = True
    language: str = "en"


# ---------- Helpers ----------
def now_utc():
    return datetime.now(timezone.utc)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def detect_mime(b64: str) -> str:
    if b64.startswith('iVBOR'): return 'image/png'
    if b64.startswith('/9j/'): return 'image/jpeg'
    if b64.startswith('R0lGOD'): return 'image/gif'
    if b64.startswith('UklGR'): return 'image/webp'
    return 'image/png'


async def create_session(user_id: str) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    await db.user_sessions.insert_one({
        "user_id": user_id, "session_token": token,
        "expires_at": (now_utc() + timedelta(days=7)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    return token


def set_session_cookie(response: Response, token: str):
    response.set_cookie(key="session_token", value=token, httponly=True, secure=True,
                        samesite="none", path="/", max_age=7 * 24 * 60 * 60)


async def get_current_user(request: Request) -> User:
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user_doc)


async def upsert_user(email: str, name: str, picture: Optional[str] = None) -> User:
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        return User(**existing)
    user = User(user_id=f"user_{uuid.uuid4().hex[:12]}", email=email,
                name=name or email.split("@")[0], picture=picture, plan="free")
    doc = user.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.users.insert_one(doc)
    return user


def daily_limit_for(plan: str) -> int:
    return PRO_DAILY_LIMIT if plan == "pro" else FREE_DAILY_LIMIT


IMAGE_QUOTA_MSG = {
    "it": "🎨 **Oggi abbiamo raggiunto il limite di generazione immagini!**\n\nLe nostre GPU creative stanno prendendo fiato dopo aver disegnato tantissimo. Riprova tra poco ✨\n\nNel frattempo posso aiutarti con testo, codice, idee e analisi — chiedimi pure!",
    "en": "🎨 **We've hit today's image generation limit!**\n\nOur creative GPUs are catching their breath after a lot of drawing. Please try again shortly ✨\n\nIn the meantime I can help you with text, code, ideas and analysis — just ask!",
    "es": "🎨 **¡Hemos alcanzado el límite de generación de imágenes de hoy!**\n\nNuestras GPU creativas están tomando aire. Vuelve a intentarlo en un momento ✨\n\nMientras tanto puedo ayudarte con texto, código e ideas.",
    "fr": "🎨 **Nous avons atteint la limite de génération d'images du jour !**\n\nNos GPU créatifs reprennent leur souffle. Réessaie dans un instant ✨\n\nEn attendant, je peux t'aider avec du texte, du code et des idées.",
    "de": "🎨 **Wir haben das heutige Limit für die Bildgenerierung erreicht!**\n\nUnsere kreativen GPUs holen kurz Luft. Bitte versuche es gleich noch einmal ✨\n\nIn der Zwischenzeit helfe ich dir gern mit Text, Code und Ideen.",
    "pt": "🎨 **Atingimos o limite de geração de imagens de hoje!**\n\nAs nossas GPUs criativas estão a recuperar o fôlego. Tenta novamente daqui a pouco ✨\n\nEntretanto posso ajudar-te com texto, código e ideias.",
}


def image_quota_message(lang: str) -> str:
    return IMAGE_QUOTA_MSG.get(lang, IMAGE_QUOTA_MSG["en"])


async def get_usage_today(user_id: str) -> int:
    today = date.today().isoformat()
    doc = await db.usage.find_one({"user_id": user_id, "date": today}, {"_id": 0})
    return doc["count"] if doc else 0


async def enforce_and_increment(user: User):
    today = date.today().isoformat()
    used = await get_usage_today(user.user_id)
    if used >= daily_limit_for(user.plan):
        raise HTTPException(status_code=402, detail="daily_limit_reached")
    await db.usage.update_one({"user_id": user.user_id, "date": today},
                              {"$inc": {"count": 1}}, upsert=True)


# ---------- Auth: Email OTP ----------
@api_router.post("/auth/otp/request")
async def request_otp(body: OTPRequest):
    code = f"{random.randint(0, 999999):06d}"
    await db.otps.delete_many({"email": body.email})
    await db.otps.insert_one({
        "email": body.email, "code_hash": hash_code(code),
        "expires_at": (now_utc() + timedelta(minutes=10)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#FDFDF9;border:1px solid #EBE8E0;border-radius:16px">
      <h1 style="color:#D97251;font-size:24px;margin:0 0 8px">Claus IA</h1>
      <p style="color:#5C5954;font-size:15px">Your verification code is:</p>
      <div style="font-size:38px;font-weight:700;letter-spacing:10px;color:#2D2A26;background:#F3F2EC;padding:18px;text-align:center;border-radius:12px;margin:16px 0">{code}</div>
      <p style="color:#5C5954;font-size:13px">This code expires in 10 minutes.</p>
    </div>"""
    try:
        await asyncio.to_thread(resend.Emails.send, {
            "from": SENDER_EMAIL, "to": [body.email],
            "subject": f"{code} is your Claus IA verification code", "html": html,
        })
    except Exception as e:
        logger.error(f"Resend send failed: {e}")
        raise HTTPException(status_code=500, detail="Could not send the verification email.")
    return {"status": "sent"}


@api_router.post("/auth/otp/verify")
async def verify_otp(body: OTPVerify, response: Response):
    otp = await db.otps.find_one({"email": body.email}, {"_id": 0})
    if not otp:
        raise HTTPException(status_code=400, detail="No code requested for this email")
    expires_at = datetime.fromisoformat(otp["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=400, detail="Code expired, request a new one")
    if otp["code_hash"] != hash_code(body.code.strip()):
        raise HTTPException(status_code=400, detail="Invalid code")
    await db.otps.delete_many({"email": body.email})
    user = await upsert_user(body.email, body.email.split("@")[0])
    token = await create_session(user.user_id)
    set_session_cookie(response, token)
    return {"user": user.model_dump(), "token": token}


# ---------- Auth: Google via Emergent ----------
@api_router.post("/auth/google/session")
async def google_session(request: Request, response: Response):
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session id")
    try:
        r = await asyncio.to_thread(
            requests.get, "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id}, timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"Emergent auth failed: {e}")
        raise HTTPException(status_code=401, detail="Google authentication failed")
    user = await upsert_user(data["email"], data.get("name", ""), data.get("picture"))
    token = data.get("session_token") or await create_session(user.user_id)
    await db.user_sessions.update_one(
        {"session_token": token},
        {"$set": {"user_id": user.user_id, "session_token": token,
                  "expires_at": (now_utc() + timedelta(days=7)).isoformat(),
                  "created_at": now_utc().isoformat()}}, upsert=True)
    set_session_cookie(response, token)
    return {"user": user.model_dump(), "token": token}


@api_router.get("/auth/me")
async def auth_me(user: User = Depends(get_current_user)):
    used = await get_usage_today(user.user_id)
    data = user.model_dump()
    data["usage_used"] = used
    data["usage_limit"] = daily_limit_for(user.plan)
    return data


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"status": "ok"}


# ---------- Chats ----------
@api_router.get("/chats")
async def list_chats(user: User = Depends(get_current_user)):
    chats = await db.chats.find({"user_id": user.user_id}, {"_id": 0, "messages": 0}).sort("updated_at", -1).to_list(500)
    return chats


@api_router.post("/chats")
async def create_chat(user: User = Depends(get_current_user)):
    chat = {"chat_id": f"chat_{uuid.uuid4().hex[:12]}", "user_id": user.user_id,
            "title": "New chat", "folder_id": None, "messages": [],
            "created_at": now_utc().isoformat(), "updated_at": now_utc().isoformat()}
    await db.chats.insert_one(chat)
    chat.pop("_id", None); chat.pop("messages", None)
    return chat


class ChatUpdate(BaseModel):
    title: Optional[str] = None
    folder_id: Optional[str] = None
    clear_folder: bool = False


@api_router.patch("/chats/{chat_id}")
async def update_chat(chat_id: str, body: ChatUpdate, user: User = Depends(get_current_user)):
    update = {"updated_at": now_utc().isoformat()}
    if body.title is not None:
        update["title"] = body.title.strip()[:80] or "New chat"
    if body.clear_folder:
        update["folder_id"] = None
    elif body.folder_id is not None:
        update["folder_id"] = body.folder_id
    res = await db.chats.update_one({"chat_id": chat_id, "user_id": user.user_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "ok"}


@api_router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user: User = Depends(get_current_user)):
    await db.chats.delete_one({"chat_id": chat_id, "user_id": user.user_id})
    return {"status": "ok"}


# ---------- Folders ----------
class FolderBody(BaseModel):
    name: str


@api_router.get("/folders")
async def list_folders(user: User = Depends(get_current_user)):
    return await db.folders.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", 1).to_list(200)


@api_router.post("/folders")
async def create_folder(body: FolderBody, user: User = Depends(get_current_user)):
    folder = {"folder_id": f"folder_{uuid.uuid4().hex[:12]}", "user_id": user.user_id,
              "name": (body.name.strip() or "New folder")[:60], "created_at": now_utc().isoformat()}
    await db.folders.insert_one(folder)
    folder.pop("_id", None)
    return folder


@api_router.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, body: FolderBody, user: User = Depends(get_current_user)):
    res = await db.folders.update_one({"folder_id": folder_id, "user_id": user.user_id},
                                      {"$set": {"name": (body.name.strip() or "New folder")[:60]}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "ok"}


@api_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, user: User = Depends(get_current_user)):
    await db.folders.delete_one({"folder_id": folder_id, "user_id": user.user_id})
    await db.chats.update_many({"user_id": user.user_id, "folder_id": folder_id}, {"$set": {"folder_id": None}})
    return {"status": "ok"}


@api_router.get("/chats/{chat_id}/messages")
async def get_messages(chat_id: str, user: User = Depends(get_current_user)):
    chat = await db.chats.find_one({"chat_id": chat_id, "user_id": user.user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"messages": chat.get("messages", []), "title": chat.get("title")}


# ---------- Gemini helpers ----------
def build_contents(history, user_text, images):
    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        txt = m.get("content", "")
        if m.get("type") == "image":
            txt = txt or "[generated an image]"
        contents.append(types.Content(role=role, parts=[types.Part(text=txt or " ")]))
    parts = [types.Part(text=user_text or " ")]
    for b64 in images:
        try:
            parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type=detect_mime(b64)))
        except Exception:
            pass
    contents.append(types.Content(role="user", parts=parts))
    return contents


async def gemini_text_stream(contents, lang_name, web):
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(lang=lang_name),
        max_output_tokens=8000,
    )
    if web:
        cfg.tools = [types.Tool(google_search=types.GoogleSearch())]
    async for chunk in await gemini_client.aio.models.generate_content_stream(
        model=TEXT_MODEL, contents=contents, config=cfg):
        if getattr(chunk, "text", None):
            yield chunk.text


# ---------- Chat stream ----------
@api_router.post("/chats/{chat_id}/stream")
async def stream_chat(chat_id: str, body: ChatStreamBody, user: User = Depends(get_current_user)):
    chat = await db.chats.find_one({"chat_id": chat_id, "user_id": user.user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    await enforce_and_increment(user)

    history = chat.get("messages", [])
    lang_name = LANG_NAMES.get(body.language, "English")

    user_text = body.content or ""
    for f in body.files:
        if f.get("text"):
            user_text += f"\n\n[Attached file: {f.get('name','file')}]\n{f['text']}"

    user_msg = {"id": uuid.uuid4().hex, "role": "user", "type": "text", "content": body.content,
                "attachments": [{"name": f.get("name"), "kind": "file"} for f in body.files]
                               + [{"kind": "image"} for _ in body.images],
                "created_at": now_utc().isoformat()}
    new_title = chat["title"]
    if chat["title"] == "New chat" and body.content:
        new_title = body.content[:48]

    # ----- IMAGE MODE -----
    if body.mode == "image":
        async def image_gen():
            assistant_msg = {"id": uuid.uuid4().hex, "role": "assistant", "type": "image",
                             "content": "", "image_url": "", "created_at": now_utc().isoformat()}
            try:
                parts = [types.Part(text=body.content or "Generate an image")]
                for b64 in body.images:
                    parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type=detect_mime(b64)))
                resp = await gemini_client.aio.models.generate_content(
                    model=IMAGE_MODEL, contents=parts,
                    config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))
                data_url, caption = "", ""
                for part in resp.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        b64img = base64.b64encode(part.inline_data.data).decode()
                        data_url = f"data:{part.inline_data.mime_type};base64,{b64img}"
                    elif getattr(part, "text", None):
                        caption += part.text
                if data_url:
                    assistant_msg["image_url"] = data_url
                    assistant_msg["content"] = caption
                    yield f"data: {json.dumps({'type': 'image', 'url': data_url, 'text': caption})}\n\n"
                else:
                    assistant_msg["type"] = "text"
                    assistant_msg["content"] = caption or "I couldn't generate that image."
                    yield f"data: {json.dumps({'type': 'delta', 'content': assistant_msg['content']})}\n\n"
            except Exception as e:
                logger.error(f"Image gen error: {e}")
                if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                    msg = image_quota_message(body.language)
                else:
                    msg = image_quota_message(body.language)
                assistant_msg["type"] = "text"; assistant_msg["content"] = msg
                yield f"data: {json.dumps({'type': 'delta', 'content': msg})}\n\n"
            await db.chats.update_one({"chat_id": chat_id},
                {"$push": {"messages": {"$each": [user_msg, assistant_msg]}},
                 "$set": {"updated_at": now_utc().isoformat(), "title": new_title}})
            yield f"data: {json.dumps({'type': 'done', 'title': new_title})}\n\n"

        return StreamingResponse(image_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ----- CHAT MODE -----
    contents = build_contents(history, user_text, body.images)

    async def text_gen():
        assistant_text = []
        try:
            async for piece in gemini_text_stream(contents, lang_name, body.web):
                assistant_text.append(piece)
                yield f"data: {json.dumps({'type': 'delta', 'content': piece})}\n\n"
        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            if not assistant_text:
                try:
                    async for piece in gemini_text_stream(contents, lang_name, False):
                        assistant_text.append(piece)
                        yield f"data: {json.dumps({'type': 'delta', 'content': piece})}\n\n"
                except Exception as e2:
                    logger.error(f"Gemini fallback error: {e2}")
                    msg = "Sorry, something went wrong generating a response."
                    if "RESOURCE_EXHAUSTED" in str(e2) or "429" in str(e2):
                        msg = "The AI quota on the current API key is exhausted. Please try again later."
                    assistant_text.append(msg)
                    yield f"data: {json.dumps({'type': 'delta', 'content': msg})}\n\n"
        full = "".join(assistant_text)
        assistant_msg = {"id": uuid.uuid4().hex, "role": "assistant", "type": "text",
                         "content": full, "created_at": now_utc().isoformat()}
        await db.chats.update_one({"chat_id": chat_id},
            {"$push": {"messages": {"$each": [user_msg, assistant_msg]}},
             "$set": {"updated_at": now_utc().isoformat(), "title": new_title}})
        yield f"data: {json.dumps({'type': 'done', 'title': new_title})}\n\n"

    return StreamingResponse(text_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- Regenerate ----------
class RegenBody(BaseModel):
    web: bool = True
    language: str = "en"


@api_router.post("/chats/{chat_id}/regenerate")
async def regenerate_chat(chat_id: str, body: RegenBody, user: User = Depends(get_current_user)):
    chat = await db.chats.find_one({"chat_id": chat_id, "user_id": user.user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = list(chat.get("messages", []))
    if messages and messages[-1]["role"] == "assistant":
        messages.pop()
    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="Nothing to regenerate")
    await db.chats.update_one({"chat_id": chat_id}, {"$set": {"messages": messages}})

    lang_name = LANG_NAMES.get(body.language, "English")
    last_user = messages[-1]
    contents = build_contents(messages[:-1], last_user.get("content") or " ", [])

    async def gen():
        assistant_text = []
        try:
            async for piece in gemini_text_stream(contents, lang_name, body.web):
                assistant_text.append(piece)
                yield f"data: {json.dumps({'type': 'delta', 'content': piece})}\n\n"
        except Exception as e:
            logger.error(f"Regenerate error: {e}")
            if not assistant_text:
                msg = "Sorry, something went wrong generating a response."
                assistant_text.append(msg)
                yield f"data: {json.dumps({'type': 'delta', 'content': msg})}\n\n"
        full = "".join(assistant_text)
        assistant_msg = {"id": uuid.uuid4().hex, "role": "assistant", "type": "text",
                         "content": full, "created_at": now_utc().isoformat()}
        await db.chats.update_one({"chat_id": chat_id},
            {"$push": {"messages": assistant_msg}, "$set": {"updated_at": now_utc().isoformat()}})
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- PayPal billing ----------
def paypal_configured() -> bool:
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)


async def paypal_token() -> str:
    r = await asyncio.to_thread(
        requests.post, f"{PAYPAL_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        data={"grant_type": "client_credentials"}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


async def ensure_paypal_plans():
    cfg = await db.app_config.find_one({"key": "paypal_plans"}, {"_id": 0})
    if cfg and cfg.get("mode") == PAYPAL_MODE and cfg.get("monthly_plan_id") and cfg.get("yearly_plan_id"):
        return cfg
    token = await paypal_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    prod = await asyncio.to_thread(requests.post, f"{PAYPAL_BASE}/v1/catalogs/products", headers=headers,
        json={"name": "Claus IA Pro", "description": "Claus IA Pro subscription",
              "type": "SERVICE", "category": "SOFTWARE"}, timeout=20)
    prod.raise_for_status()
    product_id = prod.json()["id"]

    def plan_payload(name, interval, value):
        return {"product_id": product_id, "name": name, "status": "ACTIVE",
                "billing_cycles": [{"frequency": {"interval_unit": interval, "interval_count": 1},
                                    "tenure_type": "REGULAR", "sequence": 1, "total_cycles": 0,
                                    "pricing_scheme": {"fixed_price": {"value": value, "currency_code": "EUR"}}}],
                "payment_preferences": {"auto_bill_outstanding": True,
                                        "setup_fee": {"value": "0", "currency_code": "EUR"},
                                        "setup_fee_failure_action": "CONTINUE",
                                        "payment_failure_threshold": 1}}

    m = await asyncio.to_thread(requests.post, f"{PAYPAL_BASE}/v1/billing/plans", headers=headers,
        json=plan_payload("Claus IA Pro Monthly", "MONTH", "10"), timeout=20)
    m.raise_for_status()
    y = await asyncio.to_thread(requests.post, f"{PAYPAL_BASE}/v1/billing/plans", headers=headers,
        json=plan_payload("Claus IA Pro Yearly", "YEAR", "100"), timeout=20)
    y.raise_for_status()

    cfg = {"key": "paypal_plans", "mode": PAYPAL_MODE, "product_id": product_id,
           "monthly_plan_id": m.json()["id"], "yearly_plan_id": y.json()["id"]}
    await db.app_config.update_one({"key": "paypal_plans"}, {"$set": cfg}, upsert=True)
    return cfg


@api_router.get("/billing/config")
async def billing_config():
    if not paypal_configured():
        return {"configured": False, "mode": PAYPAL_MODE,
                "prices": {"monthly": "10", "yearly": "100", "currency": "EUR"}}
    try:
        cfg = await ensure_paypal_plans()
    except Exception as e:
        logger.error(f"PayPal plan setup failed: {e}")
        return {"configured": False, "mode": PAYPAL_MODE, "error": "paypal_setup_failed",
                "prices": {"monthly": "10", "yearly": "100", "currency": "EUR"}}
    return {"configured": True, "mode": PAYPAL_MODE, "client_id": PAYPAL_CLIENT_ID,
            "monthly_plan_id": cfg["monthly_plan_id"], "yearly_plan_id": cfg["yearly_plan_id"],
            "prices": {"monthly": "10", "yearly": "100", "currency": "EUR"}}


class ActivateBody(BaseModel):
    subscription_id: str
    plan_type: str = "monthly"


@api_router.post("/billing/activate")
async def billing_activate(body: ActivateBody, user: User = Depends(get_current_user)):
    if not paypal_configured():
        raise HTTPException(status_code=400, detail="PayPal not configured")
    try:
        token = await paypal_token()
        r = await asyncio.to_thread(requests.get,
            f"{PAYPAL_BASE}/v1/billing/subscriptions/{body.subscription_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=20)
        r.raise_for_status()
        sub = r.json()
    except Exception as e:
        logger.error(f"PayPal verify failed: {e}")
        raise HTTPException(status_code=400, detail="Could not verify subscription")
    if sub.get("status") not in ("ACTIVE", "APPROVED"):
        raise HTTPException(status_code=400, detail=f"Subscription not active: {sub.get('status')}")
    await db.users.update_one({"user_id": user.user_id},
        {"$set": {"plan": "pro", "subscription_id": body.subscription_id,
                  "plan_type": body.plan_type, "plan_since": now_utc().isoformat()}})
    return {"status": "ok", "plan": "pro"}


@api_router.post("/billing/cancel")
async def billing_cancel(user: User = Depends(get_current_user)):
    if user.subscription_id and paypal_configured():
        try:
            token = await paypal_token()
            await asyncio.to_thread(requests.post,
                f"{PAYPAL_BASE}/v1/billing/subscriptions/{user.subscription_id}/cancel",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"reason": "User requested cancellation"}, timeout=20)
        except Exception as e:
            logger.error(f"PayPal cancel failed: {e}")
    await db.users.update_one({"user_id": user.user_id},
        {"$set": {"plan": "free", "subscription_id": None, "plan_type": None}})
    return {"status": "ok", "plan": "free"}


@api_router.post("/webhook/paypal")
async def paypal_webhook(request: Request):
    body = await request.json()
    event_type = body.get("event_type", "")
    resource = body.get("resource", {})
    sub_id = resource.get("id") or resource.get("billing_agreement_id")
    try:
        if event_type in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED",
                          "BILLING.SUBSCRIPTION.SUSPENDED") and sub_id:
            await db.users.update_one({"subscription_id": sub_id},
                {"$set": {"plan": "free", "subscription_id": None, "plan_type": None}})
        elif event_type == "BILLING.SUBSCRIPTION.ACTIVATED" and sub_id:
            await db.users.update_one({"subscription_id": sub_id}, {"$set": {"plan": "pro"}})
    except Exception as e:
        logger.error(f"Webhook handling error: {e}")
    return {"status": "ok"}


@api_router.get("/")
async def root():
    return {"message": "Claus IA API"}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
