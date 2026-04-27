# PostgreSQL Schema And Repository Spec

## Schema 命名

默认 schema：`wechat_ai_customer_service`。所有表都放在该 schema 下，避免污染公共 `public` schema。

## 表设计

### tenants

租户主表。

- `tenant_id text primary key`
- `display_name text`
- `payload jsonb not null default '{}'`
- `created_at timestamptz`
- `updated_at timestamptz`

### knowledge_categories

分类 registry。覆盖全局、租户和商品专属虚拟分类。

- `tenant_id text not null`
- `category_id text not null`
- `layer text not null`
- `payload jsonb not null`
- `enabled boolean`
- `sort_order integer`
- primary key `(tenant_id, layer, category_id)`

### knowledge_items

正式知识条目。

- `tenant_id text not null`
- `layer text not null`：`shared`、`tenant`、`tenant_product`
- `category_id text not null`
- `item_id text not null`
- `product_id text not null default ''`
- `status text not null default 'active'`
- `search_text text not null default ''`
- `payload jsonb not null`
- `created_at timestamptz`
- `updated_at timestamptz`
- primary key `(tenant_id, layer, category_id, product_id, item_id)`

索引：

- `(tenant_id, category_id, status)`
- `(tenant_id, product_id, status)`
- `gin(payload jsonb_path_ops)`

### review_candidates

候选审核。

- `tenant_id text not null`
- `candidate_id text primary key`
- `status text not null`
- `target_category text`
- `dedupe_key text`
- `payload jsonb not null`
- `created_at timestamptz`
- `updated_at timestamptz`

### uploads

上传文件索引。文件内容本轮仍保留在文件系统，数据库保存索引和解析状态。

- `tenant_id text not null`
- `upload_id text primary key`
- `kind text not null`
- `filename text not null`
- `stored_path text not null`
- `sha256 text not null`
- `learned boolean not null default false`
- `payload jsonb not null`
- `created_at timestamptz`
- `updated_at timestamptz`

### audit_events

管理台审计日志。

- `event_id bigserial primary key`
- `tenant_id text not null`
- `action text not null`
- `payload jsonb not null`
- `created_at timestamptz not null`

### version_snapshots

版本快照元数据。

- `tenant_id text not null`
- `version_id text primary key`
- `reason text`
- `payload jsonb not null`
- `created_at timestamptz`

### rag_sources

RAG source 元数据。

- `tenant_id text not null`
- `source_id text primary key`
- `source_type text`
- `category text`
- `product_id text`
- `source_path text`
- `content_hash text`
- `status text`
- `payload jsonb not null`
- `created_at timestamptz`
- `updated_at timestamptz`

### rag_chunks

RAG chunk。

- `tenant_id text not null`
- `chunk_id text primary key`
- `source_id text not null`
- `source_type text`
- `category text`
- `product_id text`
- `chunk_index integer`
- `text text not null`
- `status text`
- `payload jsonb not null`
- `created_at timestamptz`

### rag_index_entries

RAG 检索索引条目。当前不是向量索引，而是混合检索所需的 term/semantic/risk 元数据。

- `tenant_id text not null`
- `chunk_id text primary key`
- `source_id text`
- `terms jsonb not null default '[]'`
- `semantic_terms jsonb not null default '[]'`
- `risk_terms jsonb not null default '[]'`
- `payload jsonb not null`
- `built_at timestamptz`

### rag_experiences

RAG 范畴内的自学习经验，不自动进入正式知识库。

- `tenant_id text not null`
- `experience_id text primary key`
- `status text not null`
- `summary text`
- `question text`
- `reply_text text`
- `payload jsonb not null`
- `created_at timestamptz`
- `updated_at timestamptz`

### app_kv

低频运行状态，例如诊断忽略项。

- `tenant_id text not null`
- `namespace text not null`
- `key text not null`
- `payload jsonb not null`
- `updated_at timestamptz`
- primary key `(tenant_id, namespace, key)`

## Repository Contract

所有业务服务只依赖 repository 方法，不直接拼 SQL。

必须提供：

- `available() -> bool`
- `initialize_schema() -> dict`
- `upsert_tenant(record)`
- `upsert_category(tenant_id, layer, category)`
- `list_categories(tenant_id, layer=None)`
- `upsert_knowledge_item(tenant_id, layer, category_id, item, product_id='')`
- `list_knowledge_items(tenant_id, category_id=None, layer=None, product_id=None, include_archived=False)`
- `get_knowledge_item(tenant_id, layer, category_id, item_id, product_id='')`
- `archive_knowledge_item(...)`
- `upsert_candidate/list_candidates/get_candidate/update_candidate/move_candidate_status`
- `upsert_upload/list_uploads/get_upload/delete_upload`
- `append_audit/list_audit`
- `upsert_rag_source/list_rag_sources/delete_rag_source`
- `upsert_rag_chunks/list_rag_chunks/delete_rag_chunks`
- `replace_rag_index/list_rag_index`
- `upsert_rag_experience/list_rag_experiences/update_rag_experience`
- `set_kv/get_kv`

## 数据完整性规则

- `payload` 必须保存完整原始结构，业务列只做索引和筛选。
- 所有 upsert 必须带 `updated_at`。
- 所有 list 默认过滤 `status=archived` 或 `discarded`，除非显式 include。
- RAG experience 不允许被 migration 自动提升为正式知识。
- 商品专属知识必须写入 `layer=tenant_product` 且 `product_id` 非空。
