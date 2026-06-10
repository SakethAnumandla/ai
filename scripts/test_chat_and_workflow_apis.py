"""Smoke-test expense workflow + AI chat (OpenAI) endpoints."""
import json
import sys
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
TIMEOUT = 120.0


def ok(code: int) -> bool:
    return 200 <= code < 300


def main() -> int:
    session_id = f"test-{uuid.uuid4().hex[:20]}"
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    failures = []

    def check(label: str, resp: httpx.Response, *, allow=(200, 201)) -> dict | None:
        status = resp.status_code
        if status not in allow:
            detail = resp.text[:200]
            try:
                detail = str(resp.json().get("detail", detail))[:200]
            except Exception:
                pass
            failures.append(f"{label}: HTTP {status} — {detail}")
            print(f"FAIL {label} -> {status} {detail}")
            return None
        print(f"OK   {label} -> {status}")
        try:
            return resp.json()
        except Exception:
            return {}

    print("=== Health & workflow ===")
    h = client.get("/health")
    data = check("GET /health", h)
    if data:
        print(f"     openai.configured={data.get('openai', {}).get('configured')}")

    check("GET /categories/business/hierarchy", client.get("/categories/business/hierarchy"))
    check("GET /expenses/approvers/directory", client.get("/expenses/approvers/directory"))
    check("GET /expenses/approvals/pending", client.get("/expenses/approvals/pending"))
    check("GET /budgets/monthly", client.get("/budgets/monthly", params={"financial_year": "FY2025-26"}))

    print("\n=== AI chat ===")
    w = client.get("/ai/chat/welcome", params={"session_id": session_id})
    welcome = check("GET /ai/chat/welcome", w)
    if welcome:
        msg = welcome.get("message", {})
        content = (msg.get("content") or "")[:120]
        print(f"     welcome preview: {content!r}...")

    chat_payload = {"session_id": session_id, "message": "Hi! How are you?"}
    c1 = client.post("/ai/chat", json=chat_payload)
    r1 = check("POST /ai/chat (greeting)", c1)
    if r1:
        print(f"     reply preview: {(r1.get('message', {}).get('content') or '')[:160]}")
        tools = r1.get("tool_results")
        print(f"     tool_results: {len(tools) if tools else 0}")

    chat_payload2 = {
        "session_id": session_id,
        "message": "Show my last 3 expenses",
    }
    c2 = client.post("/ai/chat", json=chat_payload2)
    r2 = check("POST /ai/chat (search)", c2)
    if r2:
        print(f"     reply preview: {(r2.get('message', {}).get('content') or '')[:200]}")
        if r2.get("tool_results"):
            print(f"     tools: {json.dumps([t.get('tool') for t in r2['tool_results']], default=str)}")

    chat_payload3 = {
        "session_id": session_id,
        "message": "Show expense bills waiting for my approval",
    }
    c3 = client.post("/ai/chat", json=chat_payload3)
    r3 = check("POST /ai/chat (approvals)", c3)
    if r3:
        print(f"     reply preview: {(r3.get('message', {}).get('content') or '')[:200]}")

    print("\n=== Summary ===")
    if failures:
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All chat/workflow checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
