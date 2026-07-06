"""Supabase storage helpers for HCCL Rankings Dashboard v3.

This file is intentionally small and boring:
- It reads Supabase credentials from Streamlit secrets or environment variables.
- It saves the current ranking calculation as a snapshot.
- It loads a saved snapshot so the app can use it as the previous rankings source.

Required secrets / environment variables:
    SUPABASE_URL
    SUPABASE_KEY

Optional:
    HCCL_ADMIN_PASSWORD
"""

from __future__ import annotations

import math
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

try:
    import streamlit as st
except Exception:  # pragma: no cover - useful when running CLI tests
    st = None

from supabase import create_client

from hccl_rating_engine import PreviousEntry, normalize_name


CATEGORY_TO_KIND = {
    "Batting": "batting",
    "Bowling": "bowling",
    "All-Rounder": "all_rounder",
}


def _secret(name: str) -> Optional[str]:
    """Read a value from Streamlit secrets first, then environment variables."""
    if st is not None:
        try:
            value = st.secrets.get(name, None)
            if value:
                return str(value)
        except Exception:
            pass
    value = os.getenv(name)
    return str(value) if value else None


def supabase_is_configured() -> bool:
    return bool(_secret("SUPABASE_URL") and _secret("SUPABASE_KEY"))


def get_admin_password() -> Optional[str]:
    return _secret("HCCL_ADMIN_PASSWORD")


def get_supabase_client():
    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def clean_value(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe values for Supabase."""
    if value is None:
        return None
    try:
        # Handles pandas NA, numpy nan, normal float nan/inf.
        if value != value:
            return None
    except Exception:
        pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (int, str, bool)):
        return value
    # Convert numpy scalars and other simple objects.
    try:
        item = value.item()
        return clean_value(item)
    except Exception:
        pass
    return str(value)


def clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): clean_value(v) for k, v in record.items()}


def chunked(items: List[Dict[str, Any]], size: int = 500) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def save_snapshot(
    *,
    week_label: str,
    snapshot_date: str,
    official_only: bool,
    notes: str,
    batting_rows: List[Dict[str, Any]],
    bowling_rows: List[Dict[str, Any]],
    all_rounder_rows: List[Dict[str, Any]],
    weekly_report_rows: List[Dict[str, Any]],
    team_rows: List[Dict[str, Any]],
    detail_rows: List[Dict[str, Any]],
    benchmarks: Dict[str, Any],
) -> Dict[str, Any]:
    """Save the whole calculated ranking set into Supabase.

    Returns the inserted snapshot row.
    """
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured. Add SUPABASE_URL and SUPABASE_KEY to Streamlit secrets.")

    week_label = str(week_label).strip()
    if not week_label:
        raise ValueError("Week label is required, for example: Week 07 or 2026-07-06.")

    snapshot_payload = clean_record({
        "week_label": week_label,
        "snapshot_date": snapshot_date or str(date.today()),
        "official_only": official_only,
        "notes": notes or "",
    })

    snapshot_response = client.table("hccl_snapshots").insert(snapshot_payload).execute()
    if not snapshot_response.data:
        raise RuntimeError("Supabase did not return the saved snapshot row.")
    snapshot = snapshot_response.data[0]
    snapshot_id = snapshot["id"]

    ranking_records: List[Dict[str, Any]] = []
    for category, rows in [
        ("Batting", batting_rows),
        ("Bowling", bowling_rows),
        ("All-Rounder", all_rounder_rows),
    ]:
        for row in rows:
            ranking_records.append(clean_record({
                "snapshot_id": snapshot_id,
                "category": category,
                "rank": row.get("Rank"),
                "movement": row.get("Movement"),
                "player": row.get("Player"),
                "team": row.get("Team"),
                "rating": row.get("Rating"),
                "previous_rank": row.get("Previous Rank"),
                "previous_rating": row.get("Previous Rating"),
                "rating_change": row.get("Rating Change"),
                "status": row.get("Status"),
            }))

    for batch in chunked(ranking_records):
        if batch:
            client.table("hccl_rankings").insert(batch).execute()

    report_records = [
        clean_record({
            "snapshot_id": snapshot_id,
            "category": row.get("Category"),
            "report_section": row.get("Report Section"),
            "player": row.get("Player"),
            "team": row.get("Team"),
            "current_rank": row.get("Current Rank"),
            "previous_rank": row.get("Previous Rank"),
            "movement": row.get("Movement"),
            "current_rating": row.get("Current Rating"),
            "previous_rating": row.get("Previous Rating"),
            "rating_change": row.get("Rating Change"),
            "status": row.get("Status"),
        })
        for row in weekly_report_rows
    ]
    for batch in chunked(report_records):
        if batch:
            client.table("hccl_weekly_report").insert(batch).execute()

    team_records = [
        clean_record({
            "snapshot_id": snapshot_id,
            "team": row.get("Team"),
            "category": row.get("Category"),
            "team_rank": row.get("Team Rank"),
            "overall_rank": row.get("Overall Rank"),
            "movement": row.get("Movement"),
            "player": row.get("Player"),
            "rating": row.get("Rating"),
            "previous_rating": row.get("Previous Rating"),
            "rating_change": row.get("Rating Change"),
            "status": row.get("Status"),
        })
        for row in team_rows
    ]
    for batch in chunked(team_records):
        if batch:
            client.table("hccl_team_rankings").insert(batch).execute()

    detail_records = [
        clean_record({
            "snapshot_id": snapshot_id,
            "player_id": row.get("player_id"),
            "player": row.get("name"),
            "team": row.get("team"),
            "data": clean_record(row),
        })
        for row in detail_rows
    ]
    for batch in chunked(detail_records):
        if batch:
            client.table("hccl_rating_details").insert(batch).execute()

    benchmark_records = [
        clean_record({
            "snapshot_id": snapshot_id,
            "benchmark_key": key,
            "benchmark_value": value,
        })
        for key, value in benchmarks.items()
    ]
    for batch in chunked(benchmark_records):
        if batch:
            client.table("hccl_benchmarks").insert(batch).execute()

    return snapshot


def list_snapshots(limit: int = 30) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    if client is None:
        return []
    response = (
        client.table("hccl_snapshots")
        .select("id,week_label,snapshot_date,created_at,official_only,notes")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def get_rankings_for_snapshot(snapshot_id: str) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    if client is None:
        return []
    response = (
        client.table("hccl_rankings")
        .select("category,rank,movement,player,team,rating,previous_rank,previous_rating,rating_change,status")
        .eq("snapshot_id", snapshot_id)
        .order("category")
        .order("rank")
        .execute()
    )
    return response.data or []


def previous_dict_from_snapshot(snapshot_id: str) -> Dict[str, Dict[str, PreviousEntry]]:
    """Return rankings from a saved snapshot in the same shape parse_previous_rankings uses."""
    rows = get_rankings_for_snapshot(snapshot_id)
    result: Dict[str, Dict[str, PreviousEntry]] = {
        "batting": {},
        "bowling": {},
        "all_rounder": {},
    }
    for row in rows:
        category = row.get("category")
        kind = CATEGORY_TO_KIND.get(str(category))
        if not kind:
            continue
        player = str(row.get("player") or "").strip()
        rank = int(row.get("rank") or 0)
        rating = float(row.get("rating") or 0)
        if player and rank:
            result[kind][normalize_name(player)] = PreviousEntry(rank=rank, player=player, rating=rating)
    return result


def get_latest_snapshot_id() -> Optional[str]:
    snapshots = list_snapshots(limit=1)
    return snapshots[0]["id"] if snapshots else None
