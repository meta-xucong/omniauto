# VPS-LOCAL Sync And Backup Protocol

> 2026-05-05 更新：共享公共知识的正式来源已收敛到 VPS 云端 `shared_library`。客户端不再把 `pull_shared_patch` 写入 `data/shared_knowledge`，该命令现在表示刷新云端正式共享知识快照到 runtime 只读缓存；本文中涉及 `shared_knowledge` backup/restore 的内容仅保留为 legacy 数据迁移和运维参考。

## 1. Transport

Local talks to VPS over HTTPS JSON APIs. All write-like requests include:

```text
Authorization: Bearer <session token>
X-Device-ID: <stable local device id>
X-Request-ID: <uuid>
```

When `WECHAT_VPS_BASE_URL` is not configured, services return local/offline status instead of pretending that cloud sync succeeded.

## 2. Backup Manifest

Each backup package contains:

```text
manifest.json
payload/
  shared_knowledge/...
  tenants/<tenant_id>/...
```

Manifest shape:

```json
{
  "schema_version": 1,
  "backup_id": "backup_...",
  "scope": "tenant|shared|all",
  "tenant_id": "default",
  "created_at": "...",
  "include_derived": false,
  "files": [
    {
      "path": "payload/tenants/default/tenant.json",
      "sha256": "...",
      "bytes": 123
    }
  ]
}
```

## 3. Customer Tenant Backup

Included by default:

- tenant metadata
- formal knowledge bases
- product-scoped knowledge
- RAG sources
- RAG experience records
- tenant sync settings

Excluded by default:

- RAG chunks
- RAG index
- RAG cache
- transient locks
- live WeChat message state unless `include_runtime=true`

## 4. Shared Knowledge Candidate Upload

Customer local clients upload candidate observations:

```json
{
  "tenant_id": "default",
  "candidate_id": "shared_prop_...",
  "kind": "guideline|style|safety|faq_pattern",
  "summary": "...",
  "evidence": "...",
  "proposed_patch": {}
}
```

VPS never auto-publishes a candidate as formal shared knowledge. It produces a patch candidate for admin review.

## 5. Shared Patch Format

```json
{
  "schema_version": 1,
  "patch_id": "shared_patch_...",
  "version": "2026.04.29.1",
  "created_at": "...",
  "operations": [
    {
      "op": "upsert_json",
      "path": "global_guidelines/items/customer_service_style_guidelines.json",
      "content": {}
    }
  ],
  "signature": "optional-hmac-or-vps-signature"
}
```

Local safety checks:

- operation must be allow-listed.
- path must stay under `data/shared_knowledge`.
- JSON content must parse.
- version must be newer than current applied version.
- signature must verify when signing is configured.

## 6. Remote Commands

Command envelope:

```json
{
  "command_id": "cmd_...",
  "type": "backup_all|backup_tenant|pull_shared_patch|check_update",
  "tenant_id": "default",
  "payload": {},
  "issued_by": "admin",
  "expires_at": "...",
  "nonce": "...",
  "signature": "..."
}
```

Supported local commands in this phase:

- `backup_all`
- `backup_tenant`
- `pull_shared_patch`
- `check_update`

Unsupported command types are acknowledged as rejected, not ignored silently.

## 7. Update Metadata

```json
{
  "version": "0.2.0",
  "channel": "stable",
  "artifact_url": "https://...",
  "sha256": "...",
  "signature": "...",
  "notes": "..."
}
```

Local behavior:

- check latest update
- download only when explicitly requested
- verify hash/signature
- write status under runtime sync directory
- never overwrite source code silently

## 8. Restore Policy

Restore is two-step:

1. `restore-preview`: validate manifest, show changed files and conflicts.
2. `apply-restore`: apply only after explicit confirmation.

This phase implements backup generation and restore preview hooks. Destructive restore application remains guarded and should require user confirmation.

# 2026-05-05 Shared Knowledge Lease Addendum

Formal shared public knowledge is cloud-authoritative. Local clients no longer apply shared patches into `data/shared_knowledge`; `pull_shared_patch` now means "refresh the official cloud snapshot". The client stores only a read-only lease cache under `runtime/apps/wechat_ai_customer_service/cache/shared_knowledge/`.

The cache participates in runtime retrieval only while its cloud lease is valid:

- `source` must be `cloud_official_shared_library`.
- `cache_policy.mode` must be `cloud_authoritative_lease`.
- `expires_at` must be in the future.
- `requires_cloud_refresh` is true, so the client must keep refreshing against the VPS.

Production clients should set `WECHAT_VPS_BASE_URL` to the VPS HTTPS domain or public IP endpoint and set `WECHAT_VPS_AUTO_DISCOVER=0`.
