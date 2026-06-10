"""Smoke-test policy + claim APIs. Run with server at BASE_URL (default http://127.0.0.1:8000)."""
import json
import sys
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TIMEOUT = 60.0

passed = 0
failed = 0


def ok(name: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    print(f"\n=== Policy API tests @ {BASE} ===\n")
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)

    # Health
    r = client.get("/health")
    ok("GET /health", r.status_code == 200, r.text)

    # Policy metadata
    r = client.get("/policies/types")
    ok("GET /policies/types", r.status_code == 200 and "sub_categories" in r.json(), r.text[:200])

    r = client.get("/policy-types")
    ok("GET /policy-types", r.status_code == 200, r.text[:200])

    # List existing
    r = client.get("/policies")
    ok("GET /policies", r.status_code == 200 and isinstance(r.json(), list), r.text[:200])
    policies = r.json()

    # Create policy (admin — dev user is admin in local mode)
    code = f"POL-TEST-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    create_body = {
        "policy_id": code,
        "policy_name": "API Test Healthcare Policy",
        "policy_type": "medical",
        "maximum_amount": 5000,
        "minimum_amount": 0,
        "coverage_percentage": 100,
        "main_category": "policy",
        "sub_category": "healthcare",
        "requires_approval": True,
        "approval_flow": ["department_head", "manager"],
        "terms_and_conditions": "Test terms only.",
        "valid_from": datetime.now(timezone.utc).isoformat(),
    }
    r = client.post("/policies", json=create_body)
    ok("POST /policies (create)", r.status_code == 201, f"{r.status_code} {r.text[:300]}")
    if r.status_code != 201:
        print(json.dumps(create_body, indent=2))
        _summary()
        return
    policy = r.json()
    pid = policy["id"]

    # Duplicate policy_id
    r2 = client.post("/policies", json=create_body)
    ok("POST /policies duplicate", r2.status_code == 400, f"{r2.status_code}")

    # Get by id
    r = client.get(f"/policies/{pid}")
    ok("GET /policies/{id}", r.status_code == 200 and r.json()["policy_id"] == code, r.text[:200])

    # Update
    r = client.put(
        f"/policies/{pid}",
        json={"maximum_amount": 6000, "description": "Updated via API test"},
    )
    ok("PUT /policies/{id}", r.status_code == 200 and r.json()["maximum_amount"] == 6000, r.text[:200])

    # Filter list
    r = client.get("/policies", params={"policy_type": "medical"})
    ok("GET /policies?policy_type=medical", r.status_code == 200, r.text[:100])

    # Claim: over limit -> expense
    r = client.post(
        "/claims/submit",
        data={
            "policy_id": str(pid),
            "bill_name": "Test Hospital Over Limit",
            "bill_amount": "10000",
            "bill_date": datetime.now(timezone.utc).isoformat(),
        },
    )
    data = r.json() if r.status_code == 201 else {}
    ok(
        "POST /claims/submit (10000 > 6000)",
        r.status_code == 201 and data.get("outcome") == "rejected_over_limit",
        f"{r.status_code} {r.text[:300]}",
    )

    # Claim: within limit -> pending
    r = client.post(
        "/claims/submit",
        data={
            "policy_id": str(pid),
            "bill_name": "Test Hospital OK",
            "bill_amount": "4000",
            "bill_date": datetime.now(timezone.utc).isoformat(),
        },
    )
    data = r.json() if r.status_code == 201 else {}
    ok(
        "POST /claims/submit (4000 <= 6000)",
        r.status_code == 201 and data.get("outcome") == "pending_approval",
        f"{r.status_code} {r.text[:300]}",
    )

    # Summary
    r = client.get("/claims/summary")
    ok("GET /claims/summary", r.status_code == 200 and "total_claims" in r.json(), r.text[:150])

    # Delete policy with claims should fail
    r = client.delete(f"/policies/{pid}")
    ok("DELETE /policies/{id} (has claims)", r.status_code == 400, f"{r.status_code} {r.text[:200]}")

    # Create disposable policy and delete
    code2 = f"POL-DEL-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    r = client.post(
        "/policies",
        json={**create_body, "policy_id": code2, "policy_name": "To Delete"},
    )
    if r.status_code == 201:
        pid2 = r.json()["id"]
        r = client.delete(f"/policies/{pid2}")
        ok("DELETE /policies/{id} (no claims)", r.status_code == 204, f"{r.status_code}")

    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
    sys.exit(1 if failed else 0)


def _summary():
    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
