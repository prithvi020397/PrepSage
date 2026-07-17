-- Supabase schema for pawscode multi-user persistence.
-- Run with: supabase db reset  (local) or paste into the Supabase SQL editor (cloud).
-- All user-owned rows reference auth.users(id) via ON DELETE CASCADE.

-- ============================================================================
-- profiles: lightweight per-user row, created on signup via trigger (see bottom).
-- ============================================================================
create table if not exists public.profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    email       text,
    display_name text,
    created_at  timestamptz not null default now()
);

-- ============================================================================
-- progress: per-user spaced-repetition state.
-- Mirrors the old progress.json shape: qid -> {solved_at, fails, due_at, ...}
-- Stored as one row per (user, question) so we can upsert cheaply.
-- ============================================================================
create table if not exists public.progress (
    user_id    uuid not null references auth.users(id) on delete cascade,
    qid        text not null,
    solved_at  timestamptz,
    fails      integer not null default 0,
    due_at     timestamptz,
    -- working state (resettable without losing earned credit)
    code       text,
    trace      jsonb,
    pattern    text,
    skeleton   text,
    concept_map jsonb,
    updated_at timestamptz not null default now(),
    primary key (user_id, qid)
);

-- ============================================================================
-- history: append-only event timeline per user (trend dashboard).
-- Old: list of {ts, event, ...}. New: one row per event.
-- ============================================================================
create table if not exists public.history (
    id         bigint generated always as identity primary key,
    user_id    uuid not null references auth.users(id) on delete cascade,
    ts         timestamptz not null default now(),
    event      text not null,
    payload    jsonb
);

-- ============================================================================
-- chats: persisted chat threads keyed by chat_key (shareable replay links).
-- Old: chat_key -> [{role, content}]. New: one row per chat_key per user.
-- chat_key is app-generated, not the auth id, so replays can be shared.
-- ============================================================================
create table if not exists public.chats (
    user_id    uuid not null references auth.users(id) on delete cascade,
    chat_key   text not null,
    messages   jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now(),
    primary key (user_id, chat_key)
);

-- ============================================================================
-- replay_comments: comments on a shared replay, keyed by chat_key.
-- ============================================================================
create table if not exists public.replay_comments (
    user_id    uuid not null references auth.users(id) on delete cascade,
    chat_key   text not null,
    turn_idx   integer not null,
    author     text not null,
    text       text not null,
    ts         timestamptz not null default now(),
    primary key (user_id, chat_key, turn_idx)
);

-- ============================================================================
-- Indexes for common lookups.
-- ============================================================================
create index if not exists idx_progress_user on public.progress(user_id);
create index if not exists idx_history_user on public.history(user_id);
create index if not exists idx_chats_user on public.chats(user_id);
create index if not exists idx_replay_user on public.replay_comments(user_id);

-- ============================================================================
-- Row Level Security: users can only read/write their own rows.
-- ============================================================================
alter table public.profiles        enable row level security;
alter table public.progress        enable row level security;
alter table public.history         enable row level security;
alter table public.chats           enable row level security;
alter table public.replay_comments enable row level security;

create policy "own profile"  on public.profiles        for all using (auth.uid() = id) with check (auth.uid() = id);
create policy "own progress" on public.progress        for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own history"  on public.history         for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own chats"    on public.chats           for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own comments" on public.replay_comments for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ============================================================================
-- Auto-create a profile row when a new auth user signs up.
-- ============================================================================
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email, display_name)
    values (new.id, new.email, split_part(coalesce(new.email, 'user'), '@', 1));
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();
