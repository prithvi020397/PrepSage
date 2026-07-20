-- Per-user persistence tables for The Loop (cloud multi-user mode).
-- Run in the Supabase SQL editor (or `supabase db push`). RLS ensures a user
-- can only read/write their own rows via auth.uid() = user_id.

-- 1) progress: one row per (user, question)
create table if not exists public.progress (
  user_id   uuid not null references auth.users(id) on delete cascade,
  qid       text not null,
  solved_at timestamptz,
  fails     integer default 0,
  due_at    timestamptz,
  code      jsonb,
  trace     jsonb,
  pattern   text,
  skeleton  jsonb,
  concept_map jsonb,
  updated_at timestamptz default now(),
  primary key (user_id, qid)
);
alter table public.progress enable row level security;
drop policy if exists progress_owner on public.progress;
create policy progress_owner on public.progress
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- 2) chats: one row per user (whole-dict jsonb)
create table if not exists public.chats (
  user_id uuid not null references auth.users(id) on delete cascade primary key,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz default now()
);
alter table public.chats enable row level security;
drop policy if exists chats_owner on public.chats;
create policy chats_owner on public.chats
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- 3) judges: one row per user
create table if not exists public.judges (
  user_id uuid not null references auth.users(id) on delete cascade primary key,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz default now()
);
alter table public.judges enable row level security;
drop policy if exists judges_owner on public.judges;
create policy judges_owner on public.judges
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- 4) replay_comments: one row per user
create table if not exists public.replay_comments (
  user_id uuid not null references auth.users(id) on delete cascade primary key,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz default now()
);
alter table public.replay_comments enable row level security;
drop policy if exists replay_comments_owner on public.replay_comments;
create policy replay_comments_owner on public.replay_comments
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
