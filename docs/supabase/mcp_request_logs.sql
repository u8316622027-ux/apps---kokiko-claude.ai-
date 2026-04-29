create table if not exists public.mcp_request_logs2 (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  request_payload jsonb not null,
  response_payload jsonb
);

create index if not exists mcp_request_logs2_created_at_idx
  on public.mcp_request_logs2 (created_at desc);
