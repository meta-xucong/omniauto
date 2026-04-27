"""PostgreSQL-backed JSONB repository.

The repository keeps complete business objects in JSONB payload columns while
also exposing indexed business columns for routing, filtering, and parity
checks. psycopg is imported lazily so JSON/file mode remains usable without a
database driver installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import DEFAULT_TENANT_ID, active_tenant_id

from .config import StorageConfig, load_storage_config, validate_schema_name


SCHEMA_SQL_PATH = Path(__file__).with_name("postgres_schema.sql")


@dataclass
class PostgresAvailability:
    ok: bool
    reason: str = ""


class PostgresJsonStore:
    def __init__(self, config: StorageConfig | None = None, *, tenant_id: str | None = None) -> None:
        self.config = config or load_storage_config()
        self.tenant_id = active_tenant_id(tenant_id)
        validate_schema_name(self.config.postgres_schema)

    @property
    def schema(self) -> str:
        return self.config.postgres_schema

    def availability(self) -> PostgresAvailability:
        if not self.config.use_postgres:
            return PostgresAvailability(False, "WECHAT_STORAGE_BACKEND is not postgres")
        if not self.config.postgres_configured:
            return PostgresAvailability(False, "WECHAT_POSTGRES_DSN or DATABASE_URL is not set")
        try:
            self._psycopg()
        except Exception as exc:
            return PostgresAvailability(False, f"psycopg unavailable: {exc}")
        return PostgresAvailability(True)

    def available(self) -> bool:
        return self.availability().ok

    def initialize_schema(self) -> dict[str, Any]:
        self._require_available()
        ddl = SCHEMA_SQL_PATH.read_text(encoding="utf-8").format(schema=self.schema)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
        return {"ok": True, "schema": self.schema}

    def upsert_tenant(self, tenant: dict[str, Any]) -> None:
        tenant_id = str(tenant.get("tenant_id") or tenant.get("id") or self.tenant_id or DEFAULT_TENANT_ID)
        display_name = str(tenant.get("display_name") or tenant.get("name") or tenant_id)
        self.execute(
            f"""
            INSERT INTO {self.schema}.tenants (tenant_id, display_name, payload, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (tenant_id)
            DO UPDATE SET display_name = EXCLUDED.display_name, payload = EXCLUDED.payload, updated_at = now()
            """,
            [tenant_id, display_name, self.jsonb(tenant)],
        )

    def upsert_category(self, tenant_id: str, layer: str, category: dict[str, Any]) -> None:
        category_id = str(category.get("id") or category.get("category_id") or "")
        if not category_id:
            raise ValueError("category id is required")
        self.execute(
            f"""
            INSERT INTO {self.schema}.knowledge_categories
              (tenant_id, layer, category_id, enabled, sort_order, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (tenant_id, layer, category_id)
            DO UPDATE SET
              enabled = EXCLUDED.enabled,
              sort_order = EXCLUDED.sort_order,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [
                tenant_id,
                layer,
                category_id,
                category.get("enabled", True) is not False,
                int(category.get("sort_order", 999) or 999),
                self.jsonb(category),
            ],
        )

    def list_categories(self, tenant_id: str, *, layer: str | None = None, enabled_only: bool = True) -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if layer:
            filters.append("layer = %s")
            params.append(layer)
        if enabled_only:
            filters.append("enabled = true")
        rows = self.fetchall(
            f"""
            SELECT payload
            FROM {self.schema}.knowledge_categories
            WHERE {" AND ".join(filters)}
            ORDER BY sort_order ASC, category_id ASC
            """,
            params,
        )
        return [row["payload"] for row in rows]

    def upsert_knowledge_item(
        self,
        tenant_id: str,
        layer: str,
        category_id: str,
        item: dict[str, Any],
        *,
        product_id: str = "",
    ) -> None:
        item_id = str(item.get("id") or "")
        if not item_id:
            raise ValueError("item id is required")
        status = str(item.get("status") or "active")
        product_id = product_id or str(((item.get("data") or {}) if isinstance(item.get("data"), dict) else {}).get("product_id") or "")
        self.execute(
            f"""
            INSERT INTO {self.schema}.knowledge_items
              (tenant_id, layer, category_id, product_id, item_id, status, search_text, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (tenant_id, layer, category_id, product_id, item_id)
            DO UPDATE SET
              status = EXCLUDED.status,
              search_text = EXCLUDED.search_text,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [tenant_id, layer, category_id, product_id, item_id, status, search_text(item), self.jsonb(item)],
        )

    def list_knowledge_items(
        self,
        tenant_id: str,
        *,
        layer: str | None = None,
        category_id: str | None = None,
        product_id: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if layer:
            filters.append("layer = %s")
            params.append(layer)
        if category_id:
            filters.append("category_id = %s")
            params.append(category_id)
        if product_id is not None:
            filters.append("product_id = %s")
            params.append(product_id)
        if not include_archived:
            filters.append("status <> 'archived'")
        rows = self.fetchall(
            f"""
            SELECT payload
            FROM {self.schema}.knowledge_items
            WHERE {" AND ".join(filters)}
            ORDER BY category_id ASC, product_id ASC, item_id ASC
            """,
            params,
        )
        return [row["payload"] for row in rows]

    def get_knowledge_item(
        self,
        tenant_id: str,
        *,
        layer: str,
        category_id: str,
        item_id: str,
        product_id: str = "",
    ) -> dict[str, Any] | None:
        row = self.fetchone(
            f"""
            SELECT payload
            FROM {self.schema}.knowledge_items
            WHERE tenant_id = %s AND layer = %s AND category_id = %s AND product_id = %s AND item_id = %s
            """,
            [tenant_id, layer, category_id, product_id, item_id],
        )
        return row["payload"] if row else None

    def archive_knowledge_item(
        self,
        tenant_id: str,
        *,
        layer: str,
        category_id: str,
        item_id: str,
        product_id: str = "",
    ) -> None:
        self.execute(
            f"""
            UPDATE {self.schema}.knowledge_items
            SET status = 'archived',
                payload = jsonb_set(payload, '{{status}}', '"archived"', true),
                updated_at = now()
            WHERE tenant_id = %s AND layer = %s AND category_id = %s AND product_id = %s AND item_id = %s
            """,
            [tenant_id, layer, category_id, product_id, item_id],
        )

    def upsert_rag_source(self, source: dict[str, Any]) -> None:
        self.execute(
            f"""
            INSERT INTO {self.schema}.rag_sources
              (tenant_id, source_id, source_type, category, product_id, source_path, content_hash, status, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (source_id)
            DO UPDATE SET
              source_type = EXCLUDED.source_type,
              category = EXCLUDED.category,
              product_id = EXCLUDED.product_id,
              source_path = EXCLUDED.source_path,
              content_hash = EXCLUDED.content_hash,
              status = EXCLUDED.status,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [
                source.get("tenant_id") or self.tenant_id,
                source.get("source_id"),
                source.get("source_type") or "",
                source.get("category") or "",
                source.get("product_id") or "",
                source.get("source_path") or "",
                source.get("content_hash") or "",
                source.get("status") or "active",
                self.jsonb(source),
            ],
        )

    def list_rag_sources(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"""
            SELECT payload
            FROM {self.schema}.rag_sources
            WHERE tenant_id = %s AND status = 'active'
            ORDER BY source_type ASC, source_id ASC
            """,
            [tenant_id],
        )
        return [row["payload"] for row in rows]

    def delete_rag_source_by_path(self, tenant_id: str, source_path: str) -> int:
        row = self.fetchone(
            f"SELECT count(*) AS count FROM {self.schema}.rag_sources WHERE tenant_id = %s AND source_path = %s AND status = 'active'",
            [tenant_id, source_path],
        )
        deleted = int(row["count"] if row else 0)
        self.execute(
            f"UPDATE {self.schema}.rag_sources SET status = 'deleted', updated_at = now() WHERE tenant_id = %s AND source_path = %s",
            [tenant_id, source_path],
        )
        self.execute(
            f"""
            UPDATE {self.schema}.rag_chunks
            SET status = 'deleted'
            WHERE tenant_id = %s
              AND source_id IN (SELECT source_id FROM {self.schema}.rag_sources WHERE tenant_id = %s AND source_path = %s)
            """,
            [tenant_id, tenant_id, source_path],
        )
        return deleted

    def replace_rag_chunks(self, source_id: str, chunks: list[dict[str, Any]]) -> None:
        self.execute(f"DELETE FROM {self.schema}.rag_chunks WHERE source_id = %s", [source_id])
        for chunk in chunks:
            self.execute(
                f"""
                INSERT INTO {self.schema}.rag_chunks
                  (tenant_id, chunk_id, source_id, source_type, category, product_id, chunk_index, text, status, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id)
                DO UPDATE SET
                  source_type = EXCLUDED.source_type,
                  category = EXCLUDED.category,
                  product_id = EXCLUDED.product_id,
                  chunk_index = EXCLUDED.chunk_index,
                  text = EXCLUDED.text,
                  status = EXCLUDED.status,
                  payload = EXCLUDED.payload
                """,
                [
                    chunk.get("tenant_id") or self.tenant_id,
                    chunk.get("chunk_id"),
                    source_id,
                    chunk.get("source_type") or "",
                    chunk.get("category") or "",
                    chunk.get("product_id") or "",
                    int(chunk.get("chunk_index", 0) or 0),
                    chunk.get("text") or "",
                    chunk.get("status") or "active",
                    self.jsonb(chunk),
                ],
            )

    def list_rag_chunks(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"""
            SELECT payload
            FROM {self.schema}.rag_chunks
            WHERE tenant_id = %s AND status = 'active'
            ORDER BY source_id ASC, chunk_index ASC
            """,
            [tenant_id],
        )
        return [row["payload"] for row in rows]

    def replace_rag_index(self, tenant_id: str, entries: list[dict[str, Any]]) -> None:
        self.execute(f"DELETE FROM {self.schema}.rag_index_entries WHERE tenant_id = %s", [tenant_id])
        for entry in entries:
            self.execute(
                f"""
                INSERT INTO {self.schema}.rag_index_entries
                  (tenant_id, chunk_id, source_id, terms, semantic_terms, risk_terms, payload, built_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (chunk_id)
                DO UPDATE SET
                  source_id = EXCLUDED.source_id,
                  terms = EXCLUDED.terms,
                  semantic_terms = EXCLUDED.semantic_terms,
                  risk_terms = EXCLUDED.risk_terms,
                  payload = EXCLUDED.payload,
                  built_at = now()
                """,
                [
                    tenant_id,
                    entry.get("chunk_id"),
                    entry.get("source_id") or "",
                    self.jsonb(entry.get("terms", []) or []),
                    self.jsonb(entry.get("semantic_terms", []) or []),
                    self.jsonb(entry.get("risk_terms", []) or []),
                    self.jsonb(entry),
                ],
            )

    def list_rag_index(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"SELECT payload FROM {self.schema}.rag_index_entries WHERE tenant_id = %s ORDER BY source_id ASC, chunk_id ASC",
            [tenant_id],
        )
        return [row["payload"] for row in rows]

    def upsert_rag_experience(self, item: dict[str, Any]) -> None:
        self.execute(
            f"""
            INSERT INTO {self.schema}.rag_experiences
              (tenant_id, experience_id, status, summary, question, reply_text, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (experience_id)
            DO UPDATE SET
              status = EXCLUDED.status,
              summary = EXCLUDED.summary,
              question = EXCLUDED.question,
              reply_text = EXCLUDED.reply_text,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [
                item.get("tenant_id") or self.tenant_id,
                item.get("experience_id"),
                item.get("status") or "active",
                item.get("summary") or "",
                item.get("question") or "",
                item.get("reply_text") or "",
                self.jsonb(item),
            ],
        )

    def list_rag_experiences(self, tenant_id: str, *, status: str = "active", limit: int = 100) -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if status and status != "all":
            filters.append("status = %s")
            params.append(status)
        params.append(max(1, min(int(limit or 100), 500)))
        rows = self.fetchall(
            f"""
            SELECT payload
            FROM {self.schema}.rag_experiences
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        return [row["payload"] for row in rows]

    def set_kv(self, tenant_id: str, namespace: str, key: str, payload: Any) -> None:
        self.execute(
            f"""
            INSERT INTO {self.schema}.app_kv (tenant_id, namespace, key, payload, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (tenant_id, namespace, key)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
            """,
            [tenant_id, namespace, key, self.jsonb(payload)],
        )

    def get_kv(self, tenant_id: str, namespace: str, key: str) -> Any | None:
        row = self.fetchone(
            f"SELECT payload FROM {self.schema}.app_kv WHERE tenant_id = %s AND namespace = %s AND key = %s",
            [tenant_id, namespace, key],
        )
        return row["payload"] if row else None

    def upsert_candidate(self, tenant_id: str, candidate: dict[str, Any], *, status: str = "") -> None:
        candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "")
        if not candidate_id:
            raise ValueError("candidate_id is required")
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
        patch = candidate.get("formal_patch") if isinstance(candidate.get("formal_patch"), dict) else {}
        self.execute(
            f"""
            INSERT INTO {self.schema}.review_candidates
              (tenant_id, candidate_id, status, target_category, dedupe_key, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (candidate_id)
            DO UPDATE SET
              status = EXCLUDED.status,
              target_category = EXCLUDED.target_category,
              dedupe_key = EXCLUDED.dedupe_key,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [
                tenant_id,
                candidate_id,
                status or str(review.get("status") or "pending"),
                str(patch.get("target_category") or proposal.get("target_category") or ""),
                str(candidate.get("dedupe_key") or ""),
                self.jsonb(candidate),
            ],
        )

    def list_candidates(self, tenant_id: str, *, status: str = "pending") -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if status and status != "all":
            filters.append("status = %s")
            params.append(status)
        rows = self.fetchall(
            f"""
            SELECT payload
            FROM {self.schema}.review_candidates
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC, candidate_id DESC
            """,
            params,
        )
        return [row["payload"] for row in rows]

    def upsert_upload(self, tenant_id: str, record: dict[str, Any]) -> None:
        upload_id = str(record.get("upload_id") or "")
        if not upload_id:
            raise ValueError("upload_id is required")
        self.execute(
            f"""
            INSERT INTO {self.schema}.uploads
              (tenant_id, upload_id, kind, filename, stored_path, sha256, learned, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (upload_id)
            DO UPDATE SET
              kind = EXCLUDED.kind,
              filename = EXCLUDED.filename,
              stored_path = EXCLUDED.stored_path,
              sha256 = EXCLUDED.sha256,
              learned = EXCLUDED.learned,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [
                tenant_id,
                upload_id,
                record.get("kind") or "",
                record.get("filename") or "",
                record.get("path") or record.get("stored_path") or "",
                record.get("sha256") or "",
                bool(record.get("learned", False)),
                self.jsonb(record),
            ],
        )

    def list_uploads(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"SELECT payload FROM {self.schema}.uploads WHERE tenant_id = %s ORDER BY updated_at DESC, upload_id DESC",
            [tenant_id],
        )
        return [row["payload"] for row in rows]

    def delete_upload(self, tenant_id: str, upload_id: str) -> None:
        self.execute(f"DELETE FROM {self.schema}.uploads WHERE tenant_id = %s AND upload_id = %s", [tenant_id, upload_id])

    def upsert_version(self, tenant_id: str, version: dict[str, Any]) -> None:
        version_id = str(version.get("version_id") or "")
        if not version_id:
            raise ValueError("version_id is required")
        self.execute(
            f"""
            INSERT INTO {self.schema}.version_snapshots (tenant_id, version_id, reason, payload, created_at)
            VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, now()))
            ON CONFLICT (version_id)
            DO UPDATE SET reason = EXCLUDED.reason, payload = EXCLUDED.payload
            """,
            [
                tenant_id,
                version_id,
                version.get("reason") or "",
                self.jsonb(version),
                version.get("created_at") or None,
            ],
        )

    def list_versions(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"SELECT payload FROM {self.schema}.version_snapshots WHERE tenant_id = %s ORDER BY created_at DESC, version_id DESC",
            [tenant_id],
        )
        return [row["payload"] for row in rows]

    def get_version(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        row = self.fetchone(
            f"SELECT payload FROM {self.schema}.version_snapshots WHERE tenant_id = %s AND version_id = %s",
            [tenant_id, version_id],
        )
        return row["payload"] if row else None

    def append_audit(self, tenant_id: str, action: str, payload: dict[str, Any]) -> None:
        self.execute(
            f"INSERT INTO {self.schema}.audit_events (tenant_id, action, payload) VALUES (%s, %s, %s)",
            [tenant_id, action, self.jsonb(payload)],
        )

    def counts(self, tenant_id: str) -> dict[str, int]:
        tables = {
            "knowledge_categories": "tenant_id = %s",
            "knowledge_items": "tenant_id = %s",
            "review_candidates": "tenant_id = %s",
            "uploads": "tenant_id = %s",
            "version_snapshots": "tenant_id = %s",
            "rag_sources": "tenant_id = %s",
            "rag_chunks": "tenant_id = %s",
            "rag_index_entries": "tenant_id = %s",
            "rag_experiences": "tenant_id = %s",
            "app_kv": "tenant_id = %s",
            "audit_events": "tenant_id = %s",
            "work_queue_jobs": "tenant_id = %s",
            "handoff_cases": "tenant_id = %s",
            "runtime_heartbeats": "tenant_id = %s",
        }
        result: dict[str, int] = {}
        for table, where in tables.items():
            row = self.fetchone(f"SELECT count(*) AS count FROM {self.schema}.{table} WHERE {where}", [tenant_id])
            result[table] = int(row["count"] if row else 0)
        return result

    def enqueue_job(self, tenant_id: str, job: dict[str, Any]) -> dict[str, Any]:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            raise ValueError("job_id is required")
        self.execute(
            f"""
            INSERT INTO {self.schema}.work_queue_jobs
              (tenant_id, job_id, queue, kind, status, priority, dedupe_key, attempts, max_attempts, available_at, payload, updated_at)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, 0, %s, COALESCE(%s::timestamptz, now()), %s, now())
            ON CONFLICT (job_id)
            DO UPDATE SET
              payload = EXCLUDED.payload,
              priority = EXCLUDED.priority,
              max_attempts = EXCLUDED.max_attempts,
              available_at = EXCLUDED.available_at,
              updated_at = now()
            """,
            [
                tenant_id,
                job_id,
                job.get("queue") or "default",
                job.get("kind") or "generic",
                int(job.get("priority", 5) or 5),
                job.get("dedupe_key") or "",
                int(job.get("max_attempts", 3) or 3),
                job.get("available_at") or None,
                self.jsonb(job.get("payload", {}) or {}),
            ],
        )
        return self.get_job(tenant_id, job_id) or job

    def get_job(self, tenant_id: str, job_id: str) -> dict[str, Any] | None:
        row = self.fetchone(
            f"""
            SELECT tenant_id, job_id, queue, kind, status, priority, dedupe_key, attempts, max_attempts,
                   available_at, locked_until, locked_by, payload, result, error, created_at, updated_at, finished_at
            FROM {self.schema}.work_queue_jobs
            WHERE tenant_id = %s AND job_id = %s
            """,
            [tenant_id, job_id],
        )
        return normalize_job_row(row) if row else None

    def list_jobs(self, tenant_id: str, *, status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if status and status != "all":
            filters.append("status = %s")
            params.append(status)
        params.append(max(1, min(int(limit or 100), 500)))
        rows = self.fetchall(
            f"""
            SELECT tenant_id, job_id, queue, kind, status, priority, dedupe_key, attempts, max_attempts,
                   available_at, locked_until, locked_by, payload, result, error, created_at, updated_at, finished_at
            FROM {self.schema}.work_queue_jobs
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC, job_id DESC
            LIMIT %s
            """,
            params,
        )
        return [normalize_job_row(row) for row in rows]

    def claim_jobs(self, tenant_id: str, *, queue: str = "default", worker_id: str = "", limit: int = 1, lock_seconds: int = 300) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"""
            SELECT job_id
            FROM {self.schema}.work_queue_jobs
            WHERE tenant_id = %s
              AND queue = %s
              AND status = 'pending'
              AND available_at <= now()
              AND (locked_until IS NULL OR locked_until < now())
            ORDER BY priority ASC, created_at ASC
            LIMIT %s
            """,
            [tenant_id, queue or "default", max(1, min(int(limit or 1), 20))],
        )
        claimed: list[dict[str, Any]] = []
        for row in rows:
            job_id = str(row["job_id"])
            self.execute(
                f"""
                UPDATE {self.schema}.work_queue_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    locked_by = %s,
                    locked_until = now() + (%s || ' seconds')::interval,
                    updated_at = now()
                WHERE tenant_id = %s AND job_id = %s AND status = 'pending'
                """,
                [worker_id or "worker", int(lock_seconds or 300), tenant_id, job_id],
            )
            job = self.get_job(tenant_id, job_id)
            if job and job.get("status") == "running":
                claimed.append(job)
        return claimed

    def complete_job(self, tenant_id: str, job_id: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.execute(
            f"""
            UPDATE {self.schema}.work_queue_jobs
            SET status = 'succeeded',
                result = %s,
                error = '',
                locked_until = NULL,
                finished_at = now(),
                updated_at = now()
            WHERE tenant_id = %s AND job_id = %s
            """,
            [self.jsonb(result or {}), tenant_id, job_id],
        )
        return self.get_job(tenant_id, job_id)

    def fail_job(self, tenant_id: str, job_id: str, error: str, *, retry: bool = True) -> dict[str, Any] | None:
        job = self.get_job(tenant_id, job_id)
        if not job:
            return None
        attempts = int(job.get("attempts", 0) or 0)
        max_attempts = int(job.get("max_attempts", 3) or 3)
        status = "pending" if retry and attempts < max_attempts else "failed"
        finished_expr = "NULL" if status == "pending" else "now()"
        self.execute(
            f"""
            UPDATE {self.schema}.work_queue_jobs
            SET status = %s,
                error = %s,
                locked_until = NULL,
                locked_by = '',
                finished_at = {finished_expr},
                updated_at = now()
            WHERE tenant_id = %s AND job_id = %s
            """,
            [status, error, tenant_id, job_id],
        )
        return self.get_job(tenant_id, job_id)

    def cancel_job(self, tenant_id: str, job_id: str, reason: str = "") -> dict[str, Any] | None:
        self.execute(
            f"""
            UPDATE {self.schema}.work_queue_jobs
            SET status = 'cancelled',
                error = %s,
                locked_until = NULL,
                locked_by = '',
                finished_at = now(),
                updated_at = now()
            WHERE tenant_id = %s AND job_id = %s
            """,
            [reason, tenant_id, job_id],
        )
        return self.get_job(tenant_id, job_id)

    def job_summary(self, tenant_id: str) -> dict[str, Any]:
        rows = self.fetchall(
            f"""
            SELECT status, count(*) AS count
            FROM {self.schema}.work_queue_jobs
            WHERE tenant_id = %s
            GROUP BY status
            """,
            [tenant_id],
        )
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "succeeded": counts.get("succeeded", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "by_status": counts,
        }

    def upsert_heartbeat(
        self,
        tenant_id: str,
        *,
        component_id: str,
        status: str = "ok",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.execute(
            f"""
            INSERT INTO {self.schema}.runtime_heartbeats
              (tenant_id, component_id, status, message, payload, last_seen_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (tenant_id, component_id)
            DO UPDATE SET
              status = EXCLUDED.status,
              message = EXCLUDED.message,
              payload = EXCLUDED.payload,
              last_seen_at = now()
            """,
            [tenant_id, component_id, status or "ok", message or "", self.jsonb(payload or {})],
        )
        return self.get_heartbeat(tenant_id, component_id) or {}

    def get_heartbeat(self, tenant_id: str, component_id: str) -> dict[str, Any] | None:
        row = self.fetchone(
            f"""
            SELECT tenant_id, component_id, status, message, payload, last_seen_at
            FROM {self.schema}.runtime_heartbeats
            WHERE tenant_id = %s AND component_id = %s
            """,
            [tenant_id, component_id],
        )
        return normalize_heartbeat_row(row) if row else None

    def list_heartbeats(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            f"""
            SELECT tenant_id, component_id, status, message, payload, last_seen_at
            FROM {self.schema}.runtime_heartbeats
            WHERE tenant_id = %s
            ORDER BY last_seen_at DESC, component_id ASC
            """,
            [tenant_id],
        )
        return [normalize_heartbeat_row(row) for row in rows]

    def upsert_handoff_case(self, tenant_id: str, case_item: dict[str, Any]) -> dict[str, Any]:
        case_id = str(case_item.get("case_id") or "")
        if not case_id:
            raise ValueError("case_id is required")
        self.execute(
            f"""
            INSERT INTO {self.schema}.handoff_cases
              (tenant_id, case_id, target, status, priority, reason, message_ids, message_contents,
               reply_text, operator_alert, product_context, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (case_id)
            DO UPDATE SET
              status = EXCLUDED.status,
              priority = EXCLUDED.priority,
              reason = EXCLUDED.reason,
              message_ids = EXCLUDED.message_ids,
              message_contents = EXCLUDED.message_contents,
              reply_text = EXCLUDED.reply_text,
              operator_alert = EXCLUDED.operator_alert,
              product_context = EXCLUDED.product_context,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            [
                tenant_id,
                case_id,
                case_item.get("target") or "",
                case_item.get("status") or "open",
                int(case_item.get("priority", 1) or 1),
                case_item.get("reason") or "",
                self.jsonb(case_item.get("message_ids", []) or []),
                self.jsonb(case_item.get("message_contents", []) or []),
                case_item.get("reply_text") or "",
                self.jsonb(case_item.get("operator_alert", {}) or {}),
                self.jsonb(case_item.get("product_context", {}) or {}),
                self.jsonb(case_item),
            ],
        )
        return self.get_handoff_case(tenant_id, case_id) or case_item

    def get_handoff_case(self, tenant_id: str, case_id: str) -> dict[str, Any] | None:
        row = self.fetchone(
            f"""
            SELECT tenant_id, case_id, target, status, priority, reason, message_ids, message_contents,
                   reply_text, operator_alert, product_context, payload, resolution, created_at, updated_at, resolved_at
            FROM {self.schema}.handoff_cases
            WHERE tenant_id = %s AND case_id = %s
            """,
            [tenant_id, case_id],
        )
        return normalize_handoff_row(row) if row else None

    def list_handoff_cases(self, tenant_id: str, *, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if status and status != "all":
            filters.append("status = %s")
            params.append(status)
        params.append(max(1, min(int(limit or 100), 500)))
        rows = self.fetchall(
            f"""
            SELECT tenant_id, case_id, target, status, priority, reason, message_ids, message_contents,
                   reply_text, operator_alert, product_context, payload, resolution, created_at, updated_at, resolved_at
            FROM {self.schema}.handoff_cases
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC, case_id DESC
            LIMIT %s
            """,
            params,
        )
        return [normalize_handoff_row(row) for row in rows]

    def update_handoff_status(self, tenant_id: str, case_id: str, status: str, resolution: dict[str, Any] | None = None) -> dict[str, Any] | None:
        resolved_expr = "now()" if status in {"resolved", "ignored"} else "NULL"
        self.execute(
            f"""
            UPDATE {self.schema}.handoff_cases
            SET status = %s,
                resolution = %s,
                resolved_at = {resolved_expr},
                updated_at = now()
            WHERE tenant_id = %s AND case_id = %s
            """,
            [status, self.jsonb(resolution or {}), tenant_id, case_id],
        )
        return self.get_handoff_case(tenant_id, case_id)

    def handoff_summary(self, tenant_id: str) -> dict[str, Any]:
        rows = self.fetchall(
            f"""
            SELECT status, count(*) AS count
            FROM {self.schema}.handoff_cases
            WHERE tenant_id = %s
            GROUP BY status
            """,
            [tenant_id],
        )
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "total": sum(counts.values()),
            "open": counts.get("open", 0),
            "acknowledged": counts.get("acknowledged", 0),
            "resolved": counts.get("resolved", 0),
            "ignored": counts.get("ignored", 0),
            "by_status": counts,
        }

    def execute(self, query: str, params: list[Any] | tuple[Any, ...] | None = None) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or [])

    def fetchone(self, query: str, params: list[Any] | tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or [])
                return cur.fetchone()

    def fetchall(self, query: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or [])
                return list(cur.fetchall())

    def connect(self):
        psycopg, dict_row = self._psycopg()
        return psycopg.connect(self.config.postgres_dsn, autocommit=True, row_factory=dict_row)

    def jsonb(self, value: Any) -> Any:
        _, _, Jsonb = self._json_adapter()
        return Jsonb(value)

    def _require_available(self) -> None:
        availability = self.availability()
        if not availability.ok:
            raise RuntimeError(availability.reason)

    def _psycopg(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg, dict_row

    def _json_adapter(self):
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        return psycopg, dict_row, Jsonb


def get_postgres_store(*, tenant_id: str | None = None, config: StorageConfig | None = None) -> PostgresJsonStore:
    return PostgresJsonStore(config=config, tenant_id=tenant_id)


def normalize_job_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("available_at", "locked_until", "created_at", "updated_at", "finished_at"):
        value = result.get(key)
        if value is not None and hasattr(value, "isoformat"):
            result[key] = value.isoformat(timespec="seconds")
    return result


def normalize_handoff_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    for key, value in payload.items():
        result.setdefault(key, value)
    for key in ("created_at", "updated_at", "resolved_at"):
        value = result.get(key)
        if value is not None and hasattr(value, "isoformat"):
            result[key] = value.isoformat(timespec="seconds")
    return result


def normalize_heartbeat_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    value = result.get("last_seen_at")
    if value is not None and hasattr(value, "isoformat"):
        result["last_seen_at"] = value.isoformat(timespec="seconds")
    return result


def search_text(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    parts = [
        payload.get("id"),
        payload.get("category_id"),
        data.get("name"),
        data.get("title"),
        data.get("sku"),
        data.get("answer"),
        data.get("content"),
        data.get("customer_message"),
        data.get("service_reply"),
        json.dumps(data.get("additional_details", {}), ensure_ascii=False) if isinstance(data.get("additional_details"), dict) else "",
    ]
    for key in ("aliases", "keywords", "intent_tags", "tone_tags"):
        value = data.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(str(part) for part in parts if part)
