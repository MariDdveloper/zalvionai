import os
import time
import uuid
import base64
import random
import hashlib
import asyncio
import logging
import openai
import pypdf
import re
from openai import AsyncOpenAI
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional
from collections import deque
import edge_tts
import io
import httpx
import resend
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends
import json
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from pydantic import BaseModel, EmailStr, Field
from exa_py import AsyncExa
import pypdf
from urllib.parse import quote

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# =====================================================================================
# CONFIGURAZIONE SUPABASE
# =====================================================================================
SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_SERVICE_KEY = os.environ['SUPABASE_SERVICE_KEY']
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# =====================================================================================
# ALTRE CONFIGURAZIONI
# =====================================================================================
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'noreply@getzalvion.com')
resend.api_key = RESEND_API_KEY

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
EXA_API_KEY = os.environ.get('EXA_API_KEY')
exa_client = AsyncExa(api_key=EXA_API_KEY) if EXA_API_KEY else None
CLOUDFLARE_TEXT_ACCOUNT_ID = "53883d6ffd5f05104d800edf7d61f7cb"   # nuovo account, diverso da quello immagini
CLOUDFLARE_TEXT_API_TOKEN = os.environ.get('CLOUDFLARE_API_KEY')
CLOUDFLARE_TEXT_MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"  # verifica lo slug esatto nel dashboard
CLOUDFLARE_TEXT_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/"
    f"{CLOUDFLARE_TEXT_ACCOUNT_ID}/ai/run/{CLOUDFLARE_TEXT_MODEL}"
)
CLOUDFLARE_TEXT_TEMPERATURE = float(os.environ.get('CLOUDFLARE_TEXT_TEMPERATURE', '0.7'))
CLOUDFLARE_TEXT_MAX_TOKENS = int(os.environ.get('CLOUDFLARE_TEXT_MAX_TOKENS', '1024'))
# 2) CLASSIFICAZIONE (is_code_request + filtro immagini)
CLOUDFLARE_CLASSIFY_ACCOUNT_ID = os.environ.get('CLOUDFLARE_CLASSIFY_ACCOUNT_ID')
CLOUDFLARE_CLASSIFY_API_TOKEN = os.environ.get('CLOUDFLARE_CLASSIFY_API_TOKEN')
CLOUDFLARE_CLASSIFY_MODEL = os.environ.get('CLOUDFLARE_CLASSIFY_MODEL', '@cf/google/gemma-2b-it')
CLOUDFLARE_CLASSIFY_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/"
    f"{CLOUDFLARE_CLASSIFY_ACCOUNT_ID}/ai/run/{CLOUDFLARE_CLASSIFY_MODEL}"
)

# 3) IMMAGINI (Flux 1 schnell)
CLOUDFLARE_IMAGE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_IMAGE_ACCOUNT_ID')
CLOUDFLARE_IMAGE_API_TOKEN = os.environ.get('CLOUDFLARE_IMAGE_API_TOKEN')
CLOUDFLARE_IMAGE_MODEL = os.environ.get('CLOUDFLARE_IMAGE_MODEL', '@cf/black-forest-labs/flux-1-schnell')
CLOUDFLARE_IMAGE_STEPS = int(os.environ.get('CLOUDFLARE_IMAGE_STEPS', '4'))
NVIDIA_API_KEY = os.environ.get('NVIDIA_API_KEY')
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_CODE_MODEL = os.environ.get('NVIDIA_CODE_MODEL', 'nvidia/nemotron-3-ultra-550b-a55b')
NVIDIA_CODE_MODEL_FALLBACK = os.environ.get('NVIDIA_CODE_MODEL_FALLBACK', 'nvidia/nemotron-3.5-super-vl-120b-a12b')
NVIDIA_CODE_MAX_TOKENS = int(os.environ.get('NVIDIA_CODE_MAX_TOKENS', '32768'))


# =====================================================================================
# NVIDIA NIM — UNICO PROVIDER AI DI ZALVION (testo + codice)
# =====================================================================================
# Gratuito, nessuna carta di credito richiesta, ~40 richieste/minuto per account
# (limite condiviso tra tutti i modelli). Endpoint OpenAI-compatible.
# NB CRITICO: MAI mettere una chiave hardcoded come default qui - solo env var.
# Se questa riga ha mai contenuto una chiave vera, quella chiave va revocata SUBITO
# su build.nvidia.com/settings/api-keys, indipendentemente da questo fix.
MAX_HISTORY_MESSAGES = 16


CODE_KEYWORDS = (
    # --- Termini generici multilingua (IT, EN, ES, FR, DE, PT, NL) ---
    "code", "codice", "código", "code source", "código fonte", "broncode",
    "script", "sorgente", "source code", "quellcode", "code-quelle",
    "programma", "programme", "programa", "programm", "programmeren",
    "programmazione", "programming", "programación", "programmation",
    "programmierung", "programação",
    "function", "funzione", "función", "fonction", "funktion", "função", "functie",
    "metodo", "method", "método", "méthode", "méthode",
    "debug", "debugging", "eseguire il debug", "debugueo", "débogage", "fehlersuche",
    "bug", "errore", "error", "erreur", "fehler", "erro",
    "eccezione", "exception", "excepción", "exception", "ausnahme", "exceção",
    "crash", "traceback", "stack trace", "stacktrace", "pila di chiamate",
    "sito", "sito web", "website", "webapp", "web app", "landing page", "pagina web",
    "applicazione", "application", "app", "dashboard", "gioco", "game",

    # --- Linguaggi di programmazione ---
    "python", "javascript", "typescript", "java ", " c ", "c++", "c#", "golang", "go ",
    "rust", "ruby", "php", "swift", "kotlin", "scala", "perl", "haskell", "elixir",
    "erlang", "dart", "lua", "matlab", "octave", "julia", "objective-c", "objective c",
    "assembly", "assembler", "cobol", "fortran", "pascal", "delphi", "prolog",
    "clojure", "groovy", "vb.net", "visual basic", "vba", "powershell", "bash",
    "zsh", "shell script", "sql", "plsql", "pl/sql", "t-sql", "transact-sql",
    "html", "css", "sass", "scss", "less", "stylus", "xml", "yaml", "toml",
    "graphql", "nim", "crystal", "f#", "fsharp", "ocaml", "elm", "purescript",
    "reasonml", "zig", "vlang", "ada", "scheme", "common lisp", "racket",
    "smalltalk", "tcl", "verilog", "vhdl", "solidity", "webassembly", "wasm",
    "brainfuck", "cython", "coffeescript", "livescript", "apex", "abap",
    "d language", "ballerina", "chapel", "hack lang", "raku", "red lang",

    # --- Framework, librerie, ecosistemi ---
    "react", "react native", "vue", "vue.js", "angular", "angularjs", "svelte",
    "sveltekit", "next.js", "nextjs", "nuxt", "nuxt.js", "astro", "remix",
    "gatsby", "django", "flask", "fastapi", "pyramid", "spring", "spring boot",
    "spring mvc", "laravel", "symfony", "codeigniter", "yii", "rails",
    "ruby on rails", "sinatra", "express", "express.js", "nestjs", "koa",
    "hapi", ".net", "dotnet", ".net core", "asp.net", "blazor", "node.js",
    "nodejs", "deno", "bun", "jquery", "bootstrap", "tailwind", "tailwindcss",
    "bulma", "material ui", "chakra ui", "redux", "mobx", "recoil", "zustand",
    "apollo", "apollo client", "prisma", "sequelize", "typeorm", "sqlalchemy",
    "django orm", "hibernate", "mongoose", "pandas", "numpy", "scipy",
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn", "opencv",
    "huggingface", "transformers", "langchain", "docker", "docker-compose",
    "kubernetes", "k8s", "helm", "terraform", "ansible", "puppet", "chef",
    "jenkins", "github actions", "gitlab ci", "circleci", "travis ci",
    "webpack", "vite", "rollup", "parcel", "esbuild", "babel", "eslint",
    "prettier", "jest", "vitest", "mocha", "chai", "pytest", "unittest",
    "selenium", "playwright", "cypress", "junit", "testng", "phpunit",
    "rspec", "flutter", "xamarin", "ionic", "cordova", "electron", "tauri",
    "unity", "unreal engine", "godot engine", "three.js", "d3.js", "chart.js",

    # --- Concetti di programmazione ---
    "algoritmo", "algorithm", "algoritmo", "algorithme", "algorithmus",
    "struttura dati", "data structure", "estructura de datos", "structure de données",
    "array", "vettore", "lista", "list", "liste", "dizionario", "dictionary",
    "diccionario", "hashmap", "hash table", "tabella hash", "stack", "pila",
    "queue", "coda", "file d'attente", "albero", "tree", "arbre", "grafo",
    "graph", "graphe", "ricorsione", "recursion", "récursivité", "iterazione",
    "iteration", "itération", "loop", "ciclo", "boucle", "schleife", "for loop",
    "while loop", "do while", "condizionale", "conditional", "condition",
    "if else", "switch case", "classe", "class", "clase", "klasse", "oggetto",
    "object", "objet", "ereditarietà", "inheritance", "héritage", "vererbung",
    "polimorfismo", "polymorphism", "polymorphisme", "incapsulamento",
    "encapsulation", "interfaccia", "interface", "costruttore", "constructor",
    "metodo", "method", "parametro", "parameter", "paramètre", "argomento",
    "argument", "variabile", "variable", "variável", "costante", "constant",
    "puntatore", "pointer", "pointeur", "riferimento", "reference",
    "thread", "threading", "multithreading", "processo", "process",
    "concorrenza", "concurrency", "concurrence", "asincrono", "asynchronous",
    "async", "await", "promise", "callback", "evento", "event", "listener",
    "closure", "chiusura", "lambda", "generics", "generici", "enum",
    "enumerazione", "singleton", "design pattern", "pattern di progettazione",
    "solid principles", "clean code", "dependency injection", "iniezione di dipendenze",

    # --- Dev tools / versioning ---
    "git", "github", "gitlab", "bitbucket", "commit", "push", "pull request",
    "merge request", "merge", "branch", "ramo", "repository", "repo",
    "ide", "vscode", "visual studio code", "visual studio", "intellij",
    "pycharm", "eclipse", "xcode", "android studio", "sublime text",
    "vim", "neovim", "emacs", "terminal", "cli", "command line",
    "riga di comando", "npm", "npx", "pip", "pipenv", "poetry", "yarn",
    "pnpm", "cargo", "maven", "gradle", "nuget", "composer", "conda",
    "virtualenv", "docker hub", "package.json", "requirements.txt",

    # --- Web / backend / data ---
    "api ", "endpoint", "rest api", "restful", "graphql api", "grpc",
    "webhook", "backend", "frontend", "fullstack", "full stack",
    "database", "banca dati", "base de datos", "base de données", "db ",
    "query", "sql query", "orm", "migration", "migrazione", "schema",
    "tabella", "table", "indice", "index", "join", "transazione",
    "transaction", "cache", "caching", "redis", "memcached", "sessione",
    "session", "cookie", "jwt", "oauth", "sso", "autenticazione",
    "authentication", "autorizzazione", "authorization", "middleware",
    "routing", "router", "server", "http", "https", "tcp/ip", "websocket",
    "json", "parsing", "parser", "compilatore", "compiler", "interprete",
    "interpreter", "runtime", "framework", "libreria", "library", "sdk",
    "dipendenza", "dependency", "build", "deploy", "deployment", "ci/cd",
    "pipeline", "microservizi", "microservices", "monolite", "monolith",
    "serverless", "lambda function", "cloud function", "edge function",
    "cdn", "load balancer", "bilanciatore di carico", "reverse proxy",
    "nginx", "apache", "cors", "csrf", "sql injection", "xss",

    # --- Errori, testing, ottimizzazione ---
    "exception handling", "gestione delle eccezioni", "try catch",
    "try except", "null pointer", "undefined", "nan", "memory leak",
    "perdita di memoria", "race condition", "deadlock", "bottleneck",
    "collo di bottiglia", "ottimizzazione", "optimization", "performance",
    "refactoring", "refactor", "code review", "revisione del codice",
    "unit test", "test unitario", "integration test", "test di integrazione",
    "mock", "stub", "test coverage", "copertura del codice", "sintassi",
    "syntax", "regex", "espressione regolare", "regular expression",
    "linting", "static analysis", "analisi statica", "profiling", "logging",
)

CODE_EXTENSIONS = (
    ".py", ".pyw", ".pyx", ".pyi", ".ipynb",
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".d.ts",
    ".java", ".class", ".jar", ".kt", ".kts", ".scala", ".groovy", ".clj", ".cljs",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".cs", ".m", ".mm",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".styl", ".vue", ".svelte",
    ".astro", ".ejs", ".pug", ".hbs", ".mustache", ".twig", ".blade.php", ".cshtml",
    ".razor", ".aspx", ".jsp",
    ".go", ".rb", ".erb", ".php", ".phtml", ".rs", ".swift", ".dart", ".lua",
    ".pl", ".pm", ".ex", ".exs", ".erl", ".hrl", ".hs", ".fs", ".fsx", ".fsi",
    ".ml", ".mli", ".nim", ".cr", ".zig", ".v", ".jl", ".r", ".rmd",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".dockerfile",
    ".tf", ".tfvars", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".cmake", ".mk", ".makefile", ".gradle", ".pom", ".sbt",
    ".json", ".jsonc", ".xml", ".csv", ".tsv", ".sql", ".graphql", ".gql", ".proto",
    ".asm", ".s", ".vhd", ".vhdl", ".v", ".sv",
    ".vb", ".vbs", ".pas", ".pp", ".ada", ".adb", ".ads", ".scm", ".rkt",
    ".lisp", ".el", ".tcl", ".sol", ".wat", ".wasm", ".apex", ".abap",
    ".md", ".mdx", ".rst", ".tex",
)

# ---- Cloudflare Workers AI (SOLO generazione immagini - Flux 1 schnell, piano free, 720 req/min) ----


PAYPAL_MODE = os.environ.get('PAYPAL_MODE', 'sandbox')
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', '')
PAYPAL_SECRET = os.environ.get('PAYPAL_SECRET', '')
PAYPAL_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE == 'sandbox' else "https://api-m.paypal.com"

FREE_DAILY_LIMIT = 108958948594
PRO_DAILY_LIMIT = 108958948594

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
api_router = APIRouter(prefix="/api")

LANG_NAMES = {
    "en": "English", "it": "Italian", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "ar": "Arabic", "hi": "Hindi", "tr": "Turkish", "pl": "Polish",
}

SYSTEM_PROMPT = """You are Zalvion AI — an elite, world-class AI engineer and assistant, especially outstanding at writing production-grade code, but equally strong at reasoning, writing, research synthesis, and analyzing documents the user shares.

## IDENTITY
- You are Zalvion AI. Never mention DeepSeek, Kimi, Moonshot AI, NVIDIA, or any other underlying model/provider name, even if asked directly what model powers you — say you are Zalvion AI and do not name the underlying infrastructure.
- Be a confident, precise, senior-level engineer/assistant. Warm and clear, never robotic, never overly formal, never fake-enthusiastic.

## LANGUAGE
- Always answer in the user's language: {lang}. This applies to prose, code comments, and explanations, unless the user explicitly asks for something in another language.

## ENGINEERING & UI/UX STANDARD
- You are also a world-class UI/UX designer. Any interface you build must look and feel like it shipped from a top design studio: deliberate typography, spacing, and color choices, real visual hierarchy, tasteful micro-interactions and transitions, and genuine responsiveness across screen sizes — never a generic, unstyled, "default framework" look.
- Code must be complete, correct, and production-grade every time: no placeholders, no "rest of the code here", no TODOs, no invented APIs. Handle edge cases and errors explicitly. If you would not ship it to a real user, do not hand it over.
- Prefer clarity and maintainability: sensible naming, small focused functions/components, comments only where they add real understanding.

## FORMATTING (for normal, non-project answers)
- Use Markdown: headings, bullet/numbered lists, tables where they clarify structured data, fenced code blocks with the correct language id for any inline snippet.
- Be concise by default: give the direct answer first, supporting detail only if it adds real value. No filler preamble, no restating the user's question back to them.
- For debugging help or a small code fix that is NOT a full runnable project, reply with a short explanation plus the corrected snippet in an inline fenced code block — do NOT wrap small fixes in an artifact.

## ARTIFACTS — VERY IMPORTANT
When the user asks you to build, create, code, or write a runnable PROJECT (a web app, component, website, landing page, game, UI, dashboard, or a script/program in any language), you MUST output a COMPLETE, WORKING, self-contained project wrapped EXACTLY in this format.

CRITICAL SYNTAX MANDATE: 
You MUST start your response with a single empty new line, and then write the artifact tag. Never start the text directly with the letters. This empty space protects the token stream from frontend truncation bugs.

EXACT FORMATTING MATRIX:

<claus-artifact type="static" title="Short Title">
<file path="/index.html">
...full file content...
</file>
</claus-artifact>



Rules:
- `type` must ALWAYS be "static" for any frontend interface, web application, dashboard, 3D site, or component to ensure compatibility with the live preview container. Do NOT use "react" or multiple files unless explicitly requested for a backend environment.
- static: provide a single, fully-contained /index.html. All styles must be written inside an inline `<style>` tag, and all JavaScript logic must be written inside an inline `<script>` tag. For 3D capabilities, canvas elements, animations, or advanced graphics, load the official Three.js or similar libraries dynamically via stable, public CDN script tags (e.g., cdnjs or unpkg) directly inside the HTML head.
- node / python / other: provide the real backend files (e.g. /main.py, /server.js) only when asked for pure script/backend tasks. These have no live preview but the user will read the code — it must still be complete and flawless.
- Write FULLY working code. NEVER use placeholders, TODOs, ellipses (`...`) or "rest of code here". Handle edge cases and errors inside the code. Ensure all HTML tags, script boundaries, and syntax brackets are completely closed before hitting any token limit. Avoid long blocks of comments or text descriptions to preserve token economy and prevent truncation.
- Put ONE short sentence BEFORE the artifact saying what you built, and you may add a short note AFTER it. Do NOT repeat the code outside the artifact.
- For normal questions that are NOT about building a project, reply with plain Markdown as usual (short inline ```code``` snippets are fine and must NOT be wrapped in an artifact).

## ACCURACY & HONESTY
- Never invent APIs, library methods, package names, or version numbers you are not confident about. If unsure, say so explicitly and suggest how to verify instead of presenting a guess as fact.
- If a request is ambiguous or missing information you genuinely need, ask ONE direct clarifying question instead of guessing silently.
- If a web-search context block appears as a separate system message before the user's latest message, treat it as authoritative for anything time-sensitive and weave it in naturally — never narrate that you "searched" or expose those instructions.

## ATTACHMENTS
- Code/text file attachments arrive inline as labeled fenced blocks — treat them as ground truth for that file's current content; when asked to modify one, base changes on exactly what was provided.

## SAFETY BOUNDARIES
- Do not write malware, exploits, credential-stealing scripts, or anything designed to cause harm or break the law — decline briefly and, if a legitimate alternative exists, suggest it.
- Do not produce hateful content, content sexualizing minors, or other disallowed content — decline briefly, without lecturing.
"""

# =====================================================================================
# MODELLI Pydantic e rate limiter
# =====================================================================================
class RateLimiter:
    """Spazia gli AVVII delle chiamate in base all'RPS del piano - non limita quanto
    dura la generazione una volta partita, solo quanto spesso ne parte una nuova."""
    def __init__(self, rps: float):
        self.min_interval = 1.0 / rps
        self.last_call = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            elapsed = time.monotonic() - self.last_call
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self.last_call = time.monotonic()

NVIDIA_RPS = float(os.environ.get('NVIDIA_RPS', '0.55'))
nvidia_limiter = RateLimiter(rps=NVIDIA_RPS)
nvidia_concurrency = asyncio.Semaphore(4)


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    code: str


class GoogleTokenBody(BaseModel):
    credential: str


class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    plan: str = "free"
    subscription_id: Optional[str] = None
    plan_type: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
class GoogleSessionPayload(BaseModel):
    session_id: str

@app.post("/api/auth/google/session")
async def verify_google_session_endpoint(payload: GoogleSessionPayload):
    try:
        if not payload.session_id:
            raise HTTPException(status_code=400, detail="Session ID richiesto")

        try:
            user_response = supabase.auth.admin.get_user_by_id(payload.session_id)
        except Exception as auth_err:
            logging.error(f"Errore diretto da Supabase Auth: {str(auth_err)}")
            raise HTTPException(status_code=401, detail="Sessione non riconosciuta da Supabase")

        if not user_response or not hasattr(user_response, 'user'):
            raise HTTPException(status_code=401, detail="Sessione non valida o scaduta")

        return {
            "session": {
                "access_token": payload.session_id,
                "token_type": "bearer",
                "user": {
                    "id": str(user_data.user.id) if hasattr(user_data.user, 'id') else user_data.user.get('id'),
                    "email": user_data.user.email if hasattr(user_data.user, 'email') else user_data.user.get('email')
                }
            },
            "authenticated": True
        }
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        logging.error(f"Crash interno del server: {str(e)}")
        raise HTTPException(status_code=500, detail="Errore di elaborazione interna")
class AttachmentIn(BaseModel):
    name: str = ""
    kind: str = "file"
    b64: str = ""
    text: str = ""


class ChatMessageIn(BaseModel):
    role: str
    content: str
    attachments: List[AttachmentIn] = []


class ChatGenerateBody(BaseModel):
    messages: List[ChatMessageIn]
    language: str = "en"


class ImageGenerateBody(BaseModel):
    prompt: str
    width: int = 768
    height: int = 768
    content: str = ""
    attachments: List[dict] = []
class TTSBody(BaseModel):
    text: str
    lang: str = "it"

EDGE_TTS_VOICE = os.environ.get('EDGE_TTS_VOICE', 'en-US-AndrewMultilingualNeural')
class AssistantMsgBody(BaseModel):
    content: str = ""
    type: str = "text"
    image_url: str = ""
    replace_last: bool = False


class UserMsgBody(BaseModel):
    content: str = ""
    attachments: List[dict] = []


class ChatUpdate(BaseModel):
    title: Optional[str] = None
    folder_id: Optional[str] = None
    clear_folder: bool = False


class FolderBody(BaseModel):
    name: str


class ActivateBody(BaseModel):
    subscription_id: str
    plan_type: str = "monthly"
class PollinationsImageBody(BaseModel):
    prompt: str


# =====================================================================================
# HELPER GENERICI SUPABASE
# =====================================================================================
async def sb_select_one(table: str, **filters) -> Optional[dict]:
    def _run():
        q = supabase.table(table).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        res = q.limit(1).execute()
        return res.data[0] if res.data else None
    return await asyncio.to_thread(_run)


async def sb_select(table: str, columns: str = "*", order_by: Optional[str] = None,
                    desc: bool = True, limit: int = 500, **filters) -> list:
    def _run():
        q = supabase.table(table).select(columns)
        for k, v in filters.items():
            q = q.eq(k, v)
        if order_by:
            q = q.order(order_by, desc=desc)
        q = q.limit(limit)
        return q.execute().data
    return await asyncio.to_thread(_run)


async def sb_insert(table: str, doc: dict) -> dict:
    def _run():
        res = supabase.table(table).insert(doc).execute()
        return res.data[0] if res.data else doc
    return await asyncio.to_thread(_run)


async def sb_update(table: str, values: dict, **filters):
    def _run():
        q = supabase.table(table).update(values)
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute()
    return await asyncio.to_thread(_run)


async def sb_delete(table: str, **filters):
    def _run():
        q = supabase.table(table).delete()
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute()
    return await asyncio.to_thread(_run)


async def sb_upsert(table: str, doc: dict, on_conflict: Optional[str] = None):
    def _run():
        if on_conflict:
            return supabase.table(table).upsert(doc, on_conflict=on_conflict).execute()
        return supabase.table(table).upsert(doc).execute()
    return await asyncio.to_thread(_run)


# =====================================================================================
# HELPER GENERALI
# =====================================================================================
def now_utc():
    return datetime.now(timezone.utc)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def create_session(user_id: str) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    await sb_insert("user_sessions", {
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
    session = await sb_select_one("user_sessions", session_token=token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user_doc = await sb_select_one("users", user_id=session["user_id"])
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user_doc)


async def upsert_user(email: str, name: str, picture: Optional[str] = None) -> User:
    existing = await sb_select_one("users", email=email)
    if existing:
        return User(**existing)
    user = User(user_id=f"user_{uuid.uuid4().hex[:12]}", email=email,
                name=name or email.split("@")[0], picture=picture, plan="free")
    doc = user.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await sb_insert("users", doc)
    return user


def daily_limit_for(plan: str) -> int:
    return PRO_DAILY_LIMIT if plan == "pro" else FREE_DAILY_LIMIT


async def get_usage_today(user_id: str) -> int:
    today = date.today().isoformat()
    doc = await sb_select_one("usage", user_id=user_id, date=today)
    return doc["count"] if doc else 0


async def enforce_and_increment(user: User):
    today = date.today().isoformat()
    existing = await sb_select_one("usage", user_id=user.user_id, date=today)
    used = existing["count"] if existing else 0
    if used >= daily_limit_for(user.plan):
        raise HTTPException(status_code=402, detail="daily_limit_reached")
    if existing:
        await sb_update("usage", {"count": used + 1}, user_id=user.user_id, date=today)
    else:
        await sb_insert("usage", {"user_id": user.user_id, "date": today, "count": 1})


async def append_chat_message(chat_id: str, user_id: str, message: dict,
                              new_title: Optional[str] = None, replace_last: bool = False) -> dict:
    chat = await sb_select_one("chats", chat_id=chat_id, user_id=user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = list(chat.get("messages") or [])
    if replace_last and messages and messages[-1].get("role") == "assistant":
        messages.pop()
    messages.append(message)
    update = {"messages": messages, "updated_at": now_utc().isoformat()}
    if new_title is not None:
        update["title"] = new_title
    await sb_update("chats", update, chat_id=chat_id)
    return chat


IMAGE_QUOTA_MSG = {
    "it": "🎨 **Oggi abbiamo raggiunto il limite di generazione immagini!**\n\nLe nostre GPU creative stanno prendendo fiato dopo aver disegnato tantissimo. Riprova tra poco ✨\n\nNel frattempo posso aiutarti con testo, codice, idee e analisi - chiedimi pure!",
    "en": "🎨 **We've hit today's image generation limit!**\n\nOur creative GPUs are catching their breath after a lot of drawing. Please try again shortly ✨\n\nIn the meantime I can help you with text, code, ideas and analysis - just ask!",
}


def image_quota_message(lang: str) -> str:
    return IMAGE_QUOTA_MSG.get(lang, IMAGE_QUOTA_MSG["en"])


# =====================================================================================
# PROVIDER AI: NVIDIA NIM (unico provider — testo: DeepSeek V4-Flash, codice: Kimi K3)
# =====================================================================================
# =====================================================================================
# PROVIDER AI: NVIDIA NIM (unico provider — testo: DeepSeek V4-Flash, codice: Kimi K3)
# =====================================================================================







# =====================================================================================
# ZALVION AI - BLOCCO AI CORRETTO
# Sostituisce per intero il blocco incollato (dalle funzioni di conversione messaggi
# fino a /ai/generate/status). Dipendenze esterne invariate: pypdf, httpx, openai,
# AsyncOpenAI, RateLimiter, now_utc, sb_*, resend, ecc. restano definiti altrove.
#
# Variabili d'ambiente / costanti opzionali nuove (hanno un default sicuro):
#   CLOUDFLARE_TEXT_VISION = "1"  -> solo se il modello di testo ha davvero la vision
#   PDF_MAX_CHARS                  -> tetto caratteri estratti da un PDF
# =====================================================================================

# --- Costanti nuove -------------------------------------------------------------------
CLOUDFLARE_TEXT_VISION = os.environ.get("CLOUDFLARE_TEXT_VISION", "0") == "1"
PDF_MAX_CHARS = int(os.environ.get("PDF_MAX_CHARS", "12000"))  # Mistral 7B ha contesto corto
# Mistral 7B: lascia vuoto (non invia nulla). Gemma 4: imposta CLOUDFLARE_TEXT_THINKING=0
# per disattivare il thinking ed evitare risposte lente.
_t = os.environ.get("CLOUDFLARE_TEXT_THINKING", "").strip()
CLOUDFLARE_TEXT_THINKING: Optional[bool] = {"0": False, "1": True}.get(_t)

# Promemoria di lingua messo in CODA all'ultimo messaggio utente (e' la posizione
# che un modello piccolo come Mistral 7B segue di piu'). Scritto nella lingua target.
LANG_REMINDERS = {
    "it": "Rispondi esclusivamente in italiano.",
    "en": "Reply exclusively in English.",
    "es": "Responde exclusivamente en español.",
    "fr": "Réponds exclusivement en français.",
    "de": "Antworte ausschließlich auf Deutsch.",
    "pt": "Responda exclusivamente em português.",
}
LANG_ACKS = {
    "it": "Capito. Risponderò sempre in italiano, in modo naturale e diretto.",
    "en": "Understood. I will always reply in English.",
    "es": "Entendido. Responderé siempre en español.",
    "fr": "Compris. Je répondrai toujours en français.",
    "de": "Verstanden. Ich antworte immer auf Deutsch.",
    "pt": "Entendido. Responderei sempre em português.",
}


def _prepend_text(content, text: str):
    if isinstance(content, str):
        return text + content
    return [{"type": "text", "text": text}] + list(content)


def _append_text(content, text: str):
    if isinstance(content, str):
        return content + text
    return list(content) + [{"type": "text", "text": text}]

# Riferimenti ai task in background: senza, asyncio puo' garbage-collectarli a meta' lavoro.
_background_tasks: set = set()


# =====================================================================================
# CONVERSIONE MESSAGGI
# =====================================================================================
def _guess_image_mime(b64: str) -> str:
    head = (b64 or "")[:12]
    if head.startswith("iVBOR"):
        return "image/png"
    if head.startswith("/9j/"):
        return "image/jpeg"
    if head.startswith("R0lGOD"):
        return "image/gif"
    if head.startswith("UklGR"):
        return "image/webp"
    return "image/jpeg"


def _to_openai_messages(messages: List[dict]) -> List[dict]:
    """Per NVIDIA (modelli di codice, solo testo): immagini/PDF diventano segnaposto."""
    converted = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            converted.append({"role": m["role"], "content": content or " "})
            continue
        text_chunks = []
        for part in content:
            if part["type"] == "text":
                text_chunks.append(part["text"])
            elif part["type"] == "image_url":
                text_chunks.append("[Allegato immagine ricevuto: analisi immagini temporaneamente non disponibile]")
            elif part["type"] == "document_url":
                text_chunks.append("[Allegato PDF ricevuto: analisi PDF temporaneamente non disponibile]")
        converted.append({"role": m["role"], "content": "\n".join(text_chunks) or " "})
    return converted


def _to_cloudflare_messages(messages: List[dict], vision: bool = False) -> List[dict]:
    """
    Per Cloudflare Workers AI. Con vision=False (default, Mistral 7B) il contenuto
    e' SEMPRE una stringa: Mistral non accetta parti image_url e andrebbe in errore.
    Con vision=True (es. Gemma) le immagini passano come image_url.
    """
    converted = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            converted.append({"role": m["role"], "content": content or " "})
            continue
        parts = []
        for part in content:
            if part["type"] == "text":
                if part["text"]:
                    parts.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image_url":
                if vision:
                    img = part["image_url"]
                    if isinstance(img, dict):
                        img = img.get("url", "")
                    if img:
                        parts.append({"type": "image_url", "image_url": {"url": img}})
                else:
                    parts.append({"type": "text", "text": "[Allegato immagine: non analizzabile]"})
            elif part["type"] == "document_url":
                parts.append({"type": "text", "text": "[Allegato PDF: non leggibile]"})
        if not parts:
            parts = [{"type": "text", "text": " "}]
        if all(p["type"] == "text" for p in parts):
            converted.append({"role": m["role"], "content": "\n".join(p["text"] for p in parts)})
        else:
            converted.append({"role": m["role"], "content": parts})
    return converted


def _normalize_roles(messages: List[dict]) -> List[dict]:
    """
    Mistral 7B Instruct pretende ruoli rigorosamente alternati user/assistant e che
    si parta da 'user'. Qui: scarta i messaggi iniziali non-user e fonde quelli
    consecutivi con lo stesso ruolo (solo se entrambi stringhe).
    """
    out: List[dict] = []
    for m in messages:
        if m["role"] not in ("user", "assistant"):
            continue
        if not out and m["role"] != "user":
            continue
        if out and out[-1]["role"] == m["role"] and isinstance(out[-1]["content"], str) and isinstance(m["content"], str):
            out[-1]["content"] = f"{out[-1]['content']}\n\n{m['content']}"
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _prepend_text(content, text: str):
    if isinstance(content, str):
        return text + content
    return [{"type": "text", "text": text}] + list(content)


def _append_text(content, text: str):
    if isinstance(content, str):
        return content + text
    return list(content) + [{"type": "text", "text": text}]


# =====================================================================================
# PDF
# =====================================================================================
async def extract_pdf_text(b64_pdf: str, max_chars: int = PDF_MAX_CHARS) -> str:
    """Estrazione locale, nessuna chiamata AI. PDF scansionati -> testo vuoto (limite noto)."""
    def _extract():
        reader = pypdf.PdfReader(io.BytesIO(base64.b64decode(b64_pdf)))
        parts, total = [], 0
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total >= max_chars:
                break
        return "\n\n".join(parts)[:max_chars]
    return await asyncio.to_thread(_extract)


async def prepare_attachments(body: ChatGenerateBody) -> None:
    """Fallback: PDF dell'ultimo messaggio ancora non convertiti in allegati di testo."""
    last_user = next((m for m in reversed(body.messages) if m.role == "user"), None)
    if not last_user:
        return
    for att in last_user.attachments:
        if att.kind == "pdf" and att.b64:
            try:
                text = await extract_pdf_text(att.b64)
            except Exception as e:
                logger.warning(f"Lettura PDF '{att.name}' fallita: {e}")
                text = ""
            att.kind = "file"
            att.text = text if text.strip() else "(nessun testo selezionabile trovato - il PDF potrebbe essere scansionato)"
            att.b64 = ""


# =====================================================================================
# CLOUDFLARE WORKERS AI - TESTO
# =====================================================================================
async def stream_cloudflare_text(messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024,
                                 url: str = None, token: str = None, thinking: Optional[bool] = None):
    """
    Streamma la risposta da Cloudflare Workers AI (SSE).
    - `token` ora viene davvero usato (prima era ignorato e andava sempre il token testo).
    - `thinking`: None = non invia nulla (giusto per Mistral 7B, che non conosce
      chat_template_kwargs); True/False = invia enable_thinking (solo per Gemma).
    """
    headers = {
        "Authorization": f"Bearer {token or CLOUDFLARE_TEXT_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": thinking}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None)) as client:
        async with client.stream("POST", url or CLOUDFLARE_TEXT_URL, headers=headers, json=payload) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                raise RuntimeError(
                    f"Cloudflare Workers AI error {response.status_code}: {error_body.decode(errors='ignore')}"
                )

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Supporta sia il formato OpenAI (choices/delta) sia quello nativo (response).
                # "reasoning_content" viene scartato: non deve mai finire nel testo mostrato.
                choices = data.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                chunk = delta.get("content") or data.get("response") or ""
                if chunk:
                    yield chunk


async def call_cloudflare_text(messages: List[dict], temperature: float = CLOUDFLARE_TEXT_TEMPERATURE,
                               max_tokens: int = CLOUDFLARE_TEXT_MAX_TOKENS) -> str:
    """Wrapper non-streaming: accumula tutto il testo (serve al job store)."""
    cf_messages = _normalize_roles(_to_cloudflare_messages(messages, vision=CLOUDFLARE_TEXT_VISION))
    chunks = []
    async for piece in stream_cloudflare_text(cf_messages, temperature=temperature, max_tokens=max_tokens,
                                              thinking=CLOUDFLARE_TEXT_THINKING):
        chunks.append(piece)
    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("Cloudflare Workers AI ha restituito una risposta vuota")
    return text


# =====================================================================================
# NVIDIA NIM - CODICE
# =====================================================================================
if not NVIDIA_API_KEY:
    logger.error("⚠️  NVIDIA_API_KEY NON CONFIGURATA — nessuna richiesta di codice funzionera'.")
else:
    _masked = NVIDIA_API_KEY[:8] + "..." + NVIDIA_API_KEY[-4:] if len(NVIDIA_API_KEY) > 12 else "***"
    logger.info(f"NVIDIA_API_KEY caricata correttamente ({_masked})")

_nvidia_client: Optional[AsyncOpenAI] = None
NVIDIA_RPS = float(os.environ.get('NVIDIA_RPS', '0.55'))
nvidia_limiter = RateLimiter(rps=NVIDIA_RPS)
nvidia_code_concurrency = asyncio.Semaphore(2)


def _get_nvidia_client() -> AsyncOpenAI:
    global _nvidia_client
    if _nvidia_client is None:
        if not NVIDIA_API_KEY:
            raise RuntimeError("NVIDIA_API_KEY non configurata")
        _nvidia_client = AsyncOpenAI(
            base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY, max_retries=0,
            timeout=httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=30.0),
        )
    return _nvidia_client


def _timeout_for_model(model: str) -> httpx.Timeout:
    if model in (NVIDIA_CODE_MODEL, NVIDIA_CODE_MODEL_FALLBACK):
        return httpx.Timeout(connect=15.0, read=None, write=60.0, pool=60.0)
    return httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=30.0)


def _concurrency_for_model(model: str) -> asyncio.Semaphore:
    return nvidia_code_concurrency


def _extra_body_for_model(model: str, thinking: bool) -> dict:
    if model.startswith("openai/gpt-oss"):
        return {}
    if "glm" in model:
        return {"chat_template_kwargs": {"enable_thinking": thinking}}
    body = {"chat_template_kwargs": {"thinking": thinking}}
    if model in [NVIDIA_CODE_MODEL, NVIDIA_CODE_MODEL_FALLBACK] and thinking:
        body["reasoning_effort"] = "high"
    return body


# =====================================================================================
# ZALVION AI - FIX NVIDIA NIM (v2)
#   1) stream bloccati / attese infinite / tentativi a catena  (timeout e deadline)
#   2) risposte di codice TRONCATE: rilevamento finish_reason="length" + continuazione
#      automatica, cosi' i siti grandi arrivano interi e la live preview funziona
#
# SOSTITUISCE in server.py queste 3 funzioni (cancella le vecchie per intero):
#     call_nvidia_stream
#     call_nvidia
#     call_nvidia_code_with_fallback
# e applica le 2 modifiche a _run_ai_job in fondo a questo file.
# Tutto il resto (client, limiter, semaforo, _extra_body_for_model, Cloudflare,
# Gemini) resta com'e'.
#
# Serve `import re` in cima a server.py (se non c'e' gia').
#
# VARIABILI D'AMBIENTE (tutte opzionali, hanno un default):
#   NVIDIA_FIRST_BYTE_TIMEOUT   300   s per ricevere la risposta HTTP iniziale
#   NVIDIA_IDLE_TIMEOUT         240   s massimi SENZA nessun chunk (reasoning incluso)
#   NVIDIA_ATTEMPT_SECONDS      900   s massimi per UNA chiamata (15 min)
#   NVIDIA_JOB_SECONDS          1650  s massimi per tutto il job di codice (27,5 min)
#   NVIDIA_MAX_CONTINUATIONS    6     quante volte puo' "continuare" una risposta troncata
#   NVIDIA_MIN_CONTINUE_SECONDS 60    sotto questo tempo residuo non parte una continuazione
# Il job finisce SEMPRE prima dei 30 minuti del timeout lato frontend.
# =====================================================================================

NVIDIA_FIRST_BYTE_TIMEOUT = int(os.environ.get("NVIDIA_FIRST_BYTE_TIMEOUT", "300"))
NVIDIA_IDLE_TIMEOUT = int(os.environ.get("NVIDIA_IDLE_TIMEOUT", "240"))
NVIDIA_ATTEMPT_SECONDS = int(os.environ.get("NVIDIA_ATTEMPT_SECONDS", "900"))
NVIDIA_JOB_SECONDS = int(os.environ.get("NVIDIA_JOB_SECONDS", "1650"))
NVIDIA_MAX_CONTINUATIONS = int(os.environ.get("NVIDIA_MAX_CONTINUATIONS", "6"))
NVIDIA_MIN_CONTINUE_SECONDS = int(os.environ.get("NVIDIA_MIN_CONTINUE_SECONDS", "60"))

NVIDIA_CONTINUE_PROMPT = (
    "Continua ESATTAMENTE dal punto in cui ti sei interrotto, anche a meta' di una riga o di una parola. "
    "Non ripetere nulla di quanto hai gia' scritto, non salutare, non aggiungere introduzioni o commenti, "
    "non riaprire il blocco di codice: scrivi solo il seguito."
)
NVIDIA_TRUNCATED_NOTE = "\n\n_La risposta è stata interrotta perché troppo lunga. Scrivi «continua» per proseguire._"

# max_tokens massimo accettato da ogni modello, imparato dagli errori 400 (si azzera al riavvio)
_NVIDIA_TOKEN_CAPS: dict = {}
_FENCE_RE = re.compile(r"^[ \t]*```", re.M)


class NvidiaStalledError(RuntimeError):
    """Il modello non produce piu' nulla, o ha superato il tempo massimo del tentativo."""


def _has_open_fence(text: str) -> bool:
    """True se c'e' un blocco di codice ``` aperto e mai chiuso (risposta tagliata)."""
    return len(_FENCE_RE.findall(text)) % 2 == 1


def _parse_token_cap(exc: Exception, current: int) -> Optional[int]:
    """Prova a leggere il tetto di max_tokens dal messaggio d'errore 400 di NVIDIA."""
    nums = [int(n) for n in re.findall(r"\d{4,6}", str(exc))]
    smaller = [n for n in nums if 2048 <= n < current]
    return max(smaller) if smaller else None


def _stitch_continuation(prev: str, more: str) -> str:
    """Unisce il testo gia' scritto col seguito, togliendo ripetizioni e fence riaperti."""
    # il modello a volte riapre il blocco di codice: ```html, ```js ...
    if _has_open_fence(prev):
        stripped = more.lstrip("\n")
        if stripped.startswith("```"):
            more = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    # il modello a volte ripete le ultime righe: cerca la sovrapposizione piu' lunga
    for k in range(min(400, len(prev), len(more)), 19, -1):
        if prev.endswith(more[:k]):
            more = more[k:]
            break
    return prev + more


async def call_nvidia_stream(messages: List[dict], model: str, temperature: float = 0.7,
                             max_tokens: int = 16384, thinking: bool = False,
                             max_seconds: Optional[int] = None, info: Optional[dict] = None):
    """
    Stream verso NVIDIA (obbligatorio: il gateway chiude le richieste non-stream dopo
    ~300s). Async generator che emette solo il testo visibile.

    Protezioni contro le attese infinite:
      1. la risposta HTTP iniziale deve arrivare entro NVIDIA_FIRST_BYTE_TIMEOUT
      2. tra un chunk e il successivo (reasoning compreso) non passano piu' di
         NVIDIA_IDLE_TIMEOUT secondi
      3. un singolo tentativo non dura piu' di `max_seconds`
    In tutti e tre i casi: NvidiaStalledError, stream chiuso, slot del semaforo liberato.

    `info` (dict opzionale) viene riempito a fine stream con finish_reason,
    content_chars e reasoning_chars: finish_reason == "length" = risposta TRONCATA.
    """
    client = _get_nvidia_client()
    openai_messages = _to_openai_messages(messages)
    concurrency = _concurrency_for_model(model)
    max_seconds = max_seconds or NVIDIA_ATTEMPT_SECONDS

    async with concurrency:
        await nvidia_limiter.wait()
        started = time.monotonic()
        reasoning_chars = 0
        content_chars = 0
        first_token_at = None
        finish_reason = None

        extra_body = _extra_body_for_model(model, thinking)
        create_kwargs = dict(
            model=model, messages=openai_messages, temperature=temperature, top_p=0.95,
            max_tokens=max_tokens, stream=True, timeout=_timeout_for_model(model),
        )
        if extra_body:
            create_kwargs["extra_body"] = extra_body

        logger.info(f"NVIDIA NIM: chiamata a '{model}' - max_tokens={max_tokens}, thinking={thinking}, "
                    f"stream=True, limite tentativo {max_seconds}s")
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(**create_kwargs),
                timeout=min(NVIDIA_FIRST_BYTE_TIMEOUT, max_seconds),
            )
        except asyncio.TimeoutError:
            raise NvidiaStalledError(
                f"'{model}' non ha risposto entro {min(NVIDIA_FIRST_BYTE_TIMEOUT, max_seconds)}s "
                f"(coda piena o gateway NVIDIA bloccato)"
            )
        logger.info(f"NVIDIA NIM: risposta HTTP da '{model}' dopo {time.monotonic() - started:.1f}s")

        iterator = response.__aiter__()
        last_heartbeat = time.monotonic()
        try:
            while True:
                remaining = max_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise NvidiaStalledError(
                        f"'{model}' ha superato il limite di {max_seconds}s "
                        f"({content_chars} car. visibili, {reasoning_chars} di reasoning)"
                    )
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=min(NVIDIA_IDLE_TIMEOUT, remaining))
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    if remaining <= NVIDIA_IDLE_TIMEOUT:
                        # e' scaduto il tempo massimo del tentativo, non il silenzio del modello
                        raise NvidiaStalledError(
                            f"'{model}' ha superato il limite di {max_seconds}s "
                            f"({content_chars} car. visibili, {reasoning_chars} di reasoning)"
                        )
                    raise NvidiaStalledError(
                        f"'{model}' non invia dati da piu' di {NVIDIA_IDLE_TIMEOUT}s "
                        f"({content_chars} car. visibili, {reasoning_chars} di reasoning)"
                    )

                if time.monotonic() - last_heartbeat >= 60:
                    last_heartbeat = time.monotonic()
                    logger.info(f"NVIDIA NIM: '{model}' ancora in corso dopo {time.monotonic() - started:.0f}s "
                                f"({content_chars} car. visibili, {reasoning_chars} di reasoning)")

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                fr = getattr(choice, "finish_reason", None)
                if fr:
                    finish_reason = fr
                delta = choice.delta
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reasoning:
                    reasoning_chars += len(reasoning)
                    continue
                if delta.content:
                    if first_token_at is None:
                        first_token_at = time.monotonic() - started
                        logger.info(f"NVIDIA NIM: primo token da '{model}' dopo {first_token_at:.1f}s "
                                    f"(reasoning: {reasoning_chars} car.)")
                    content_chars += len(delta.content)
                    yield delta.content
        finally:
            try:
                await response.close()
            except Exception:
                pass

        if info is not None:
            info.update(finish_reason=finish_reason, content_chars=content_chars, reasoning_chars=reasoning_chars)
        elapsed = time.monotonic() - started
        if content_chars == 0 and reasoning_chars > 0:
            logger.warning(f"NVIDIA NIM: '{model}' ha esaurito max_tokens={max_tokens} in reasoning "
                           f"({reasoning_chars} car.) - ZERO output visibile.")
        if finish_reason == "length":
            logger.warning(f"NVIDIA NIM: '{model}' TRONCATO da max_tokens={max_tokens} "
                           f"({content_chars} car. visibili, {reasoning_chars} di reasoning)")
        logger.info(f"NVIDIA NIM: stream completato per '{model}' in {elapsed:.1f}s "
                    f"({content_chars} car. visibili, {reasoning_chars} reasoning, finish_reason={finish_reason})")


async def call_nvidia(messages: List[dict], model: str, temperature: float = 0.7,
                      max_tokens: int = 16384, thinking: bool = False, max_retries: int = 3,
                      deadline: Optional[float] = None, info: Optional[dict] = None) -> str:
    """
    Una chiamata completa (con retry) a NVIDIA: restituisce il testo di UNA risposta.
    - `deadline` (istante time.monotonic()): non parte nessun tentativo oltre quel limite.
    - Stallo (NvidiaStalledError): niente retry sullo stesso modello, tocca al fallback.
    - Risposta vuota (token finiti nel reasoning): il tentativo dopo parte senza thinking.
    - Errore 400 su max_tokens: legge il tetto dal messaggio (o dimezza), NON conta come
      tentativo, e ricorda il tetto del modello per le richieste successive.
    - `info` riceve finish_reason ecc. (vedi call_nvidia_stream).
    """
    if not NVIDIA_API_KEY:
        logger.error(f"NVIDIA NIM: richiesta bloccata - chiave assente (model={model})")
        raise RuntimeError("NVIDIA_API_KEY non configurata")

    current_max_tokens = min(max_tokens, _NVIDIA_TOKEN_CAPS.get(model, max_tokens))
    current_thinking = thinking
    downshifted = False
    downshifts = 0
    last_exc: Optional[Exception] = None
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        attempt_seconds = NVIDIA_ATTEMPT_SECONDS
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining < 30:
                logger.warning(f"NVIDIA NIM: tempo massimo esaurito per '{model}', nessun altro tentativo")
                break
            attempt_seconds = min(NVIDIA_ATTEMPT_SECONDS, int(remaining))

        logger.info(f"NVIDIA NIM: richiesta a '{model}' (tentativo {attempt}/{max_retries}, "
                    f"thinking={current_thinking}, max_tokens={current_max_tokens}, limite {attempt_seconds}s)")
        try:
            attempt_info: dict = {}
            chunks = []
            async for piece in call_nvidia_stream(messages, model, temperature, current_max_tokens,
                                                  current_thinking, max_seconds=attempt_seconds,
                                                  info=attempt_info):
                chunks.append(piece)
            text = "".join(chunks)
            if not text.strip():
                raise RuntimeError(f"NVIDIA NIM '{model}' ha restituito una risposta vuota")
            if downshifted:
                _NVIDIA_TOKEN_CAPS[model] = current_max_tokens
                logger.info(f"NVIDIA NIM: tetto max_tokens di '{model}' = {current_max_tokens} (memorizzato)")
            if info is not None:
                info.update(attempt_info)
            return text
        except NvidiaStalledError as e:
            logger.warning(f"NVIDIA NIM: stallo su '{model}', niente altri tentativi sullo stesso modello: {e}")
            raise
        except openai.AuthenticationError as e:
            logger.error(f"NVIDIA NIM: 401 - chiave sbagliata o revocata (model={model}): {e}")
            raise RuntimeError(f"NVIDIA API key non valida o revocata: {e}") from e
        except openai.BadRequestError as e:
            if _is_max_tokens_error(e) and current_max_tokens > 2048 and downshifts < 6:
                new_max = _parse_token_cap(e, current_max_tokens) or max(current_max_tokens // 2, 2048)
                logger.warning(f"NVIDIA NIM: max_tokens={current_max_tokens} rifiutato da '{model}' (400), riprovo con {new_max}")
                current_max_tokens = new_max
                downshifted = True
                downshifts += 1
                attempt -= 1          # non conta come tentativo
                last_exc = e
                continue
            logger.error(f"NVIDIA NIM: 400 (model={model}): {e}")
            raise RuntimeError(f"NVIDIA API richiesta non valida: {e}") from e
        except openai.RateLimitError as e:
            last_exc = e
            if attempt < max_retries:
                wait_s = min(2 ** (attempt - 1) * 2, 20)
                logger.warning(f"NVIDIA NIM 429 (model={model}), attesa {wait_s}s (tentativo {attempt}/{max_retries})")
                await asyncio.sleep(wait_s)
                continue
            break
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            last_exc = e
            if attempt < max_retries:
                logger.warning(f"NVIDIA NIM: connessione/timeout (model={model}), riprovo: {e}")
                await asyncio.sleep(2)
                continue
            break
        except openai.InternalServerError as e:
            last_exc = e
            if attempt < max_retries:
                logger.warning(f"NVIDIA NIM: errore 5xx (model={model}), riprovo: {e}")
                await asyncio.sleep(3)
                continue
            break
        except openai.APIStatusError as e:
            logger.error(f"NVIDIA NIM: errore {e.status_code} (model={model}): {e.message}")
            last_exc = e
            break
        except RuntimeError as e:
            # risposta vuota: riprova, ma senza thinking (i token erano finiti nel reasoning)
            last_exc = e
            if current_thinking:
                current_thinking = False
                logger.warning(f"NVIDIA NIM: risposta vuota da '{model}', il prossimo tentativo parte SENZA thinking")
            if attempt < max_retries:
                continue
            break

    raise RuntimeError(f"NVIDIA NIM (model={model}) non raggiungibile dopo {max_retries} tentativi: {last_exc}")


async def call_nvidia_continued(messages: List[dict], model: str, temperature: float = 1.0,
                                max_tokens: int = 16384, thinking: bool = True,
                                deadline: Optional[float] = None) -> str:
    """
    Come call_nvidia, ma se la risposta viene TRONCATA (finish_reason == "length") chiede
    al modello di continuare, fino a NVIDIA_MAX_CONTINUATIONS volte, e cuce i pezzi.
    - le continuazioni partono SENZA thinking, cosi' i token vanno tutti al codice;
    - se una continuazione fallisce o il tempo finisce, si restituisce quanto scritto
      finora (meglio un sito quasi completo di un errore);
    - un blocco ``` rimasto aperto viene chiuso, cosi' la live preview riesce a leggerlo;
    - se alla fine e' ancora troncata, si aggiunge NVIDIA_TRUNCATED_NOTE.
    """
    info: dict = {}
    text = await call_nvidia(messages, model, temperature, max_tokens, thinking,
                             deadline=deadline, info=info)
    rounds = 0
    errored = False
    while info.get("finish_reason") == "length" and rounds < NVIDIA_MAX_CONTINUATIONS:
        if deadline is not None and deadline - time.monotonic() < NVIDIA_MIN_CONTINUE_SECONDS:
            logger.warning(f"NVIDIA NIM: '{model}' troncato e tempo quasi finito, mi fermo a {len(text)} caratteri")
            break
        rounds += 1
        logger.info(f"NVIDIA NIM: '{model}' troncato (length), continuazione {rounds}/{NVIDIA_MAX_CONTINUATIONS} "
                    f"- {len(text)} caratteri finora")
        cont_messages = list(messages) + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": NVIDIA_CONTINUE_PROMPT},
        ]
        info = {}
        try:
            more = await call_nvidia(cont_messages, model, temperature, max_tokens, thinking=False,
                                     max_retries=2, deadline=deadline, info=info)
        except Exception as e:
            logger.warning(f"NVIDIA NIM: continuazione {rounds} fallita ({e}), restituisco i {len(text)} caratteri gia' scritti")
            errored = True
            break
        text = _stitch_continuation(text, more)

    truncated = errored or info.get("finish_reason") == "length"
    if truncated:
        if _has_open_fence(text):
            text += "\n```"
        text += NVIDIA_TRUNCATED_NOTE
        logger.warning(f"NVIDIA NIM: risposta di '{model}' ancora incompleta dopo {rounds} continuazioni ({len(text)} caratteri)")
    elif rounds:
        logger.info(f"NVIDIA NIM: risposta di '{model}' completata con {rounds} continuazioni ({len(text)} caratteri)")
    return text


async def call_nvidia_code_with_fallback(messages: List[dict], max_tokens: int) -> tuple:
    """
    Prova NVIDIA_CODE_MODEL con al massimo l'80% del tempo totale (NVIDIA_JOB_SECONDS);
    se fallisce o si blocca prima di scrivere qualcosa, passa a NVIDIA_CODE_MODEL_FALLBACK
    con il tempo che resta. In totale non supera mai NVIDIA_JOB_SECONDS.
    """
    started = time.monotonic()
    job_deadline = started + NVIDIA_JOB_SECONDS
    primary_deadline = started + NVIDIA_JOB_SECONDS * 0.8
    try:
        content = await call_nvidia_continued(
            messages, model=NVIDIA_CODE_MODEL, temperature=1.0,
            max_tokens=max_tokens, thinking=True, deadline=primary_deadline,
        )
        return content, NVIDIA_CODE_MODEL
    except Exception as primary_exc:
        logger.warning(
            f"NVIDIA NIM: modello primario '{NVIDIA_CODE_MODEL}' fallito dopo {time.monotonic() - started:.0f}s, "
            f"passo al fallback '{NVIDIA_CODE_MODEL_FALLBACK}': {primary_exc}"
        )
        content = await call_nvidia_continued(
            messages, model=NVIDIA_CODE_MODEL_FALLBACK, temperature=1.0,
            max_tokens=max_tokens, thinking=True, deadline=job_deadline,
        )
        return content, NVIDIA_CODE_MODEL_FALLBACK


# =====================================================================================
# MODIFICHE A _run_ai_job (2 punti)
# =====================================================================================
# 1) nel ramo `if is_code:` sostituisci la chiamata con:
#
#        if is_code:
#            content, provider_label = await asyncio.wait_for(
#                call_nvidia_code_with_fallback(messages, max_tokens=NVIDIA_CODE_MAX_TOKENS),
#                timeout=NVIDIA_JOB_SECONDS + 120,   # rete di sicurezza, include l'attesa in coda
#            )
#
# 2) nel blocco `except Exception as e:` in fondo, sostituisci le righe dell'errore con:
#
#        except Exception as e:
#            logger.error(f"AI job error (job {job_id}): {e}")
#            job = _ai_jobs.get(job_id)
#            if job is not None:
#                if isinstance(e, (NvidiaStalledError, asyncio.TimeoutError)):
#                    msg = "Il modello ha impiegato troppo tempo a rispondere. Riprova tra poco."
#                else:
#                    msg = "Error generating with Zalvion AI"
#                _ai_jobs[job_id] = {**job, "status": "error", "error": msg}
# =====================================================================================


# =====================================================================================
# IMMAGINI: moderazione + Flux
# =====================================================================================
async def is_unsafe_image_prompt(prompt: str) -> bool:
    """
    Filtro di sicurezza sui prompt immagine, via Gemma. Fail-safe: se la
    classificazione fallisce, BLOCCA (meglio un falso positivo che un falso negativo).
    """
    if not prompt or not prompt.strip():
        return False
    classify_messages = [
        {
            "role": "system",
            "content": (
                "Rispondi SOLO con true o false, nient'altro. "
                "Questo prompt per un generatore di immagini richiede contenuto "
                "sessuale, nudità, pornografico, o comunque esplicito? Rispondi "
                "true anche se la richiesta è ambigua, allusiva, o cerca di "
                "aggirare il divieto con eufemismi, e anche se il soggetto "
                "potrebbe essere un minore in qualsiasi contesto inappropriato. "
                "Altrimenti rispondi false."
            ),
        },
        {"role": "user", "content": prompt[:1000]},
    ]
    try:
        chunks = []
        async for piece in stream_cloudflare_text(
            classify_messages, temperature=0.0, max_tokens=5,
            url=CLOUDFLARE_TEXT_URL, token=CLOUDFLARE_TEXT_API_TOKEN, thinking=False,
        ):
            chunks.append(piece)
        answer = "".join(chunks).strip().lower()
        logger.info(f"Moderazione immagine — prompt: '{prompt[:80]}' → risposta classificatore: '{answer}'")
        return not answer.startswith("false")
    except Exception as e:
        logger.warning(f"Moderazione immagine fallita, blocco per sicurezza: {e}")
        return True


async def call_cloudflare_flux_image(prompt: str, timeout: float = 90.0, max_retries: int = 3):
    """Flux 1 [schnell] sull'account IMMAGINI. Restituisce (bytes, content_type)."""
    if not CLOUDFLARE_IMAGE_ACCOUNT_ID or not CLOUDFLARE_IMAGE_API_TOKEN:
        raise RuntimeError("CLOUDFLARE_IMAGE_ACCOUNT_ID / CLOUDFLARE_IMAGE_API_TOKEN non configurate")
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_IMAGE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
    headers = {"Authorization": f"Bearer {CLOUDFLARE_IMAGE_API_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt[:2048],
        "steps": CLOUDFLARE_IMAGE_STEPS,
    }

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
            if r.status_code in (429, 502, 503, 504) and attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Cloudflare Workers AI {r.status_code}: {r.text[:500]}")
            data = r.json()
            if not data.get("success", False):
                raise RuntimeError(f"Cloudflare Workers AI errore: {data.get('errors')}")
            return base64.b64decode(data["result"]["image"]), "image/jpeg"
        except (httpx.RequestError, KeyError, IndexError, TypeError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))
        except RuntimeError as e:
            last_exc = e
            break
    raise RuntimeError(f"Cloudflare Workers AI (Flux, immagini) non raggiungibile dopo {max_retries} tentativi: {last_exc}")


# =====================================================================================
# ALLEGATI: vision per le immagini, estrazione locale per i PDF
# =====================================================================================
async def describe_image_with_vision(b64_image: str, timeout: float = 45.0) -> str:
    """
    Descrive un'immagine con Llama 3.2 11B Vision su Cloudflare Workers AI.
    NB: al primo utilizzo va accettata UNA VOLTA la licenza Meta (prompt "agree"
    sull'endpoint del modello) - a mano, non nel codice dell'app.
    """
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN non configurate")
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_VISION_MODEL}"
    headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}
    mime = _guess_image_mime(b64_image)  # prima era sempre image/jpeg
    payload = {
        "messages": [
            {"role": "system", "content": "You are an assistant that describes images accurately and in detail, including any visible text."},
            {"role": "user", "content": [
                {"type": "text", "text": "Describe this image in detail."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64_image}"}},
            ]},
        ],
        "max_tokens": 800,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudflare Vision {r.status_code}: {r.text[:300]}")
    data = r.json()
    result = data.get("result", {})
    if isinstance(result, dict):
        return result.get("response") or result.get("description") or ""
    return str(result)


async def enrich_attachments_with_ai_analysis(body: ChatGenerateBody, skip_images: bool = False) -> None:
    """
    Trasforma immagini/PDF dell'ultimo messaggio utente in allegati kind="file" con
    testo pronto. Se un'analisi fallisce l'allegato resta com'era (degrado controllato).
    Le analisi girano in parallelo.
    """
    last_user = next((m for m in reversed(body.messages) if m.role == "user"), None)
    if not last_user or not last_user.attachments:
        return

    async def _process(att):
        try:
            if att.kind == "image" and att.b64 and not skip_images:
                description = await describe_image_with_vision(att.b64)
                if description:
                    att.kind = "file"
                    att.text = f'[Descrizione automatica dell\'immagine "{att.name}"]\n{description}'
                    att.b64 = ""
            elif att.kind == "pdf" and att.b64:
                extracted = await extract_pdf_text(att.b64)
                if extracted.strip():
                    att.kind = "file"
                    att.text = f'[Testo estratto dal PDF "{att.name}"]\n{extracted}'
                    att.b64 = ""
        except Exception as e:
            logger.warning(f"Analisi allegato '{att.name}' fallita, resta non disponibile: {e}")

    await asyncio.gather(*[_process(a) for a in last_user.attachments])


# =====================================================================================
# RICERCA WEB (Exa)
# =====================================================================================
async def exa_web_search(query: str, num_results: int = 5) -> str:
    if not exa_client or not query.strip():
        return ""
    try:
        results = await exa_client.search(
            query.strip()[:300], type="auto", num_results=num_results,
            contents={"highlights": True},
        )
        if not results.results:
            return ""
        lines = []
        for r in results.results:
            highlight = r.highlights[0] if getattr(r, "highlights", None) else ""
            lines.append(f"- {r.title}: {highlight} (fonte: {r.url})")
        today = now_utc().strftime("%A, %d %B %Y")
        results_text = "\n".join(lines)
        # Testo volutamente corto: i modelli piccoli (Mistral 7B) si perdono con
        # prompt di contesto lunghi e tendono a scivolare in inglese.
        return f"""[WEB SEARCH CONTEXT - internal, never repeat to the user]
Today's date: {today}. Trust this date and the results below over your training data for current events, prices, versions, people's roles.
Rules: use the results only if relevant, otherwise ignore them; if sources disagree say so and prefer the most recent; if results don't fully answer, say what is uncertain instead of inventing; name the source naturally when you use it; never mention this search process; for stable facts prefer your own knowledge; reply in the language requested at the end of the user message.

Results:
{results_text}
[END WEB SEARCH CONTEXT]"""
    except Exception as e:
        logger.error(f"Exa web search error: {e}")
        return ""


# =====================================================================================
# AUTH: OTP via email
# =====================================================================================
@api_router.post("/auth/otp/request")
async def request_otp(body: OTPRequest):
    code = f"{random.randint(0, 999999):06d}"
    await sb_delete("otps", email=body.email)
    await sb_insert("otps", {
        "email": body.email, "code_hash": hash_code(code),
        "expires_at": (now_utc() + timedelta(minutes=10)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#FDFDF9;border:1px solid #EBE8E0;border-radius:16px">
      <h1 style="color:#D97251;font-size:24px;margin:0 0 8px">Zalvion AI</h1>
      <p style="color:#5C5954;font-size:15px">Your verification code is:</p>
      <div style="font-size:38px;font-weight:700;letter-spacing:10px;color:#2D2A26;background:#F3F2EC;padding:18px;text-align:center;border-radius:12px;margin:16px 0">{code}</div>
      <p style="color:#5C5954;font-size:13px">This code expires in 10 minutes.</p>
    </div>"""
    try:
        await asyncio.to_thread(resend.Emails.send, {
            "from": SENDER_EMAIL, "to": [body.email],
            "subject": f"{code} is your Zalvion AI verification code", "html": html,
        })
    except Exception as e:
        logger.error(f"Resend send failed: {e}")
        raise HTTPException(status_code=500, detail="Could not send the verification email.")
    return {"status": "sent"}


@api_router.post("/auth/otp/verify")
async def verify_otp(body: OTPVerify, response: Response):
    otp = await sb_select_one("otps", email=body.email)
    if not otp:
        raise HTTPException(status_code=400, detail="No code requested for this email")
    expires_at = datetime.fromisoformat(otp["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=400, detail="Code expired, request a new one")
    if otp["code_hash"] != hash_code(body.code.strip()):
        raise HTTPException(status_code=400, detail="Invalid code")
    await sb_delete("otps", email=body.email)
    user = await upsert_user(body.email, body.email.split("@")[0])
    token = await create_session(user.user_id)
    set_session_cookie(response, token)
    return {"user": user.model_dump(), "token": token}


# =====================================================================================
# AUTH: Google
# =====================================================================================
@api_router.post("/auth/google/verify")
async def google_verify(body: GoogleTokenBody, response: Response):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID non configurato sul backend")
    try:
        idinfo = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            body.credential, google_auth_requests.Request(), GOOGLE_CLIENT_ID,
        )
    except ValueError as e:
        logger.warning(f"Google token non valido: {e}")
        raise HTTPException(status_code=401, detail="Token Google non valido")
    if not idinfo.get("email_verified", False):
        raise HTTPException(status_code=401, detail="Email Google non verificata")
    user = await upsert_user(idinfo["email"], idinfo.get("name", ""), idinfo.get("picture"))
    token = await create_session(user.user_id)
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
        await sb_delete("user_sessions", session_token=token)
    response.delete_cookie("session_token", path="/")
    return {"status": "ok"}


# =====================================================================================
# GENERAZIONE AI
# =====================================================================================
async def is_code_request(body: ChatGenerateBody) -> bool:
    """
    Router: chiede a Gemma (Cloudflare) se l'ultimo messaggio utente richiede codice.
    Se la classificazione fallisce -> False (ramo testo), per non caricare NVIDIA.
    """
    if not body.messages:
        return False

    last_user_idx = next((i for i in range(len(body.messages) - 1, -1, -1)
                          if body.messages[i].role == "user"), None)
    if last_user_idx is None:
        return False

    history = body.messages[max(0, last_user_idx - 2): last_user_idx + 1]
    convo_lines = []
    for m in history:
        role_label = "Utente" if m.role == "user" else "Assistente"
        convo_lines.append(f"{role_label}: {(m.content or '')[:500]}")
    convo_text = "\n".join(convo_lines)

    last_user = body.messages[last_user_idx]
    attachment_names = ", ".join(att.name for att in last_user.attachments if att.name)
    if attachment_names:
        convo_text += f"\n[File allegati nell'ultimo messaggio: {attachment_names}]"

    if not convo_text.strip():
        return False

    classify_messages = [
        {
            "role": "system",
            "content": (
                "Rispondi SOLO con la parola true oppure la parola false, nient'altro. "
                "L'ultimo messaggio dell'Utente in questa conversazione sta chiedendo di scrivere, "
                "generare, correggere, spiegare riga per riga o modificare del codice sorgente / "
                "uno script / un programma? Se e' una domanda generale, una richiesta creativa "
                "(storie, testi, idee), una domanda di cultura generale o qualsiasi cosa che non "
                "richieda di produrre codice, rispondi false."
            ),
        },
        {"role": "user", "content": convo_text[:2000]},
    ]

    try:
        chunks = []
        async for piece in stream_cloudflare_text(
            classify_messages, temperature=0.0, max_tokens=5,
            url=CLOUDFLARE_TEXT_URL, token=CLOUDFLARE_TEXT_API_TOKEN, thinking=False,
        ):
            chunks.append(piece)
        answer = "".join(chunks).strip().lower()
        return answer.startswith("true")
    except Exception as e:
        logger.warning(f"Classificazione is_code_request fallita, uso default False (ramo testo): {e}")
        return False


def build_messages(body: ChatGenerateBody, search_context: str = "") -> List[dict]:
    lang_name = LANG_NAMES.get(body.language, "English")
    reminder = LANG_REMINDERS.get(body.language, f"Reply exclusively in {lang_name}.")
    messages: List[dict] = []

    for m in body.messages[-MAX_HISTORY_MESSAGES:]:
        parts = []
        if m.content:
            parts.append({"type": "text", "text": m.content})
        for att in m.attachments:
            if att.kind == "image" and att.b64:
                parts.append({"type": "image_url", "image_url": f"data:{_guess_image_mime(att.b64)};base64,{att.b64}"})
            elif att.kind == "pdf" and att.b64:
                parts.append({"type": "document_url", "document_url": ""})
            elif att.kind == "file" and att.text:
                parts.append({"type": "text", "text": f"\n\n[Allegato: {att.name}]\n```\n{att.text}\n```"})
        if not parts:
            parts = [{"type": "text", "text": " "}]
        if len(parts) == 1 and parts[0]["type"] == "text":
            messages.append({"role": m.role, "content": parts[0]["text"]})
        else:
            messages.append({"role": m.role, "content": parts})

    # Si parte sempre da un messaggio 'user'
    first_user = next((i for i, m in enumerate(messages) if m["role"] == "user"), None)
    if first_user is None:
        return messages
    messages = messages[first_user:]
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")

    # Contesto web nell'ultimo messaggio utente (non come messaggio 'system')
    if search_context:
        messages[last_user]["content"] = _prepend_text(
            messages[last_user]["content"], f"{search_context}\n\n[User message]: "
        )
        # Promemoria di lingua solo se c'e' contesto web
        messages[last_user]["content"] = _append_text(
            messages[last_user]["content"], f"\n\n({reminder})"
        )

    # Istruzioni come scambio "finto" a inizio conversazione: user -> assistant
    sys_content = SYSTEM_PROMPT.format(lang=lang_name)
    ack = LANG_ACKS.get(body.language, "OK.")
    priming = [
        {"role": "user", "content": f"{sys_content}\n\n{reminder}"},
        {"role": "assistant", "content": ack},
    ]
    return priming + messages

# =====================================================================================
# JOB STORE PER GENERAZIONE ASINCRONA
# POST /ai/generate/start -> job_id subito; il client fa polling su
# GET /ai/generate/status/{job_id}. In-memory: va bene con UN solo worker uvicorn;
# con piu' worker servira' Redis/Supabase.
# =====================================================================================
_ai_jobs: dict = {}
_AI_JOB_TTL_SECONDS = 3 * 60 * 60  # 3 ore


def _cleanup_ai_jobs():
    now = time.monotonic()
    expired = [jid for jid, job in _ai_jobs.items() if now - job["created_at"] > _AI_JOB_TTL_SECONDS]
    for jid in expired:
        _ai_jobs.pop(jid, None)


# =====================================================================================
# ZALVION AI - FALLBACK/VISION SU GEMMA 4 26B (Google AI Studio / Gemini API)
#
# Usato in 2 casi (e solo in questi):
#   1) l'ultimo messaggio utente contiene immagini (e non e' una richiesta di codice)
#   2) Cloudflare risponde con rate limit / quota finita (429, errore 4006)
#
# Nessuna nuova dipendenza: usa httpx (gia' nel progetto).
# Il codice Cloudflare/NVIDIA esistente NON viene toccato, tranne:
#   - enrich_attachments_with_ai_analysis: +1 parametro opzionale (vedi PASSO 3)
#   - _run_ai_job e ai_generate_start: sostituite con le versioni qui sotto
#
# VARIABILI D'AMBIENTE (Render):
#   GEMINI_API_KEY      chiave di Google AI Studio (se assente, tutto resta com'e' ora)
#   GEMINI_MODEL        opzionale, default gemma-4-26b-a4b-it
#   GEMINI_RPM          opzionale, default 14  (limite reale 15, 1 di margine)
#   GEMINI_RPD          opzionale, default 1450 (limite reale 1500, margine)
#   GEMINI_MAX_TOKENS   opzionale, default 2048
# =====================================================================================

# ---- PASSO 1: aggiungi questi import in cima a server.py (se mancano) ---------------
# from collections import deque
# -------------------------------------------------------------------------------------

# ---- PASSO 2: incolla da qui in giu', DOPO call_cloudflare_text / describe_image_with_vision
#               e PRIMA di _run_ai_job (sostituendo _run_ai_job e ai_generate_start) ----

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemma-4-26b-a4b-it").strip()
GEMINI_RPM = int(os.environ.get("GEMINI_RPM", "14"))
GEMINI_RPD = int(os.environ.get("GEMINI_RPD", "1450"))
GEMINI_MAX_TOKENS = int(os.environ.get("GEMINI_MAX_TOKENS", "2048"))
GEMINI_ENABLED = bool(GEMINI_API_KEY)

if GEMINI_ENABLED:
    logger.info(f"Gemini API attiva: modello '{GEMINI_MODEL}', limiti locali {GEMINI_RPM} rpm / {GEMINI_RPD} rpd")
else:
    logger.warning("GEMINI_API_KEY non configurata: nessun supporto immagini via Gemini, nessun fallback sul 429 di Cloudflare.")


class _GeminiLimiter:
    """
    Rispetta in locale i limiti del piano gratuito (15 richieste/minuto, 1500/giorno)
    cosi' non arrivano nemmeno i 429 da Google. In-memory: valido con un solo worker
    uvicorn (come il job store). Il giorno di Google riparte a mezzanotte Pacific:
    qui si approssima con UTC-8 fisso (il margine su GEMINI_RPD copre l'ora di scarto).
    """
    def __init__(self, rpm: int, rpd: int):
        self.rpm = rpm
        self.rpd = rpd
        self._window = deque()
        self._day = None
        self._day_count = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _today() -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=-8)).strftime("%Y-%m-%d")

    async def acquire(self, max_wait: float = 20.0) -> None:
        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                today = self._today()
                if today != self._day:
                    self._day, self._day_count = today, 0
                if self._day_count >= self.rpd:
                    raise RuntimeError("Quota giornaliera Gemini esaurita")
                while self._window and now - self._window[0] >= 60.0:
                    self._window.popleft()
                if len(self._window) < self.rpm:
                    self._window.append(now)
                    self._day_count += 1
                    return
                wait = 60.0 - (now - self._window[0]) + 0.05
            if waited + wait > max_wait:
                raise RuntimeError("Limite al minuto Gemini raggiunto")
            await asyncio.sleep(wait)
            waited += wait


_gemini_limiter = _GeminiLimiter(GEMINI_RPM, GEMINI_RPD)


def _parse_data_uri(url) -> Optional[tuple]:
    """'data:image/png;base64,XXXX' -> ('image/png', 'XXXX'); altrimenti None."""
    if isinstance(url, dict):
        url = url.get("url", "")
    if not isinstance(url, str) or not url.startswith("data:") or ";base64," not in url:
        return None
    head, data = url.split(";base64,", 1)
    return (head[5:] or "image/jpeg"), data


def _to_gemini_contents(messages: List[dict]) -> List[dict]:
    """
    Converte i messaggi interni nel formato Gemini (contents/parts).
    - ruolo 'assistant' -> 'model'
    - le immagini viaggiano come inline_data SOLO nell'ultimo messaggio utente
      (quelle della cronologia diventano un segnaposto: risparmia banda e quota)
    - nessun system_instruction: il priming user/assistant di build_messages basta
      ed e' compatibile con qualsiasi modello Gemma
    """
    msgs = _normalize_roles(messages)
    if not msgs:
        raise RuntimeError("Nessun messaggio da inviare a Gemini")
    last_user = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=len(msgs) - 1)

    contents = []
    for i, m in enumerate(msgs):
        role = "user" if m["role"] == "user" else "model"
        content = m["content"]
        parts = []
        if isinstance(content, str):
            if content.strip():
                parts.append({"text": content})
        else:
            for p in content:
                if p["type"] == "text":
                    if p.get("text") and p["text"].strip():
                        parts.append({"text": p["text"]})
                elif p["type"] == "image_url":
                    parsed = _parse_data_uri(p.get("image_url"))
                    if parsed and i == last_user:
                        parts.append({"inline_data": {"mime_type": parsed[0], "data": parsed[1]}})
                    else:
                        parts.append({"text": "[immagine inviata in precedenza]"})
                elif p["type"] == "document_url":
                    parts.append({"text": "[Allegato PDF: non leggibile]"})
        if not parts:
            parts = [{"text": " "}]
        contents.append({"role": role, "parts": parts})
    return contents


async def call_gemini_text(messages: List[dict], temperature: float = None,
                           max_tokens: int = None, max_retries: int = 2) -> str:
    """Chiama Gemma su Gemini API (non-streaming, il job store fa gia' da buffer)."""
    if not GEMINI_ENABLED:
        raise RuntimeError("GEMINI_API_KEY non configurata")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "contents": _to_gemini_contents(messages),
        "generationConfig": {
            "temperature": CLOUDFLARE_TEXT_TEMPERATURE if temperature is None else temperature,
            "maxOutputTokens": max_tokens or GEMINI_MAX_TOKENS,
        },
    }

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        await _gemini_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
                r = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as e:
            last_exc = e
            logger.warning(f"Gemini: errore di rete (tentativo {attempt + 1}): {e}")
            await asyncio.sleep(2)
            continue

        if r.status_code in (500, 502, 503, 504):
            last_exc = RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
            logger.warning(f"Gemini: errore server {r.status_code} (tentativo {attempt + 1})")
            await asyncio.sleep(3)
            continue
        if r.status_code >= 400:
            # 429 / 400 / 401 / 403: inutile ritentare
            raise RuntimeError(f"Gemini API error {r.status_code}: {r.text[:500]}")

        data = r.json()
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise RuntimeError(f"Gemini ha bloccato la richiesta ({block})")
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini ha restituito zero candidati")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        # scarta eventuali parti di ragionamento ("thought": true)
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if not text:
            raise RuntimeError(f"Gemini ha restituito una risposta vuota (finishReason={candidates[0].get('finishReason')})")
        return text

    raise RuntimeError(f"Gemini non raggiungibile dopo {max_retries + 1} tentativi: {last_exc}")


def _is_cloudflare_rate_limit(exc: Exception) -> bool:
    """429 o quota giornaliera di Neuron esaurita (errore Cloudflare 4006)."""
    s = str(exc).lower()
    return ("error 429" in s or " 429" in s or "4006" in s
            or "too many requests" in s or "daily free allocation" in s)


async def _describe_images_in_messages(messages: List[dict]) -> List[dict]:
    """
    Fallback se Gemini fallisce su una richiesta con immagini: l'immagine dell'ultimo
    messaggio utente viene descritta con Llama Vision (come faceva prima) e il testo
    prosegue sul ramo Cloudflare. Le immagini della cronologia diventano segnaposto.
    """
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    out = []
    for i, m in enumerate(messages):
        c = m["content"]
        if not isinstance(c, list):
            out.append(m)
            continue
        new_parts = []
        for p in c:
            if p["type"] != "image_url":
                new_parts.append(p)
                continue
            desc = ""
            parsed = _parse_data_uri(p.get("image_url"))
            if parsed and i == last_user:
                try:
                    desc = await describe_image_with_vision(parsed[1])
                except Exception as e:
                    logger.warning(f"Descrizione immagine di fallback fallita: {e}")
            new_parts.append({"type": "text", "text": (
                f"[Descrizione automatica dell'immagine]\n{desc}" if desc else "[Allegato immagine: non analizzabile]"
            )})
        out.append({**m, "content": new_parts})
    return out


async def _run_ai_job(job_id: str, messages: List[dict], is_code: bool, user: User, use_gemini: bool = False):
    try:
        if is_code:
          content, provider_label = await asyncio.wait_for(
             call_nvidia_code_with_fallback(messages, max_tokens=NVIDIA_CODE_MAX_TOKENS),
             timeout=NVIDIA_JOB_SECONDS + 120,
         )
        elif use_gemini:
            # Input con immagini: Gemma/Gemini vede l'immagine davvero.
            try:
                content = await call_gemini_text(messages)
                provider_label = "gemini_gemma"
            except Exception as gem_exc:
                logger.warning(f"Gemini fallito su richiesta con immagini, ripiego su Llama Vision + Cloudflare: {gem_exc}")
                fallback_messages = await _describe_images_in_messages(messages)
                content = await call_cloudflare_text(fallback_messages)
                provider_label = "cloudflare_workers_ai"
        else:
            try:
                content = await call_cloudflare_text(messages)
                provider_label = "cloudflare_workers_ai"
            except Exception as cf_exc:
                if GEMINI_ENABLED and _is_cloudflare_rate_limit(cf_exc):
                    logger.warning(f"Cloudflare in rate limit/quota, passo a Gemini: {cf_exc}")
                    content = await call_gemini_text(messages)
                    provider_label = "gemini_gemma"
                else:
                    raise

        used = await get_usage_today(user.user_id)
        logger.info(f"AI job {job_id} completato con provider '{provider_label}'")
        job = _ai_jobs.get(job_id)
        if job is None:  # job scaduto/ripulito nel frattempo
            return
        _ai_jobs[job_id] = {
            **job,
            "status": "done",
            "content": content,
            "provider": provider_label,
            "usage_used": used,
            "usage_limit": daily_limit_for(user.plan),
        }
    except Exception as e:
         logger.error(f"AI job error (job {job_id}): {e}")
         job = _ai_jobs.get(job_id)
         if job is not None:
             if isinstance(e, (NvidiaStalledError, asyncio.TimeoutError)):
                 msg = "Il modello ha impiegato troppo tempo a rispondere. Riprova tra poco."
             else:
                 msg = "Error generating with Zalvion AI"
             _ai_jobs[job_id] = {**job, "status": "error", "error": msg}

@api_router.post("/ai/generate/start")
async def ai_generate_start(body: ChatGenerateBody, user: User = Depends(get_current_user)):
    """Avvia la generazione in background e risponde SUBITO con un job_id."""
    _cleanup_ai_jobs()

    last_user_msg = next((m for m in reversed(body.messages) if m.role == "user"), None)
    has_images = bool(last_user_msg and any(a.kind == "image" and a.b64 for a in last_user_msg.attachments))
    gemini_vision = GEMINI_ENABLED and has_images

    # Con Gemini le immagini NON vanno descritte da Llama: restano immagini vere.
    await enrich_attachments_with_ai_analysis(body, skip_images=gemini_vision)
    await prepare_attachments(body)

    last_user_text = next((m.content for m in reversed(body.messages) if m.role == "user" and m.content), "")

    search_context, is_code = await asyncio.gather(
        exa_web_search(last_user_text),
        is_code_request(body),
    )

    # Richiesta di codice con immagine: il codice va su NVIDIA (solo testo), quindi
    # l'immagine serve descritta come prima.
    if gemini_vision and is_code:
        gemini_vision = False
        await enrich_attachments_with_ai_analysis(body)

    messages = build_messages(body, search_context)

    job_id = uuid.uuid4().hex
    _ai_jobs[job_id] = {
        "status": "pending", "content": None, "error": None,
        "created_at": time.monotonic(), "user_id": user.user_id,
    }
    task = asyncio.create_task(_run_ai_job(job_id, messages, is_code, user, use_gemini=gemini_vision))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"job_id": job_id, "status": "pending"}




@api_router.get("/ai/generate/status/{job_id}")
async def ai_generate_status(job_id: str, user: User = Depends(get_current_user)):
    job = _ai_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (scaduto o mai esistito)")
    if job["user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    response = {"status": job["status"]}
    if job["status"] == "done":
        response.update({
            "content": job["content"], "provider": job["provider"],
            "usage_used": job["usage_used"], "usage_limit": job["usage_limit"],
        })
    elif job["status"] == "error":
        response["error"] = job["error"]
    return response
# --- Router: decide quale provider usare PRIMA di generare ---
# Riusa la tua is_code_request(text) già esistente per CODE_KEYWORDS,
# non la ridefinisco qui.


@api_router.get("/ai/test-nvidia")
async def test_nvidia():
    """
    Test rapido di entrambi i modelli NVIDIA NIM usati da Zalvion. Nessuna scrittura
    su Supabase, nessuna auth richiesta (debug/monitoraggio manuale).
    """
    cases = [
        {"name": "testo_deepseek_v4_flash", "model": NVIDIA_TEXT_MODEL, "max_tokens": 200, "thinking": False,
         "messages": [{"role": "user", "content": "Rispondi con una sola parola: 'ok'."}]},
        {"name": "codice_kimi_k3", "model": NVIDIA_CODE_MODEL, "max_tokens": 2000, "thinking": True,
         "messages": [{"role": "user", "content": "Scrivi una funzione Python che calcola il fattoriale, "
                                                   "gestendo input negativi con un'eccezione."}]},
    ]
    results = []
    for case in cases:
        started = now_utc()
        try:
            content = await call_nvidia(case["messages"], model=case["model"], max_tokens=case["max_tokens"],
                                        thinking=case["thinking"])
            elapsed = (now_utc() - started).total_seconds()
            results.append({
                "test": case["name"], "model": case["model"], "status": "ok",
                "elapsed_seconds": round(elapsed, 2), "response_preview": content[:200],
            })
        except Exception as e:
            elapsed = (now_utc() - started).total_seconds()
            results.append({
                "test": case["name"], "model": case["model"], "status": "error",
                "elapsed_seconds": round(elapsed, 2), "error": str(e),
            })

    passed = sum(1 for r in results if r["status"] == "ok")
    return {
        "provider": "nvidia-nim", "tests_total": len(results), "tests_passed": passed,
        "tests_failed": len(results) - passed, "all_passed": passed == len(results),
        "results": results,
    }


@api_router.post("/ai/generate-image")
async def ai_generate_image(body: ImageGenerateBody, user: User = Depends(get_current_user)):
    """
    Genera un'immagine con Flux 1 [schnell] su Cloudflare Workers AI (gratuito, 720 req/min).
    NB: width/height del body sono ignorati da questo provider (risoluzione fissa del modello).
    """
    if await is_unsafe_image_prompt(body.prompt):
        raise HTTPException(status_code=400, detail="Questo tipo di immagine non può essere generata.")
    await enforce_and_increment(user)
    try:
        content, content_type = await call_cloudflare_flux_image(body.prompt)
    except Exception as e:
        logger.error(f"Cloudflare Workers AI (Flux) image error: {e}")
        lang = "it"
        raise HTTPException(status_code=502, detail=image_quota_message(lang))
    b64 = base64.b64encode(content).decode()
    used = await get_usage_today(user.user_id)
    return {
        "image_url": f"data:{content_type};base64,{b64}",
        "usage_used": used,
        "usage_limit": daily_limit_for(user.plan),
    }
@api_router.post("/ai/generate-image-pollinations")
async def ai_generate_image_pollinations(body: PollinationsImageBody, user: User = Depends(get_current_user)):
    if await is_unsafe_image_prompt(body.prompt):
        raise HTTPException(status_code=400, detail="This type of image cannot be generated.")
    prompt_text = (body.prompt or "").strip() or "a beautiful high quality image"
    try:
        content, content_type = await call_cloudflare_flux_image(prompt_text)
    except Exception as e:
        logger.error(f"Cloudflare Flux image error: {e}")
        raise HTTPException(status_code=502, detail=image_quota_message("en"))
    b64 = base64.b64encode(content).decode()
    return {"image_url": f"data:{content_type};base64,{b64}"}
@api_router.post("/tts")
async def text_to_speech(body: TTSBody, user: User = Depends(get_current_user)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="The text cannot be empty.")
    if len(text) > 3000:
        raise HTTPException(status_code=400, detail="Text too long, (max 3000)")
    try:
        buf = io.BytesIO()
        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.error(f"edge-tts error: {e}")
        raise HTTPException(status_code=502, detail="Error in the audio generation, try again")
    return {"audio_url": f"data:audio/mpeg;base64,{b64}"}


@api_router.get("/ai/test-cloudflare-image")
async def test_cloudflare_image():
    started = now_utc()
    try:
        content, content_type = await call_cloudflare_flux_image(
            "a red apple on a wooden table, photorealistic")
        elapsed = (now_utc() - started).total_seconds()
        return {
            "provider": "cloudflare-flux", "model": CLOUDFLARE_IMAGE_MODEL,
            "status": "ok", "elapsed_seconds": round(elapsed, 2),
            "content_type": content_type, "size_bytes": len(content),
        }
    except Exception as e:
        elapsed = (now_utc() - started).total_seconds()
        return {
            "provider": "cloudflare-flux", "model": CLOUDFLARE_IMAGE_MODEL,
            "status": "error", "elapsed_seconds": round(elapsed, 2), "error": str(e),
        }


# =====================================================================================
# CHATS
# =====================================================================================
@api_router.get("/chats")
async def list_chats(user: User = Depends(get_current_user)):
    return await sb_select("chats", columns="chat_id,user_id,title,folder_id,created_at,updated_at",
                           order_by="updated_at", desc=True, user_id=user.user_id)


@api_router.post("/chats")
async def create_chat(user: User = Depends(get_current_user)):
    chat = {"chat_id": f"chat_{uuid.uuid4().hex[:12]}", "user_id": user.user_id,
            "title": "New chat", "folder_id": None, "messages": [],
            "created_at": now_utc().isoformat(), "updated_at": now_utc().isoformat()}
    await sb_insert("chats", chat)
    chat.pop("messages", None)
    return chat


@api_router.patch("/chats/{chat_id}")
async def update_chat(chat_id: str, body: ChatUpdate, user: User = Depends(get_current_user)):
    update = {"updated_at": now_utc().isoformat()}
    if body.title is not None:
        update["title"] = body.title.strip()[:80] or "New chat"
    if body.clear_folder:
        update["folder_id"] = None
    elif body.folder_id is not None:
        update["folder_id"] = body.folder_id
    existing = await sb_select_one("chats", chat_id=chat_id, user_id=user.user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Chat not found")
    await sb_update("chats", update, chat_id=chat_id)
    return {"status": "ok"}


@api_router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user: User = Depends(get_current_user)):
    await sb_delete("chats", chat_id=chat_id, user_id=user.user_id)
    return {"status": "ok"}


@api_router.get("/chats/{chat_id}/messages")
async def get_messages(chat_id: str, user: User = Depends(get_current_user)):
    chat = await sb_select_one("chats", chat_id=chat_id, user_id=user.user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"messages": chat.get("messages", []), "title": chat.get("title")}


@api_router.post("/chats/{chat_id}/messages/user")
async def add_user_message(chat_id: str, body: UserMsgBody, user: User = Depends(get_current_user)):
    chat = await sb_select_one("chats", chat_id=chat_id, user_id=user.user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    await enforce_and_increment(user)
    user_msg = {"id": uuid.uuid4().hex, "role": "user", "type": "text",
                "content": body.content, "attachments": body.attachments,
                "created_at": now_utc().isoformat()}
    new_title = chat["title"]
    if chat["title"] == "New chat" and body.content:
        new_title = body.content[:48]
    await append_chat_message(chat_id, user.user_id, user_msg, new_title=new_title)
    used = await get_usage_today(user.user_id)
    return {"ok": True, "title": new_title, "usage_used": used, "usage_limit": daily_limit_for(user.plan)}


@api_router.post("/chats/{chat_id}/messages/assistant")
async def add_assistant_message(chat_id: str, body: AssistantMsgBody, user: User = Depends(get_current_user)):
    chat = await sb_select_one("chats", chat_id=chat_id, user_id=user.user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    assistant_msg = {"id": uuid.uuid4().hex, "role": "assistant", "type": body.type,
                     "content": body.content, "image_url": body.image_url,
                     "created_at": now_utc().isoformat()}
    await append_chat_message(chat_id, user.user_id, assistant_msg, replace_last=body.replace_last)
    return {"ok": True}


# =====================================================================================
# FOLDERS
# =====================================================================================
@api_router.get("/folders")
async def list_folders(user: User = Depends(get_current_user)):
    return await sb_select("folders", order_by="created_at", desc=False, user_id=user.user_id)


@api_router.post("/folders")
async def create_folder(body: FolderBody, user: User = Depends(get_current_user)):
    folder = {"folder_id": f"folder_{uuid.uuid4().hex[:12]}", "user_id": user.user_id,
              "name": (body.name.strip() or "New folder")[:60], "created_at": now_utc().isoformat()}
    await sb_insert("folders", folder)
    return folder


@api_router.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, body: FolderBody, user: User = Depends(get_current_user)):
    existing = await sb_select_one("folders", folder_id=folder_id, user_id=user.user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Folder not found")
    await sb_update("folders", {"name": (body.name.strip() or "New folder")[:60]}, folder_id=folder_id)
    return {"status": "ok"}


@api_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, user: User = Depends(get_current_user)):
    await sb_delete("folders", folder_id=folder_id, user_id=user.user_id)
    chats_in_folder = await sb_select("chats", columns="chat_id", user_id=user.user_id, folder_id=folder_id)
    for c in chats_in_folder:
        await sb_update("chats", {"folder_id": None}, chat_id=c["chat_id"])
    return {"status": "ok"}


# =====================================================================================
# BILLING (PayPal)
# =====================================================================================
def paypal_configured() -> bool:
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)


async def paypal_token() -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{PAYPAL_BASE}/v1/oauth2/token",
                              auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
                              data={"grant_type": "client_credentials"})
        r.raise_for_status()
        return r.json()["access_token"]


async def ensure_paypal_plans():
    cfg = await sb_select_one("app_config", key="paypal_plans")
    if cfg and cfg.get("mode") == PAYPAL_MODE and cfg.get("monthly_plan_id") and cfg.get("yearly_plan_id"):
        return cfg
    token = await paypal_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        prod = await client.post(f"{PAYPAL_BASE}/v1/catalogs/products", headers=headers,
            json={"name": "Claus IA Pro", "description": "Claus IA Pro subscription",
                  "type": "SERVICE", "category": "SOFTWARE"})
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

        m = await client.post(f"{PAYPAL_BASE}/v1/billing/plans", headers=headers,
                              json=plan_payload("Claus IA Pro Monthly", "MONTH", "10"))
        m.raise_for_status()
        y = await client.post(f"{PAYPAL_BASE}/v1/billing/plans", headers=headers,
                              json=plan_payload("Claus IA Pro Yearly", "YEAR", "100"))
        y.raise_for_status()

    cfg = {"key": "paypal_plans", "mode": PAYPAL_MODE, "product_id": product_id,
           "monthly_plan_id": m.json()["id"], "yearly_plan_id": y.json()["id"]}
    await sb_upsert("app_config", cfg, on_conflict="key")
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


@api_router.post("/billing/activate")
async def billing_activate(body: ActivateBody, user: User = Depends(get_current_user)):
    if not paypal_configured():
        raise HTTPException(status_code=400, detail="PayPal not configured")
    try:
        token = await paypal_token()
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{PAYPAL_BASE}/v1/billing/subscriptions/{body.subscription_id}",
                                 headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            sub = r.json()
    except Exception as e:
        logger.error(f"PayPal verify failed: {e}")
        raise HTTPException(status_code=400, detail="Could not verify subscription")
    if sub.get("status") not in ("ACTIVE", "APPROVED"):
        raise HTTPException(status_code=400, detail=f"Subscription not active: {sub.get('status')}")
    await sb_update("users", {"plan": "pro", "subscription_id": body.subscription_id,
                              "plan_type": body.plan_type, "plan_since": now_utc().isoformat()},
                    user_id=user.user_id)
    return {"status": "ok", "plan": "pro"}


@api_router.post("/billing/cancel")
async def billing_cancel(user: User = Depends(get_current_user)):
    if user.subscription_id and paypal_configured():
        try:
            token = await paypal_token()
            async with httpx.AsyncClient(timeout=20) as client:
                await client.post(f"{PAYPAL_BASE}/v1/billing/subscriptions/{user.subscription_id}/cancel",
                                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                  json={"reason": "User requested cancellation"})
        except Exception as e:
            logger.error(f"PayPal cancel failed: {e}")
    await sb_update("users", {"plan": "free", "subscription_id": None, "plan_type": None}, user_id=user.user_id)
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
            await sb_update("users", {"plan": "free", "subscription_id": None, "plan_type": None},
                            subscription_id=sub_id)
        elif event_type == "BILLING.SUBSCRIPTION.ACTIVATED" and sub_id:
            await sb_update("users", {"plan": "pro"}, subscription_id=sub_id)
    except Exception as e:
        logger.error(f"Webhook handling error: {e}")
    return {"status": "ok"}


@api_router.get("/")
async def root():
    return {"message": "Zalvion AI API"}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"], allow_headers=["*"],
)
