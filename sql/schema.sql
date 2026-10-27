-- Soccer Team Points Tracker — database schema, RLS policies, and RPCs.
-- Run this entire file once in the Supabase SQL editor on a fresh project.
-- Safe to re-run: most statements use IF NOT EXISTS / CREATE OR REPLACE,
-- but DROP POLICY IF EXISTS guards are included for idempotent policy setup.

-- ============================================================================
-- Extensions
-- ============================================================================
create extension if not exists pgcrypto;

-- ============================================================================
-- Tables
-- ============================================================================

create table if not exists public.players (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  normalized_name text not null unique,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.point_events (
  id uuid primary key default gen_random_uuid(),
  player_id uuid not null references public.players(id) on delete restrict,
  category text not null check (category in ('win', 'goal', 'assist')),
  created_at timestamptz not null default now(),
  created_by uuid not null default auth.uid() references auth.users(id)
);

create table if not exists public.editor_allowlist (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- Indexes
-- ============================================================================

create index if not exists idx_point_events_player_category_created
  on public.point_events (player_id, category, created_at);

create index if not exists idx_point_events_created_at
  on public.point_events (created_at desc);

create index if not exists idx_players_active_name
  on public.players (active, name);

-- ============================================================================
-- Name normalization (server-side, so direct API writes can't bypass it)
-- ============================================================================

-- Mirrors the Python-side normalization: strip, collapse internal whitespace,
-- casefold. Used by a trigger so normalized_name is always derived from name,
-- never trusted from client input.
create or replace function public.normalize_player_name(raw_name text)
returns text
language sql
immutable
as $$
  select lower(trim(regexp_replace(coalesce(raw_name, ''), '\s+', ' ', 'g')));
$$;

create or replace function public.players_set_normalized_name()
returns trigger
language plpgsql
as $$
begin
  new.name := trim(regexp_replace(coalesce(new.name, ''), '\s+', ' ', 'g'));
  if new.name = '' then
    raise exception 'player name must not be empty';
  end if;
  new.normalized_name := public.normalize_player_name(new.name);
  return new;
end;
$$;

drop trigger if exists trg_players_set_normalized_name on public.players;
create trigger trg_players_set_normalized_name
  before insert or update of name on public.players
  for each row
  execute function public.players_set_normalized_name();

-- ============================================================================
-- Editor-allowlist membership check
--
-- SECURITY DEFINER is required here, not just for the RPC public code calls
-- directly: editor_allowlist has RLS enabled with NO select policy for any
-- client role (by design — nobody should be able to read it directly). A
-- plain "exists (select 1 from editor_allowlist where ...)" written inline
-- inside another table's RLS policy is STILL subject to editor_allowlist's
-- own RLS when it runs, even nested like that — so it would silently see
-- zero rows and always evaluate false, locking out every real editor. This
-- function runs with the definer's privileges instead, which is what
-- actually lets the lookup see the row. Every policy below calls this
-- function rather than querying editor_allowlist inline.
-- ============================================================================

create or replace function public.is_approved_editor()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.editor_allowlist a where a.user_id = auth.uid()
  );
$$;

revoke all on function public.is_approved_editor() from public, anon;
grant execute on function public.is_approved_editor() to authenticated;

-- ============================================================================
-- Row Level Security
-- ============================================================================

alter table public.players enable row level security;
alter table public.point_events enable row level security;
alter table public.editor_allowlist enable row level security;

-- --- players -----------------------------------------------------------

drop policy if exists players_public_select on public.players;
create policy players_public_select
  on public.players
  for select
  to anon, authenticated
  using (true);

drop policy if exists players_editor_insert on public.players;
create policy players_editor_insert
  on public.players
  for insert
  to authenticated
  with check (public.is_approved_editor());

drop policy if exists players_editor_update on public.players;
create policy players_editor_update
  on public.players
  for update
  to authenticated
  using (public.is_approved_editor())
  with check (public.is_approved_editor());

-- No delete policy at all: direct player deletion is intentionally impossible
-- (players are deactivated, never deleted, per v1 scope).

-- --- point_events --------------------------------------------------------

drop policy if exists point_events_public_select on public.point_events;
create policy point_events_public_select
  on public.point_events
  for select
  to anon, authenticated
  using (true);

drop policy if exists point_events_editor_insert on public.point_events;
create policy point_events_editor_insert
  on public.point_events
  for insert
  to authenticated
  with check (created_by = auth.uid() and public.is_approved_editor());

drop policy if exists point_events_editor_delete on public.point_events;
create policy point_events_editor_delete
  on public.point_events
  for delete
  to authenticated
  using (public.is_approved_editor());

-- No update policy: point_events rows are immutable once inserted.

-- --- editor_allowlist ------------------------------------------------------

-- No public SELECT, no INSERT/UPDATE/DELETE policies for any client role.
-- The owner manages this table exclusively via the Supabase dashboard
-- (table editor or SQL editor), which uses the service role and bypasses RLS.
-- Ordinary editors get no policy that would let them read or write this
-- table at all — not even their own row — which is why is_approved_editor()
-- above exists as a security-definer escape hatch for self-checks only.

-- ============================================================================
-- Other RPCs
-- ============================================================================

-- Atomically awards one win event to every active player. Re-checks
-- allowlist membership itself (never trust the caller's client-side gating).
create or replace function public.award_team_win()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  affected integer;
begin
  if not public.is_approved_editor() then
    raise exception 'not an approved editor';
  end if;

  insert into public.point_events (player_id, category, created_by)
  select p.id, 'win', auth.uid()
  from public.players p
  where p.active;

  select count(*) into affected from public.players where active;
  return affected;
end;
$$;

revoke all on function public.award_team_win() from public, anon;
grant execute on function public.award_team_win() to authenticated;

-- ============================================================================
-- Aggregated totals view (security-invoker: respects the querying role's
-- own RLS grants rather than the view owner's, so it can never leak beyond
-- what players/point_events already expose).
-- ============================================================================

create or replace view public.player_totals
with (security_invoker = true)
as
select
  p.id as player_id,
  p.name,
  p.active,
  coalesce(sum((pe.category = 'win')::int), 0) as wins,
  coalesce(sum((pe.category = 'goal')::int), 0) as goals,
  coalesce(sum((pe.category = 'assist')::int), 0) as assists,
  coalesce(count(pe.id), 0) as total
from public.players p
left join public.point_events pe on pe.player_id = p.id
group by p.id, p.name, p.active;

grant select on public.player_totals to anon, authenticated;
