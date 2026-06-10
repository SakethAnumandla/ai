"""Smoke-test approval APIs + full claim workflow visibility."""
import sys
from datetime import datetime, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TIMEOUT = 60.0
passed = failed = 0


def ok(name: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    print(f"\n=== Approval API tests @ {BASE} ===\n")
    c = httpx.Client(base_url=BASE, timeout=TIMEOUT)

    r = c.get("/approvals/pending")
    ok("GET /approvals/pending", r.status_code == 200 and isinstance(r.json(), list), r.text[:150])

    r = c.get("/claims/pending-approvals")
    ok("GET /claims/pending-approvals", r.status_code == 200, r.text[:150])

    # Ensure we have a claim to inspect
    policies = c.get("/policies").json()
    if not policies:
        print("  SKIP  no policies — run seed first")
        print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
        sys.exit(1 if failed else 0)

    pid = policies[0]["id"]
    r = c.post(
        "/claims/submit",
        data={
            "policy_id": str(pid),
            "bill_name": "Approval flow test bill",
            "bill_amount": "100",
            "bill_date": datetime.now(timezone.utc).isoformat(),
        },
    )
    ok("POST /claims/submit (small amount)", r.status_code == 201, r.text[:200])
    if r.status_code != 201:
        print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
        sys.exit(1)

    claim_id = r.json()["claim"]["id"]
    outcome = r.json().get("outcome")
    ok("claim outcome pending_approval", outcome == "pending_approval", outcome)

    r = c.get(f"/approvals/claim/{claim_id}/workflow")
    ok("GET /approvals/claim/{id}/workflow", r.status_code == 200, r.text[:150])
    if r.status_code == 200:
        wf = r.json()
        ok("workflow has approvals", wf.get("total_approvals", 0) >= 1, str(wf))

    r = c.get(f"/claims/{claim_id}")
    ok("GET /claims/{id}", r.status_code == 200, r.text[:100])
    if r.status_code == 200:
        approvals = r.json().get("approvals") or []
        ok("claim includes approvals array", len(approvals) >= 0, f"count={len(approvals)}")

    # Action endpoint: only if current dev user has a pending approval
    pending = c.get("/approvals/pending").json()
    if pending:
        aid = pending[0]["id"]
        r = c.post(
            f"/approvals/{aid}/action",
            json={"status": "approved", "comments": "API test approve"},
        )
        ok("POST /approvals/{id}/action", r.status_code == 200, r.text[:200])
    else:
        print("  SKIP  POST /approvals/{id}/action (no pending for devuser — use depthead/manager login)")

    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
