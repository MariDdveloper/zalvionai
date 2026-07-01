"""Backend API tests for the new Claus IA features:
- Rename chat via PATCH /api/chats/{id}
- Move chat to/out of folder via PATCH /api/chats/{id}
- Folder CRUD via /api/folders
- Regenerate assistant message via POST /api/chats/{id}/regenerate
"""
import os
import json
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://claus-ai.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_qa_01"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


# -- helpers --------------------------------------------------------------
def _new_chat():
    r = requests.post(f"{BASE_URL}/api/chats", headers=H)
    assert r.status_code == 200, r.text
    return r.json()["chat_id"]


def _send_message_stream(chat_id, content, timeout=90):
    """Consume SSE from POST /api/chats/{id}/stream and return final assistant text."""
    payload = {"content": content, "images": [], "files": [], "mode": "chat", "web": False, "language": "it"}
    with requests.post(f"{BASE_URL}/api/chats/{chat_id}/stream", headers=H, json=payload, stream=True, timeout=timeout) as r:
        assert r.status_code == 200, r.text
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except Exception:
                continue
            if evt.get("type") == "done":
                return True
    return True


# -- Folders CRUD ---------------------------------------------------------
class TestFolders:
    def test_list_folders(self):
        r = requests.get(f"{BASE_URL}/api/folders", headers=H)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_folder_create_rename_delete(self):
        name = f"TEST_folder_{uuid.uuid4().hex[:6]}"
        # CREATE
        r = requests.post(f"{BASE_URL}/api/folders", headers=H, json={"name": name})
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["name"] == name
        assert "folder_id" in f
        fid = f["folder_id"]

        # LIST includes it
        r = requests.get(f"{BASE_URL}/api/folders", headers=H)
        assert any(x["folder_id"] == fid for x in r.json())

        # RENAME
        new_name = name + "_R"
        r = requests.patch(f"{BASE_URL}/api/folders/{fid}", headers=H, json={"name": new_name})
        assert r.status_code == 200, r.text
        r = requests.get(f"{BASE_URL}/api/folders", headers=H)
        got = [x for x in r.json() if x["folder_id"] == fid][0]
        assert got["name"] == new_name

        # DELETE
        r = requests.delete(f"{BASE_URL}/api/folders/{fid}", headers=H)
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/folders", headers=H)
        assert not any(x["folder_id"] == fid for x in r.json())


# -- Rename & Move chat ---------------------------------------------------
class TestChatPatch:
    def test_rename_chat_persists(self):
        cid = _new_chat()
        title = f"TEST_renamed_{uuid.uuid4().hex[:6]}"
        r = requests.patch(f"{BASE_URL}/api/chats/{cid}", headers=H, json={"title": title})
        assert r.status_code == 200, r.text
        # verify persistence
        chats = requests.get(f"{BASE_URL}/api/chats", headers=H).json()
        got = [c for c in chats if c["chat_id"] == cid][0]
        assert got["title"] == title
        # cleanup
        requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)

    def test_move_chat_in_and_out_of_folder(self):
        # setup: folder + chat
        f = requests.post(f"{BASE_URL}/api/folders", headers=H, json={"name": f"TEST_mv_{uuid.uuid4().hex[:6]}"}).json()
        fid = f["folder_id"]
        cid = _new_chat()
        try:
            # MOVE INTO folder
            r = requests.patch(f"{BASE_URL}/api/chats/{cid}", headers=H, json={"folder_id": fid})
            assert r.status_code == 200, r.text
            chats = requests.get(f"{BASE_URL}/api/chats", headers=H).json()
            got = [c for c in chats if c["chat_id"] == cid][0]
            assert got.get("folder_id") == fid

            # MOVE OUT via clear_folder
            r = requests.patch(f"{BASE_URL}/api/chats/{cid}", headers=H, json={"clear_folder": True})
            assert r.status_code == 200, r.text
            chats = requests.get(f"{BASE_URL}/api/chats", headers=H).json()
            got = [c for c in chats if c["chat_id"] == cid][0]
            assert got.get("folder_id") in (None, "", None)
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)
            requests.delete(f"{BASE_URL}/api/folders/{fid}", headers=H)

    def test_delete_folder_ungroups_chats(self):
        f = requests.post(f"{BASE_URL}/api/folders", headers=H, json={"name": f"TEST_del_{uuid.uuid4().hex[:6]}"}).json()
        fid = f["folder_id"]
        cid = _new_chat()
        try:
            requests.patch(f"{BASE_URL}/api/chats/{cid}", headers=H, json={"folder_id": fid})
            r = requests.delete(f"{BASE_URL}/api/folders/{fid}", headers=H)
            assert r.status_code == 200
            chats = requests.get(f"{BASE_URL}/api/chats", headers=H).json()
            got = [c for c in chats if c["chat_id"] == cid][0]
            assert not got.get("folder_id"), f"expected folder cleared, got {got.get('folder_id')}"
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)


# -- Regenerate -----------------------------------------------------------
class TestRegenerate:
    def test_regenerate_does_not_duplicate_assistant(self):
        cid = _new_chat()
        try:
            # 1 user + 1 assistant via streaming send
            _send_message_stream(cid, "Dimmi un numero tra 1 e 100, solo il numero")
            time.sleep(1)
            msgs = requests.get(f"{BASE_URL}/api/chats/{cid}/messages", headers=H).json().get("messages", [])
            n_user = sum(1 for m in msgs if m.get("role") == "user")
            n_asst = sum(1 for m in msgs if m.get("role") == "assistant")
            assert n_user == 1 and n_asst == 1, f"pre-regen expected 1/1 got {n_user}/{n_asst}"
            first_asst = [m for m in msgs if m.get("role") == "assistant"][0]

            # Regenerate — consume SSE stream
            with requests.post(f"{BASE_URL}/api/chats/{cid}/regenerate", headers=H,
                               json={"web": False, "language": "it"}, stream=True, timeout=90) as r:
                assert r.status_code == 200, r.text
                for line in r.iter_lines(decode_unicode=True):
                    if line and line.startswith("data:"):
                        try:
                            evt = json.loads(line[5:].strip())
                        except Exception:
                            continue
                        if evt.get("type") == "done":
                            break
            time.sleep(1)

            msgs2 = requests.get(f"{BASE_URL}/api/chats/{cid}/messages", headers=H).json().get("messages", [])
            n_user2 = sum(1 for m in msgs2 if m.get("role") == "user")
            n_asst2 = sum(1 for m in msgs2 if m.get("role") == "assistant")
            assert n_user2 == 1 and n_asst2 == 1, f"post-regen expected 1/1 got {n_user2}/{n_asst2}. Assistant msg was duplicated!"

            new_asst = [m for m in msgs2 if m.get("role") == "assistant"][0]
            # It should be a NEW assistant message (different id or different content)
            # Either the id changed or content changed (both indicate a real regenerate)
            assert new_asst.get("id") != first_asst.get("id") or new_asst.get("content") != first_asst.get("content"), \
                "Regenerate returned identical message; expected replacement"
        finally:
            requests.delete(f"{BASE_URL}/api/chats/{cid}", headers=H)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
