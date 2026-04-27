CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.tenants (
  tenant_id text PRIMARY KEY,
  display_name text NOT NULL DEFAULT '',
  payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {schema}.knowledge_categories (
  tenant_id text NOT NULL,
  layer text NOT NULL,
  category_id text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 999,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, layer, category_id)
);

CREATE TABLE IF NOT EXISTS {schema}.knowledge_items (
  tenant_id text NOT NULL,
  layer text NOT NULL,
  category_id text NOT NULL,
  product_id text NOT NULL DEFAULT '',
  item_id text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  search_text text NOT NULL DEFAULT '',
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, layer, category_id, product_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_category
  ON {schema}.knowledge_items (tenant_id, category_id, status);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_product
  ON {schema}.knowledge_items (tenant_id, product_id, status);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_payload
  ON {schema}.knowledge_items USING gin (payload jsonb_path_ops);

CREATE TABLE IF NOT EXISTS {schema}.review_candidates (
  tenant_id text NOT NULL,
  candidate_id text PRIMARY KEY,
  status text NOT NULL DEFAULT 'pending',
  target_category text NOT NULL DEFAULT '',
  dedupe_key text NOT NULL DEFAULT '',
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_candidates_tenant_status
  ON {schema}.review_candidates (tenant_id, status);

CREATE TABLE IF NOT EXISTS {schema}.uploads (
  tenant_id text NOT NULL,
  upload_id text PRIMARY KEY,
  kind text NOT NULL,
  filename text NOT NULL,
  stored_path text NOT NULL,
  sha256 text NOT NULL,
  learned boolean NOT NULL DEFAULT false,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uploads_tenant_kind
  ON {schema}.uploads (tenant_id, kind);

CREATE TABLE IF NOT EXISTS {schema}.audit_events (
  event_id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  action text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_action
  ON {schema}.audit_events (tenant_id, action, created_at DESC);

CREATE TABLE IF NOT EXISTS {schema}.version_snapshots (
  tenant_id text NOT NULL,
  version_id text PRIMARY KEY,
  reason text NOT NULL DEFAULT '',
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {schema}.rag_sources (
  tenant_id text NOT NULL,
  source_id text PRIMARY KEY,
  source_type text NOT NULL DEFAULT '',
  category text NOT NULL DEFAULT '',
  product_id text NOT NULL DEFAULT '',
  source_path text NOT NULL DEFAULT '',
  content_hash text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active',
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_sources_tenant_status
  ON {schema}.rag_sources (tenant_id, status);

CREATE TABLE IF NOT EXISTS {schema}.rag_chunks (
  tenant_id text NOT NULL,
  chunk_id text PRIMARY KEY,
  source_id text NOT NULL,
  source_type text NOT NULL DEFAULT '',
  category text NOT NULL DEFAULT '',
  product_id text NOT NULL DEFAULT '',
  chunk_index integer NOT NULL DEFAULT 0,
  text text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_source
  ON {schema}.rag_chunks (tenant_id, source_id, status);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_product
  ON {schema}.rag_chunks (tenant_id, product_id, status);

CREATE TABLE IF NOT EXISTS {schema}.rag_index_entries (
  tenant_id text NOT NULL,
  chunk_id text PRIMARY KEY,
  source_id text NOT NULL DEFAULT '',
  terms jsonb NOT NULL DEFAULT '[]'::jsonb,
  semantic_terms jsonb NOT NULL DEFAULT '[]'::jsonb,
  risk_terms jsonb NOT NULL DEFAULT '[]'::jsonb,
  payload jsonb NOT NULL,
  built_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_index_tenant
  ON {schema}.rag_index_entries (tenant_id);

CREATE TABLE IF NOT EXISTS {schema}.rag_experiences (
  tenant_id text NOT NULL,
  experience_id text PRIMARY KEY,
  status text NOT NULL DEFAULT 'active',
  summary text NOT NULL DEFAULT '',
  question text NOT NULL DEFAULT '',
  reply_text text NOT NULL DEFAULT '',
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_experiences_tenant_status
  ON {schema}.rag_experiences (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS {schema}.app_kv (
  tenant_id text NOT NULL,
  namespace text NOT NULL,
  key text NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, namespace, key)
);
