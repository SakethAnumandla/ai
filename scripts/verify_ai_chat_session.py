"""Verify first-message chat alignment (run with backend on localhost:8000)."""
import json
import sys
import uuid

import httpx

BASE = "http://localhost:8000"
TIMEOUT = 90.0


def main() -> int:
    sid = f"bizwy-{uuid.uuid4().hex[:12]}"
    c = httpx.Client(base_url=BASE, timeout=TIMEOUT)

    print(f"session_id={sid}")

    w = c.get("/ai/chat/welcome", params={"session_id": sid})
    print(f"GET welcome -> {w.status_code}")
    if w.status_code != 200:
        print(w.text[:300])
        return 1

    r1 = c.post("/ai/chat", json={"session_id": sid, "message": "hi"})
    print(f"POST hi -> {r1.status_code}")
    if r1.status_code != 200:
        print(r1.text[:300])
        return 1
    body1 = r1.json()
    msg1 = (body1.get("message") or {}).get("content", "")
    print(f"  reply1 preview: {msg1[:120]!r}")
    if "I'm Bizwy AI" in msg1 and "Expenses" in msg1 and "Approvals" in msg1:
        print("FAIL: first message still returned welcome blob")
        return 1

    r2 = c.post(
        "/ai/chat",
        json={"session_id": sid, "message": "show me the expense summary"},
    )
    print(f"POST summary -> {r2.status_code}")
    if r2.status_code != 200:
        print(r2.text[:300])
        return 1
    msg2 = (r2.json().get("message") or {}).get("content", "")
    print(f"  reply2 preview: {msg2[:120]!r}")
    if "how are you" in msg2.lower() and "hi" not in msg2.lower():
        print("FAIL: second message looks like delayed greeting for first")
        return 1

    end = c.post("/ai/chat/end", params={"session_id": sid})
    print(f"POST end -> {end.status_code}")
    if end.status_code != 204:
        print(end.text[:300])
        return 1

    print("OK: session chat alignment verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
