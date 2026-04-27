"""PostgreSQL storage administration helper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id  # noqa: E402
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage PostgreSQL storage for WeChat AI customer-service.")
    parser.add_argument("command", choices=["status", "init", "counts"])
    parser.add_argument("--tenant-id", default="")
    args = parser.parse_args()

    tenant_id = active_tenant_id(args.tenant_id or None)
    config = load_storage_config()
    store = get_postgres_store(tenant_id=tenant_id, config=config)
    availability = store.availability()
    if args.command == "status":
        print(json.dumps({"ok": availability.ok, "reason": availability.reason, "schema": config.postgres_schema}, ensure_ascii=False, indent=2))
        return 0
    if not availability.ok:
        print(json.dumps({"ok": False, "message": availability.reason}, ensure_ascii=False, indent=2))
        return 2
    if args.command == "init":
        print(json.dumps(store.initialize_schema(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "counts":
        print(json.dumps({"ok": True, "tenant_id": tenant_id, "counts": store.counts(tenant_id)}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
