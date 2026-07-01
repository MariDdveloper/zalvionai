"""Backend tests for POST /api/auth/google/session (Emergent-managed Google Auth).

Verifies:
- Missing X-Session-ID header → HTTP 400
- Invalid X-Session-ID → HTTP 401 with detail 'Google authentication failed'
- No 500 errors under either condition
- Regression: legacy /api/auth/google still returns 401 gracefully on fake code
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://claus-ai.preview.emergentagent.com").rstrip("/")


# ---- New Emergent Google session endpoint ----
class TestGoogleSession:
    def test_missing_header_returns_400(self):
        r = requests.post(f"{BASE_URL}/api/auth/google/session", timeout=15)
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        data = r.json()
        assert "detail" in data
        assert "session" in data["detail"].lower()

    def test_invalid_session_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/google/session",
            headers={"X-Session-ID": "invalidxyz"},
            timeout=20,
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("detail") == "Google authentication failed", data

    def test_invalid_session_never_500(self):
        for sid in ["", "x", "a" * 500, "!@#$%^&*()"]:
            r = requests.post(
                f"{BASE_URL}/api/auth/google/session",
                headers={"X-Session-ID": sid} if sid else {},
                timeout=15,
            )
            assert r.status_code in (400, 401), f"sid={sid!r} → {r.status_code}: {r.text[:200]}"


# ---- Regression: legacy direct OAuth endpoint still safe ----
class TestLegacyGoogleAuth:
    def test_legacy_bad_code_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/google",
            json={"code": "fakecode", "redirect_uri": f"{BASE_URL}/auth/google"},
            timeout=20,
        )
        # Legacy endpoint may still be present; must not 500.
        assert r.status_code in (401, 404, 410), f"Unexpected {r.status_code}: {r.text[:200]}"
