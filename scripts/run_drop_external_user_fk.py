#!/usr/bin/env python3
"""One-shot: drop user_id FK constraints so external Bizwy ids work.

Usage (production):
  DATABASE_URL='postgresql://...' python scripts/run_drop_external_user_fk.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.migrations.drop_external_user_fk import expenses_user_id_fk_present, run


def main() -> int:
    before = expenses_user_id_fk_present()
    print(f"expenses_user_id_fk before: {before}")
    run()
    after = expenses_user_id_fk_present()
    print(f"expenses_user_id_fk after:  {after}")
    return 1 if after else 0


if __name__ == "__main__":
    raise SystemExit(main())
