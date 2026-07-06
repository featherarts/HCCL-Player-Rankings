-- HCCL Rankings Dashboard v3 Supabase schema
-- Run this once in Supabase Dashboard > SQL Editor.

create extension if not exists "pgcrypto";

create table if not exists public.hccl_snapshots (
    id uuid primary key default gen_random_uuid(),
    week_label text not null,
    snapshot_date date not null default current_date,
    official_only boolean not null default false,
    notes text,
    created_at timestamptz not null default now()
);

create table if not exists public.hccl_rankings (
    id bigserial primary key,
    snapshot_id uuid not null references public.hccl_snapshots(id) on delete cascade,
    category text not null check (category in ('Batting', 'Bowling', 'All-Rounder')),
    rank integer not null,
    movement text,
    player text not null,
    team text,
    rating numeric,
    previous_rank integer,
    previous_rating numeric,
    rating_change text,
    status text,
    created_at timestamptz not null default now()
);

create table if not exists public.hccl_weekly_report (
    id bigserial primary key,
    snapshot_id uuid not null references public.hccl_snapshots(id) on delete cascade,
    category text,
    report_section text,
    player text,
    team text,
    current_rank integer,
    previous_rank integer,
    movement text,
    current_rating numeric,
    previous_rating numeric,
    rating_change text,
    status text,
    created_at timestamptz not null default now()
);

create table if not exists public.hccl_team_rankings (
    id bigserial primary key,
    snapshot_id uuid not null references public.hccl_snapshots(id) on delete cascade,
    team text,
    category text,
    team_rank integer,
    overall_rank integer,
    movement text,
    player text,
    rating numeric,
    previous_rating numeric,
    rating_change text,
    status text,
    created_at timestamptz not null default now()
);

create table if not exists public.hccl_rating_details (
    id bigserial primary key,
    snapshot_id uuid not null references public.hccl_snapshots(id) on delete cascade,
    player_id text,
    player text,
    team text,
    data jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.hccl_benchmarks (
    id bigserial primary key,
    snapshot_id uuid not null references public.hccl_snapshots(id) on delete cascade,
    benchmark_key text not null,
    benchmark_value numeric,
    created_at timestamptz not null default now()
);

create index if not exists idx_hccl_rankings_snapshot_category_rank
    on public.hccl_rankings(snapshot_id, category, rank);

create index if not exists idx_hccl_rankings_player
    on public.hccl_rankings(player);

create index if not exists idx_hccl_snapshots_created_at
    on public.hccl_snapshots(created_at desc);

create index if not exists idx_hccl_team_rankings_snapshot_team
    on public.hccl_team_rankings(snapshot_id, team, category, team_rank);
