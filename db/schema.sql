-- Green Media AI Command Center — PostgreSQL schema (blueprint §4).
-- Multi-tenant from day one: every row carries tenant_id so the internal tool can become a SaaS without a rebuild.
-- Row-level security isolates tenants; the API sets `app.tenant_id` per request.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE tenants (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text NOT NULL,
  plan         text NOT NULL DEFAULT 'agency',          -- starter | growth | pro | agency
  custom_domain text UNIQUE,
  branding_json jsonb NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE roles (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants(id),
  name             text NOT NULL,                      -- admin | account_manager | seo | content | designer | client
  permissions_json jsonb NOT NULL DEFAULT '[]',
  UNIQUE (tenant_id, name)
);

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  name          text NOT NULL,
  email         citext NOT NULL,
  password_hash text NOT NULL,
  totp_secret_enc bytea,                               -- optional 2FA, encrypted at rest
  role_id       uuid NOT NULL REFERENCES roles(id),
  client_id     uuid,                                  -- set for client-portal users
  status        text NOT NULL DEFAULT 'active',
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE clients (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  company_name       text NOT NULL,
  website            text,
  industry           text,
  city               text,
  status             text NOT NULL DEFAULT 'onboarding', -- active | onboarding | paused
  account_manager_id uuid REFERENCES users(id),
  brand_voice_json   jsonb NOT NULL DEFAULT '{}',        -- tone, preferred phrases, prohibited claims, CTA, languages, escalation
  auto_publish_json  jsonb NOT NULL DEFAULT '{}',        -- per-channel; empty = human approval everywhere
  notes              text,
  created_at         timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE users ADD CONSTRAINT users_client_fk FOREIGN KEY (client_id) REFERENCES clients(id);

CREATE TABLE client_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name text NOT NULL, email text, phone text, designation text
);

CREATE TABLE services (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  name text NOT NULL, description text, active boolean NOT NULL DEFAULT true
);

CREATE TABLE client_services (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  service_id uuid NOT NULL REFERENCES services(id),
  plan text, start_date date, end_date date, status text NOT NULL DEFAULT 'active'
);

-- OAuth tokens are encrypted by the API (envelope encryption) before they reach the database.
CREATE TABLE gmb_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  location_id text NOT NULL, account_ref text, oauth_token_enc bytea, token_expires_at timestamptz,
  status text NOT NULL DEFAULT 'connected', last_sync timestamptz
);

CREATE TABLE gmb_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  external_review_id text NOT NULL, author text, rating smallint CHECK (rating BETWEEN 1 AND 5),
  review_text text, language text, sentiment text, reply text,
  reply_status text NOT NULL DEFAULT 'new',             -- new | drafted | approved | published | rejected | failed
  reviewed_at timestamptz, published_at timestamptz, publish_error text,
  UNIQUE (client_id, external_review_id)
);

CREATE TABLE social_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  platform text NOT NULL, account_ref text, handle text, oauth_token_enc bytea, token_expires_at timestamptz,
  status text NOT NULL DEFAULT 'connected'
);

CREATE TABLE content_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  topic text NOT NULL, content_type text NOT NULL, master_copy text, hashtags text[],
  creative_brief text, status text NOT NULL DEFAULT 'draft',
  created_by uuid REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE content_variants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  content_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  platform text NOT NULL, copy text, media_ref text, format text, status text NOT NULL DEFAULT 'draft'
);

CREATE TABLE scheduled_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  content_variant_id uuid NOT NULL REFERENCES content_variants(id),
  platform text NOT NULL, scheduled_at timestamptz NOT NULL,
  publish_status text NOT NULL DEFAULT 'scheduled',     -- scheduled | publishing | published | failed
  external_post_id text, error text, attempts int NOT NULL DEFAULT 0
);
CREATE INDEX scheduled_posts_due ON scheduled_posts (scheduled_at) WHERE publish_status = 'scheduled';

CREATE TABLE seo_keywords (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  keyword text NOT NULL, target_url text, location text, current_rank int, previous_rank int, volume int
);

CREATE TABLE analytics_daily (
  id bigserial PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  source text NOT NULL,                                 -- gmb | gsc | ga4 | facebook | instagram | ...
  metric text NOT NULL, metric_value numeric NOT NULL, date date NOT NULL,
  UNIQUE (client_id, source, metric, date)
);

CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid REFERENCES clients(id) ON DELETE CASCADE, assigned_to uuid REFERENCES users(id),
  title text NOT NULL, priority text NOT NULL DEFAULT 'medium', due_date date, status text NOT NULL DEFAULT 'todo'
);

CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  item_type text NOT NULL, item_id uuid NOT NULL, approver_id uuid REFERENCES users(id),
  status text NOT NULL DEFAULT 'pending', comments text, decided_at timestamptz
);

CREATE TABLE reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  period_start date NOT NULL, period_end date NOT NULL, summary text, file_ref text,
  delivered_at timestamptz, delivered_via text
);

CREATE TABLE audit_logs (
  id bigserial PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id),
  user_id uuid REFERENCES users(id), client_id uuid REFERENCES clients(id),
  action text NOT NULL, entity_type text, entity_id text, created_at timestamptz NOT NULL DEFAULT now()
);

-- Tenant isolation.
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['roles','users','clients','client_contacts','services','client_services','gmb_accounts','gmb_reviews',
                               'social_accounts','content_items','content_variants','scheduled_posts','seo_keywords','analytics_daily',
                               'tasks','approvals','reports','audit_logs'])
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'')::uuid)', t);
  END LOOP;
END $$;
