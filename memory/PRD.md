# Claus IA — PRD

## Original problem statement
Build "Claus IA", a Claude-identical, more powerful AI web app (Italian user). Requirements: answers any question (incl. web info), image (& video) generation, deep reasoning, file/image upload understanding, modern Claude-like UI, login via Google OAuth2 (real Google screen) OR email with real OTP code, chats saved per account with a "New chat" button, a download button for a native desktop app (Windows/Mac/Linux), 15 languages, and real voice input. No placeholders — everything real.

## Architecture
- Frontend: React 19 + Tailwind + shadcn, react-markdown + syntax highlighting, Web Speech API for voice, PWA (installable desktop app).
- Backend: FastAPI + MongoDB (motor). SSE streaming for chat.
- AI: Claude Sonnet 4.6 (text, with Anthropic web_search tool) + Gemini Nano Banana (images) via emergentintegrations / EMERGENT_LLM_KEY.
- Email OTP: Resend. Auth: Emergent Google OAuth + custom email-OTP sessions (httpOnly cookie + Bearer fallback).

## User personas
- Anyone wanting a powerful multilingual AI assistant for Q&A, coding, reasoning, and image creation.

## Core requirements (static)
Auth (Google + email OTP), persistent per-account chats, new chat, streaming AI chat, web search, image generation, file/image upload, voice input, 15 languages, desktop install.

## Implemented (2026-06-30)
- ✅ Email OTP login (real Resend email) + Emergent Google OAuth login flow
- ✅ Session auth (cookie + Bearer), /auth/me, logout
- ✅ Chats CRUD + persistence per user, sidebar with history, search, New chat, delete
- ✅ Streaming chat (Claude Sonnet 4.6) with markdown/code rendering + web search tool (graceful fallback)
- ✅ Image generation mode (Gemini Nano Banana) inline in chat
- ✅ File + image upload (vision / document text)
- ✅ Real voice input (Web Speech API, language-aware)
- ✅ 15-language UI + language selector; AI replies in selected language
- ✅ PWA install (Windows/Mac/Linux) via Download modal + manifest + service worker + app icon
- ✅ Claude-identical warm/organic UI (login verified via screenshot)
- ✅ Verified via curl: auth/me, chat create, persistence, list

## Blocked / needs user action
- ⚠️ LLM responses fail with "Budget exceeded" — Universal Key balance is 0. User must top up: Profile → Universal Key → Add Balance. After top-up, chat + image flows work.

## Backlog (P1/P2)
- P1: Full e2e testing of chat/image/voice once budget is added.
- P1: Verify Resend domain to allow OTP delivery to any email.
- P2: Real native installers (Electron .exe/.dmg/.AppImage) build pipeline (currently PWA install).
- P2: Video generation (needs fal.ai key) — deferred per user.
- P2: Chat rename, message regenerate, stop-and-edit.
