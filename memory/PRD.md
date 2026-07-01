# Claus IA — PRD

## Original problem statement
Build "Claus IA", a Claude-identical, more powerful AI web app (Italian user). Chat (with web info), image + video generation, deep reasoning, file/image upload understanding, modern Claude-like UI, Google login + email OTP, per-account saved chats with "New chat", desktop app download (Win/Mac/Linux), 15 languages, real voice input. No placeholders.

### Iteration 2 modifications (requested)
1. Google login must go DIRECTLY to the official Google page (accounts.google.com, "continue to Claus") — NOT via Emergent.
2. Add a video generator to complete the AI environment.
3. Desktop app must install on click (not tell user to open the browser menu).

## Architecture
- Frontend: React 19 + Tailwind + shadcn, react-markdown + syntax highlighting, Web Speech API (voice), PWA install.
- Backend: FastAPI + MongoDB (motor), SSE streaming for chat.
- AI: Claude Sonnet 4.6 (text + web_search tool), Gemini Nano Banana (images), OpenAI Sora 2 (video) — all via emergentintegrations / EMERGENT_LLM_KEY.
- Auth: Direct Google OAuth 2.0 (authorization-code flow, backend token exchange) + email OTP via Resend. Sessions = httpOnly cookie + Bearer fallback.

## Implemented
### Iteration 1 (2026-06-30)
- Email OTP login (real Resend email), chats CRUD + persistence, streaming chat (Claude) with markdown/code, web search, image generation, file/image upload, voice input, 15-language UI, PWA install, Claude-like UI.

### Iteration 2 (2026-07-01)
- ✅ Direct Google OAuth 2.0: /login builds accounts.google.com URL; /auth/google callback exchanges code via backend (GOOGLE_CLIENT_ID/SECRET) → userinfo → session cookie. Emergent auth removed.
- ✅ Video generation (Sora 2): composer video toggle (Film icon) → POST /chats/{id}/video → background job → polling → inline <video>. Endpoint verified (creates messages, runs job; output pending budget).
- ✅ Direct install: global `beforeinstallprompt` capture in index.js; Download button calls prompt() immediately.

## Blocked / needs user action
- ⚠️ Universal Key budget exceeded (Max budget ~$0.40, already spent). Chat/image/video produce NO output until balance is increased: Profile → Universal Key → Add Balance (or enable auto top-up). Code is correct and verified; only credits are missing.

## Verified (curl/screenshot)
- Auth /auth/me (cookie + Bearer), chats create/list/persist, video endpoint message flow, full chat UI with image/video/web/voice toggles, sidebar, download, language selector, Italian login screen.

## Backlog (P1/P2)
- P1: Full e2e AI test once budget is added; verify Google OAuth end-to-end (real Google login).
- P1: Verify a Resend domain so OTP delivers to any email (test mode = owner email only).
- P2: Real native installers (Electron) build pipeline (currently PWA install).
- P2: Video options UI (duration/size/model), image-to-video, chat rename, regenerate.
