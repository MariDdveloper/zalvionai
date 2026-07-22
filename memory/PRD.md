# Zalvion AI — PRD (ex "Claus IA")

> STATO (2026-06): Rebrand completo a **Zalvion AI**. AI migrata da Gemini a **Pollinations AI** (gratis, no chiave). Paywall rimosso: tutto gratis, limite **10 generazioni/24h** per utente. Nuova landing "Get Started" con lettera dello sviluppatore in **15 lingue** + firma. DB su **MongoDB Atlas** (`ia_utenti_db`).
>
> ⚠️ BLOCCO NOTO: la generazione **TESTO** Pollinations dal tier anonimo (IP server condiviso) restituisce 402/429 → serve un **token gratuito** Pollinations (registrarsi su auth.pollinations.ai) da mettere in `POLLINATIONS_TOKEN` nel backend .env. Le **immagini** funzionano (girano dal browser client).
>
> FASE B DA FARE (richiede credenziali utente): migrazione auth+DB a **Supabase** (Google OAuth nativo, tabelle profiles/messages/rate_limits, RLS) e email onboarding **Resend** dal dominio `getzalvion.com`. Domini `zalvionai.com`/`getzalvion.com` da configurare in deploy.

---

# Claus IA — PRD (storico)

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
- ✅ Direct Google OAuth 2.0 (accounts.google.com), backend code exchange, session cookie. Emergent auth removed.
- ✅ Video generation (Sora 2): composer video toggle, background job + polling, inline <video>. VERIFIED end-to-end (valid 2.3MB mp4 rendered in UI).
- ✅ Video options: duration 4/8/12s, orientation landscape/portrait/square, image-to-video (uses attached image).
- ✅ Direct install: global beforeinstallprompt capture; Download button triggers install immediately.
- ✅ Budget added by user → chat, image, and video ALL verified working end-to-end via curl + screenshots.

## Known fragility note
- Some search_replace edits to MessageItem.jsx and server.py were silently reverted once (video branch/endpoints), likely a visual-edits/hot-reload race. Re-applied and verified. If a feature "disappears", re-check the file on disk.

### Iteration 3 (2026-07-01)
- ✅ Google 403 root cause fixed: frontend served client_id=undefined because CRA hadn't reloaded after REACT_APP_GOOGLE_CLIENT_ID was added. Frontend restarted; guard added in Login.jsx; graceful access_denied handling in GoogleCallback. Verified by testing_agent (iteration_1, all pass).
- ✅ Regenerate assistant message (POST /chats/{id}/regenerate — strips trailing assistant, re-streams, no duplication). Tested.
- ✅ Rename chat (PATCH /chats/{id} {title}). Tested + persists.
- ✅ Folders: create/rename/delete (/folders), move chats in/out (PATCH {folder_id}|{clear_folder}); sidebar grouping + chat action menu. Tested (backend 6/6, frontend 7/7).

## Remaining 403 note (user-side Google Console)
- If "Continua con Google" still shows 403 AFTER selecting the account, the OAuth consent screen is in "Testing" publishing status (or User type = Internal). Fix: Google Cloud Console → OAuth consent screen → PUBLISH APP (Production). Non-sensitive scopes (openid/email/profile) need no Google verification. Alternatively add the email under Test users. This is not a code issue.

## Verified (curl/screenshot)
- Auth /auth/me (cookie + Bearer), chats create/list/persist, video endpoint message flow, full chat UI with image/video/web/voice toggles, sidebar, download, language selector, Italian login screen.

## Backlog (P1/P2)
- P1: Provide PayPal Sandbox Client ID + Secret to activate real subscription buttons (currently configured:false → demo box shown).
- P1: Provide a higher-quota Gemini key (or billing) to enable image generation (currently 429 → friendly fallback message).
- P1: Resend domain verification (manual DNS records on registrar) so OTP delivers to any email; currently test mode = owner email only.
- P2: Extend IMAGE_QUOTA_MSG to all 15 languages (currently it/en/es/fr/de/pt, rest fall back to English).
- P2: Export chat to PDF/Markdown.
- P2: Real native installers (Electron) — currently PWA install.

### Iteration 4 & 5 (2026-07-05)
- ✅ Migrated LLM to DIRECT Gemini key (google-genai SDK), model gemini-2.5-flash (text) + gemini-2.5-flash-image (images). Emergent Universal Key removed. Video removed.
- ✅ Free/Pro daily limits (5/10) enforced server-side (db.usage). 402 → Pricing modal on frontend.
- ✅ Pricing modal (PayPal sandbox UI, graceful demo box when unconfigured), fake marketing reviews, Pro "advanced reasoning" panel (fake UI).
- ✅ Friendly localized image-quota fallback message (IMAGE_QUOTA_MSG).
- ✅ Fixed Sidebar.jsx duplicate `user` declaration (compile blocker).
- ✅ Fixed first-message-from-home race (justCreatedRef skips post-navigate fetch overwrite).
- ✅ Backend E2E 8/8 (iteration_4), Frontend E2E 5/5 (iteration_5). All verified.
