"""Backend test: POST /api/auth/google returns 401 on bad code (graceful, no 500)."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://claus-ai.preview.emergentagent.com").rstrip("/")


def test_google_auth_bad_code_returns_401():
    r = requests.post(
        f"{BASE_URL}/api/auth/google",
        json={"code": "fakecode", "redirect_uri": f"{BASE_URL}/auth/google"},
        timeout=20,
    )
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("detail") == "Google authentication failed", data


def test_google_auth_missing_fields_returns_422():
    r = requests.post(f"{BASE_URL}/api/auth/google", json={}, timeout=15)
    assert r.status_code in (400, 422), f"Expected validation error, got {r.status_code}"
