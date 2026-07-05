"""Backend tests for the January 2026 Claus IA update:
- Chat streaming SSE (Gemini text) persists user + assistant messages
- Daily limit enforcement (free=5, pro=10 → 402 daily_limit_reached)
- /api/auth/me returns usage_used and usage_limit for free (5) & pro (10)
- Image mode → gracefully streams friendly localized message (IT contains 🎨), no 500
- /api/billing/config returns configured:false with EUR 10/100 when PayPal creds empty
"""
import os
import json
import time
from datetime import date

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TOKEN = "test_session_qa_01"
UID = "user_testqa01"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def dbc():
    c = MongoClient(MONGO_URL)[DB_NAME]
    yield c
    # cleanup: reset usage and plan back to free
    c.usage.delete_many({"user_id": UID})
    c.users.update_one({"user_id": UID}, {"$set": {"plan": "free"}})


def _reset_usage(dbc):
    dbc.usage.delete_many({"user_id": UID})


def _set_usage(dbc, count):
    dbc.usage.update_one(
        {"user_id": UID, "date": date.today().isoformat()},
        {"$set": {"count": count}},
        upsert=True,
    )


def _set_plan(dbc, plan):
    dbc.users.update_one({"user_id": UID}, {"$set": {"plan": plan}}, upsert=True)


def _new_chat():
    r = requests.post(f"{BASE_URL}/api/chats", headers=H, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["chat_id"]


def _consume_stream(chat_id, body, timeout=90):
    """Collect all SSE events. Returns (status_code, events_list, full_delta_text)."""
    r = requests.post(f"{BASE_URL}/api/chats/{chat_id}/stream", headers=H,
                      json=body, stream=True, timeout=timeout)
    if r.status_code != 200:
        return r.status_code, [], r.text
    events, deltas = [], []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[5:].strip())
        except Exception:
            continue
        events.append(evt)
        if evt.get("type") == "delta":
            deltas.append(evt.get("content", ""))
        if evt.get("type") == "done":
            break
    return 200, events, "".join(deltas)


# ---------- /api/billing/config (PayPal empty → configured:false) ----------
class TestBillingConfig:
    def test_billing_config_not_configured(self):
        r = requests.get(f"{BASE_URL}/api/billing/config", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is False
        assert data.get("mode") == "sandbox"
        prices = data.get("prices", {})
        assert str(prices.get("monthly")) == "10"
        assert str(prices.get("yearly")) == "100"
        assert prices.get("currency") == "EUR"


# ---------- /api/auth/me usage_used / usage_limit ----------
class TestAuthMeUsage:
    def test_auth_me_free_limit_5(self, dbc):
        _set_plan(dbc, "free")
        _reset_usage(dbc)
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H, timeout=10)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["plan"] == "free"
        assert me["usage_limit"] == 5
        assert me["usage_used"] == 0

    def test_auth_me_pro_limit_10(self, dbc):
        _set_plan(dbc, "pro")
        _reset_usage(dbc)
        try:
            r = requests.get(f"{BASE_URL}/api/auth/me", headers=H, timeout=10)
            assert r.status_code == 200, r.text
            me = r.json()
            assert me["plan"] == "pro"
            assert me["usage_limit"] == 10
        finally:
            _set_plan(dbc, "free")


# ---------- Chat stream (Gemini) + persistence ----------
class TestChatStream:
    def test_stream_delta_and_done_and_persists(self, dbc):
        _set_plan(dbc, "free")
        _reset_usage(dbc)
        cid = _new_chat()
        try:
            status, events, text = _consume_stream(cid, {
                "content": "Rispondi solo con la parola: Ciao",
                "images": [], "files": [],
                "mode": "chat", "web": False, "language": "it",
            })
            assert status == 200
            types_seen = {e["type"] for e in events}
            assert "delta" in types_seen, f"no delta events. events={events}"
            assert "done" in types_seen, f"no done event. events={events}"
            assert text.strip() != ""

            # Persistence
            time.sleep(0.5)
            msgs = requests.get(f"{BASE_URL}/api/chats/{cid}/messages", headers=H, timeout=10).json().get("messages", [])
            roles = [m["role"] for m in msgs]
            assert roles.count("user") == 1
            assert roles.count("assistant") == 1
            assistant = [m for m in msgs if m["role"] == "assistant"][0]
            assert assistant["content"].strip() != ""
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)


# ---------- Daily limit enforcement ----------
class TestDailyLimit:
    def test_free_user_402_when_limit_reached(self, dbc):
        _set_plan(dbc, "free")
        _set_usage(dbc, 5)  # already at cap
        cid = _new_chat()
        try:
            r = requests.post(f"{BASE_URL}/api/chats/{cid}/stream", headers=H,
                              json={"content": "hi", "images": [], "files": [],
                                    "mode": "chat", "web": False, "language": "it"},
                              timeout=15)
            assert r.status_code == 402, r.text
            try:
                assert r.json().get("detail") == "daily_limit_reached"
            except Exception:
                assert "daily_limit_reached" in r.text
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)
            _reset_usage(dbc)

    def test_pro_user_still_allowed_at_5(self, dbc):
        _set_plan(dbc, "pro")
        _set_usage(dbc, 5)  # for a pro user this is under the limit of 10
        cid = _new_chat()
        try:
            r = requests.post(f"{BASE_URL}/api/chats/{cid}/stream", headers=H,
                              json={"content": "ok", "images": [], "files": [],
                                    "mode": "chat", "web": False, "language": "it"},
                              stream=True, timeout=60)
            assert r.status_code == 200, r.text
            r.close()
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)
            _set_plan(dbc, "free")
            _reset_usage(dbc)

    def test_pro_user_402_at_10(self, dbc):
        _set_plan(dbc, "pro")
        _set_usage(dbc, 10)
        cid = _new_chat()
        try:
            r = requests.post(f"{BASE_URL}/api/chats/{cid}/stream", headers=H,
                              json={"content": "hi", "images": [], "files": [],
                                    "mode": "chat", "web": False, "language": "it"},
                              timeout=15)
            assert r.status_code == 402, r.text
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)
            _set_plan(dbc, "free")
            _reset_usage(dbc)


# ---------- Image mode graceful 429 fallback ----------
class TestImageModeGraceful:
    def test_image_mode_returns_friendly_italian_message(self, dbc):
        _set_plan(dbc, "free")
        _reset_usage(dbc)
        cid = _new_chat()
        try:
            status, events, text = _consume_stream(cid, {
                "content": "Genera un'immagine di un gatto astronauta",
                "images": [], "files": [],
                "mode": "image", "web": False, "language": "it",
            }, timeout=120)
            assert status == 200, f"image mode should not 500: got {status}"
            types_seen = {e["type"] for e in events}
            assert "done" in types_seen
            # The Gemini image key is expected to 429 → friendly IT message contains 🎨
            # If it actually succeeds (image event), that's also acceptable.
            if "image" in types_seen:
                # Success path (unlikely but valid)
                assert True
            else:
                assert "delta" in types_seen
                assert "🎨" in text, f"expected italian friendly emoji in fallback, got: {text[:200]}"
                # italian keyword
                assert ("limite" in text.lower()) or ("immagin" in text.lower())
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)
            _reset_usage(dbc)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
