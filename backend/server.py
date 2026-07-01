import os
import uuid
import json
import base64
import random
import hashlib
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import resend
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent, TextDelta, StreamDone
from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
resend.api_key = RESEND_API_KEY

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

TEXT_MODEL = ("anthropic", "claude-sonnet-4-6")
IMAGE_MODEL = ("gemini", "gemini-3.1-flash-image-preview")
VIDEO_MODEL = "sora-2"

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
    "You reason deeply and carefully, explain clearly, write excellent code, and can analyze "
    "documents and images the user shares. You are honest, thoughtful and concise when appropriate "
    "and thorough when needed. Use Markdown formatting (headings, lists, tables, fenced code blocks "
    "with language identifiers). Always answer in the user's language: {lang}."
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatStreamBody(BaseModel):
    content: str = ""
    images: List[str] = []          # base64 (no data: prefix)
    files: List[dict] = []          # {name, text}
    mode: str = "chat"              # chat | image
    web: bool = True
    language: str = "en"


# ---------- Helpers ----------
def now_utc():
    return datetime.now(timezone.utc)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def create_session(user_id: str) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now_utc() + timedelta(days=7)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    return token


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key="session_token", value=token, httponly=True, secure=True,
        samesite="none", path="/", max_age=7 * 24 * 60 * 60,
    )


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
                name=name or email.split("@")[0], picture=picture)
    doc = user.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.users.insert_one(doc)
    return user


# ---------- Auth: Email OTP ----------
@api_router.post("/auth/otp/request")
async def request_otp(body: OTPRequest):
    code = f"{random.randint(0, 999999):06d}"
    await db.otps.delete_many({"email": body.email})
    await db.otps.insert_one({
        "email": body.email,
        "code_hash": hash_code(code),
        "expires_at": (now_utc() + timedelta(minutes=10)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#FDFDF9;border:1px solid #EBE8E0;border-radius:16px">
      <h1 style="color:#D97251;font-size:24px;margin:0 0 8px">Claus IA</h1>
      <p style="color:#5C5954;font-size:15px">Your verification code is:</p>
      <div style="font-size:38px;font-weight:700;letter-spacing:10px;color:#2D2A26;background:#F3F2EC;padding:18px;text-align:center;border-radius:12px;margin:16px 0">{code}</div>
      <p style="color:#5C5954;font-size:13px">This code expires in 10 minutes. If you didn't request it, ignore this email.</p>
    </div>
    """
    try:
        await asyncio.to_thread(resend.Emails.send, {
            "from": SENDER_EMAIL,
            "to": [body.email],
            "subject": f"{code} is your Claus IA verification code",
            "html": html,
        })
    except Exception as e:
        logger.error(f"Resend send failed: {e}")
        raise HTTPException(status_code=500, detail="Could not send the verification email. Check the email address.")
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


# ---------- Auth: Google (direct OAuth 2.0) ----------
class GoogleAuthBody(BaseModel):
    code: str
    redirect_uri: str


@api_router.post("/auth/google")
async def google_auth(body: GoogleAuthBody, response: Response):
    # REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    try:
        token_res = await asyncio.to_thread(
            requests.post, "https://oauth2.googleapis.com/token",
            data={
                "code": body.code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": body.redirect_uri,
                "grant_type": "authorization_code",
            }, timeout=15,
        )
        token_res.raise_for_status()
        tokens = token_res.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise RuntimeError(f"No access token in Google response: {tokens}")
        info_res = await asyncio.to_thread(
            requests.get, "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=15,
        )
        info_res.raise_for_status()
        data = info_res.json()
    except Exception as e:
        logger.error(f"Google auth failed: {e}")
        raise HTTPException(status_code=401, detail="Google authentication failed")
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Could not read email from Google")
    user = await upsert_user(email, data.get("name", ""), data.get("picture"))
    token = await create_session(user.user_id)
    set_session_cookie(response, token)
    return {"user": user.model_dump(), "token": token}


@api_router.get("/auth/me")
async def auth_me(user: User = Depends(get_current_user)):
    return user.model_dump()


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
    chat = {
        "chat_id": f"chat_{uuid.uuid4().hex[:12]}",
        "user_id": user.user_id,
        "title": "New chat",
        "messages": [],
        "created_at": now_utc().isoformat(),
        "updated_at": now_utc().isoformat(),
    }
    await db.chats.insert_one(chat)
    chat.pop("_id", None)
    chat.pop("messages", None)
    return chat


@api_router.get("/chats/{chat_id}/messages")
async def get_messages(chat_id: str, user: User = Depends(get_current_user)):
    chat = await db.chats.find_one({"chat_id": chat_id, "user_id": user.user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"messages": chat.get("messages", []), "title": chat.get("title")}


@api_router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user: User = Depends(get_current_user)):
    await db.chats.delete_one({"chat_id": chat_id, "user_id": user.user_id})
    return {"status": "ok"}


@api_router.post("/chats/{chat_id}/stream")
async def stream_chat(chat_id: str, body: ChatStreamBody, user: User = Depends(get_current_user)):
    chat = await db.chats.find_one({"chat_id": chat_id, "user_id": user.user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    history = chat.get("messages", [])
    lang_name = LANG_NAMES.get(body.language, "English")

    user_text = body.content or ""
    for f in body.files:
        if f.get("text"):
            user_text += f"\n\n[Attached file: {f.get('name','file')}]\n{f['text']}"

    user_msg = {
        "id": uuid.uuid4().hex,
        "role": "user",
        "type": "text",
        "content": body.content,
        "attachments": [{"name": f.get("name"), "kind": "file"} for f in body.files]
                       + [{"kind": "image"} for _ in body.images],
        "created_at": now_utc().isoformat(),
    }
    new_title = chat["title"]
    if chat["title"] == "New chat" and body.content:
        new_title = body.content[:48]

    # ---------- IMAGE MODE ----------
    if body.mode == "image":
        async def image_gen():
            assistant_msg = {"id": uuid.uuid4().hex, "role": "assistant", "type": "image",
                             "content": "", "image_url": "", "created_at": now_utc().isoformat()}
            try:
                img_chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=chat_id,
                                   system_message="You are an expert image generator.")
                img_chat.with_model(*IMAGE_MODEL).with_params(modalities=["image", "text"])
                file_contents = [ImageContent(b64) for b64 in body.images]
                msg = UserMessage(text=body.content or "Generate an image", file_contents=file_contents)
                text, images = await img_chat.send_message_multimodal_response(msg)
                if images:
                    img = images[0]
                    data_url = f"data:{img['mime_type']};base64,{img['data']}"
                    assistant_msg["image_url"] = data_url
                    assistant_msg["content"] = text or ""
                    yield f"data: {json.dumps({'type': 'image', 'url': data_url, 'text': text or ''})}\n\n"
                else:
                    assistant_msg["type"] = "text"
                    assistant_msg["content"] = text or "I couldn't generate that image."
                    yield f"data: {json.dumps({'type': 'delta', 'content': assistant_msg['content']})}\n\n"
            except Exception as e:
                logger.error(f"Image gen error: {e}")
                assistant_msg["type"] = "text"
                assistant_msg["content"] = "Sorry, image generation failed. Please try again."
                yield f"data: {json.dumps({'type': 'delta', 'content': assistant_msg['content']})}\n\n"
            await db.chats.update_one(
                {"chat_id": chat_id},
                {"$push": {"messages": {"$each": [user_msg, assistant_msg]}},
                 "$set": {"updated_at": now_utc().isoformat(), "title": new_title}},
            )
            yield f"data: {json.dumps({'type': 'done', 'title': new_title})}\n\n"

        return StreamingResponse(image_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------- CHAT MODE ----------
    initial = [{"role": "system", "content": SYSTEM_PROMPT.format(lang=lang_name)}]
    for m in history:
        if m["role"] == "user":
            initial.append({"role": "user", "content": m.get("content", "") or "(image)"})
        elif m["role"] == "assistant":
            txt = m.get("content", "")
            if m.get("type") == "image":
                txt = "[generated an image]"
            initial.append({"role": "assistant", "content": txt or ""})

    file_contents = [ImageContent(b64) for b64 in body.images]
    user_message = UserMessage(text=user_text or "(image)", file_contents=file_contents)

    async def text_gen():
        assistant_text = []

        def build_chat(with_tools: bool):
            c = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=chat_id,
                        system_message=SYSTEM_PROMPT.format(lang=lang_name),
                        initial_messages=list(initial))
            c.with_model(*TEXT_MODEL).with_params(max_tokens=8000)
            if with_tools:
                c.with_tools([{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}])
            return c

        produced = False
        try:
            c = build_chat(with_tools=body.web)
            async for ev in c.stream_message(user_message):
                if isinstance(ev, TextDelta):
                    produced = True
                    assistant_text.append(ev.content)
                    yield f"data: {json.dumps({'type': 'delta', 'content': ev.content})}\n\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as e:
            logger.error(f"Stream error (web={body.web}): {e}")
            if not produced and body.web:
                try:
                    c2 = build_chat(with_tools=False)
                    async for ev in c2.stream_message(user_message):
                        if isinstance(ev, TextDelta):
                            assistant_text.append(ev.content)
                            yield f"data: {json.dumps({'type': 'delta', 'content': ev.content})}\n\n"
                        elif isinstance(ev, StreamDone):
                            break
                except Exception as e2:
                    logger.error(f"Fallback stream error: {e2}")
                    msg = "Sorry, something went wrong generating a response."
                    assistant_text.append(msg)
                    yield f"data: {json.dumps({'type': 'delta', 'content': msg})}\n\n"
            elif not produced:
                msg = "Sorry, something went wrong generating a response."
                assistant_text.append(msg)
                yield f"data: {json.dumps({'type': 'delta', 'content': msg})}\n\n"

        full = "".join(assistant_text)
        assistant_msg = {"id": uuid.uuid4().hex, "role": "assistant", "type": "text",
                         "content": full, "created_at": now_utc().isoformat()}
        await db.chats.update_one(
            {"chat_id": chat_id},
            {"$push": {"messages": {"$each": [user_msg, assistant_msg]}},
             "$set": {"updated_at": now_utc().isoformat(), "title": new_title}},
        )
        yield f"data: {json.dumps({'type': 'done', 'title': new_title})}\n\n"

    return StreamingResponse(text_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- Video generation (Sora 2) ----------
class VideoBody(BaseModel):
    content: str = ""
    size: str = "1280x720"
    duration: int = 4
    language: str = "en"


async def run_video_job(chat_id, asst_id, video_id, prompt, size, duration):
    try:
        vg = OpenAIVideoGeneration(api_key=EMERGENT_LLM_KEY)
        video_bytes = await asyncio.to_thread(vg.text_to_video, prompt, VIDEO_MODEL, size, duration, 600)
        if not video_bytes:
            raise RuntimeError("No video bytes returned")
        b64 = base64.b64encode(video_bytes).decode()
        await db.videos.insert_one({"video_id": video_id, "data": b64, "created_at": now_utc().isoformat()})
        await db.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"messages.$[m].status": "done", "messages.$[m].video_id": video_id,
                      "updated_at": now_utc().isoformat()}},
            array_filters=[{"m.id": asst_id}],
        )
    except Exception as e:
        logger.error(f"Video job error: {e}")
        await db.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"messages.$[m].status": "error",
                      "messages.$[m].content": "Video generation failed. Please try again."}},
            array_filters=[{"m.id": asst_id}],
        )


@api_router.post("/chats/{chat_id}/video")
async def create_video(chat_id: str, body: VideoBody, user: User = Depends(get_current_user)):
    chat = await db.chats.find_one({"chat_id": chat_id, "user_id": user.user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if body.size not in OpenAIVideoGeneration.SIZES:
        body.size = "1280x720"
    if body.duration not in OpenAIVideoGeneration.DURATIONS:
        body.duration = 4
    user_msg = {"id": uuid.uuid4().hex, "role": "user", "type": "text",
                "content": body.content, "attachments": [], "created_at": now_utc().isoformat()}
    asst_id = uuid.uuid4().hex
    video_id = uuid.uuid4().hex
    assistant_msg = {"id": asst_id, "role": "assistant", "type": "video", "status": "generating",
                     "content": "", "video_id": "", "created_at": now_utc().isoformat()}
    new_title = chat["title"]
    if chat["title"] == "New chat" and body.content:
        new_title = body.content[:48]
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$push": {"messages": {"$each": [user_msg, assistant_msg]}},
         "$set": {"updated_at": now_utc().isoformat(), "title": new_title}},
    )
    asyncio.create_task(run_video_job(
        chat_id, asst_id, video_id,
        body.content or "A short cinematic video", body.size, body.duration,
    ))
    return {"assistant_id": asst_id, "title": new_title}


@api_router.get("/videos/{video_id}")
async def get_video(video_id: str):
    doc = await db.videos.find_one({"video_id": video_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Video not found")
    data = base64.b64decode(doc["data"])
    return Response(content=data, media_type="video/mp4")


@api_router.get("/")
async def root():
    return {"message": "Claus IA API"}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
