from __future__ import annotations

import hashlib
import html
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from hccl_rating_engine import (
    calculate_formula_audit,
    calculate_ratings,
    parse_previous_rankings,
    ranking_dicts,
    read_stats_csv,
    team_ranking_dicts,
    weekly_report_rows,
    write_details,
    write_side_by_side_rankings,
    write_team_rankings,
    write_weekly_report,
)
from scorecard_updater import update_stats_csv_from_scorecard
from supabase_storage import (
    get_admin_password,
    get_full_snapshot,
    list_snapshots,
    previous_dict_from_snapshot,
    save_snapshot,
    supabase_is_configured,
)

APP_VERSION = "v5.1"

st.set_page_config(page_title="HCCL Official Rankings Dashboard", page_icon="🏏", layout="wide")

# -----------------------------
# Modern UI skin
# -----------------------------

st.markdown(
    """
    <style>
    :root {
      --hccl-bg: #070910;
      --hccl-card: rgba(255,255,255,0.055);
      --hccl-card-2: rgba(255,255,255,0.080);
      --hccl-line: rgba(255,255,255,0.12);
      --hccl-text-muted: rgba(255,255,255,0.70);
      --hccl-red: #ff3b54;
      --hccl-gold: #ffd166;
      --hccl-green: #35d07f;
      --hccl-blue: #63a4ff;
    }
    html, body, [data-testid="stAppViewContainer"] {
      background:
        radial-gradient(circle at 20% 0%, rgba(255, 59, 84, 0.16), transparent 32%),
        radial-gradient(circle at 78% 6%, rgba(255, 209, 102, 0.10), transparent 24%),
        linear-gradient(180deg, #080b13 0%, #070910 55%, #05070d 100%) !important;
    }
    [data-testid="stSidebar"] {
      background: linear-gradient(180deg, rgba(18,22,34,0.98), rgba(11,13,21,0.98)) !important;
      border-right: 1px solid rgba(255,255,255,0.08);
    }
    .block-container {padding-top: 1.05rem; padding-bottom: 2.5rem; max-width: 1500px;}
    div[data-testid="stVerticalBlock"] {gap: 0.78rem;}
    .hccl-hero {
      position: relative;
      overflow: hidden;
      padding: 30px 34px;
      border-radius: 28px;
      background:
        linear-gradient(135deg, rgba(255, 59, 84, 0.18) 0%, rgba(18, 22, 35, 0.96) 46%, rgba(255, 209, 102, 0.10) 100%),
        linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
      border: 1px solid rgba(255,255,255,0.16);
      box-shadow: 0 20px 65px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.10);
      margin-bottom: 18px;
    }
    .hccl-hero:after {
      content: "";
      position: absolute;
      right: -80px;
      top: -80px;
      width: 320px;
      height: 320px;
      background: radial-gradient(circle, rgba(255,209,102,0.22), transparent 62%);
      transform: rotate(24deg);
    }
    .hccl-pill {
      display: inline-flex;
      gap: 8px;
      align-items: center;
      padding: 7px 13px;
      border-radius: 999px;
      background: rgba(255,59,84,0.16);
      color: #ffc7cf;
      border: 1px solid rgba(255,59,84,0.36);
      font-size: 13px;
      font-weight: 900;
      letter-spacing: 0.02em;
      margin-bottom: 12px;
    }
    .hccl-title {font-size: clamp(34px, 4.2vw, 58px); line-height: 1.02; font-weight: 950; color: #ffffff; margin: 0 0 8px 0;}
    .hccl-subtitle {font-size: 17px; color: rgba(255,255,255,0.82); max-width: 1060px; margin: 0;}
    .snapshot-banner {
      padding: 13px 16px;
      border-radius: 16px;
      background: rgba(99, 164, 255, 0.12);
      border: 1px solid rgba(99, 164, 255, 0.28);
      color: #dceaff;
      font-weight: 750;
      margin-bottom: 16px;
    }
    .update-banner {
      padding: 13px 16px;
      border-radius: 16px;
      background: rgba(255, 209, 102, 0.12);
      border: 1px solid rgba(255, 209, 102, 0.28);
      color: #ffefbc;
      font-weight: 750;
      margin-bottom: 16px;
    }
    .metric-card, .leader-card, .glass-card {
      padding: 18px 18px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255,255,255,0.075), rgba(255,255,255,0.035));
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 14px 36px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.07);
    }
    .metric-label {font-size: 13px; color: rgba(255,255,255,0.68); font-weight: 900; text-transform: uppercase; letter-spacing: 0.04em;}
    .metric-value {font-size: 32px; color: #ffffff; font-weight: 950; margin-top: 8px; line-height: 1;}
    .metric-help {font-size: 13px; color: rgba(255,255,255,0.68); margin-top: 9px;}
    .leader-card {min-height: 168px; position: relative; overflow: hidden;}
    .leader-card:before {content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: linear-gradient(180deg, var(--hccl-gold), var(--hccl-red));}
    .leader-label {font-size: 14px; color: rgba(255,255,255,0.68); font-weight: 900; text-transform: uppercase; letter-spacing: 0.04em;}
    .leader-name {font-size: 28px; color: white; font-weight: 950; margin: 8px 0 8px 0; line-height: 1.08;}
    .leader-team {font-size: 14px; color: rgba(255,255,255,0.68); margin-bottom: 10px;}
    .rating-chip {display:inline-block; padding: 6px 10px; border-radius: 999px; background: rgba(53,208,127,0.18); color:#a8ffd0; border:1px solid rgba(53,208,127,0.34); font-weight:900;}
    .section-title {font-size: 25px; font-weight: 950; color: #fff; margin: 20px 0 10px 0;}
    .section-subtitle {font-size: 14px; color: rgba(255,255,255,0.66); margin-top: -4px; margin-bottom: 10px;}
    .db-ok {color: #77ffae; font-weight: 900;}
    .db-miss {color: #ffcf7a; font-weight: 900;}
    div[data-testid="stDataFrame"] {border-radius: 18px; overflow: hidden; border: 1px solid rgba(255,255,255,0.09);}
    .stTabs [data-baseweb="tab-list"] {gap: 9px; border-bottom: 1px solid rgba(255,255,255,0.12); flex-wrap: wrap;}
    .stTabs [data-baseweb="tab"] {
      height: 42px;
      padding: 10px 14px;
      border-radius: 999px 999px 0 0;
      background: rgba(255,255,255,0.045);
      border: 1px solid rgba(255,255,255,0.08);
      border-bottom: 0;
      font-weight: 850;
    }
    .stTabs [aria-selected="true"] {background: rgba(255,59,84,0.18) !important; color: #fff !important;}
    button[kind="primary"] {border-radius: 999px !important; font-weight: 900 !important;}
    .stDownloadButton button {border-radius: 999px !important; font-weight: 850 !important;}
    @media (max-width: 768px) {
      .hccl-hero {padding: 24px 20px; border-radius: 22px;}
      .hccl-title {font-size: 32px;}
      .hccl-subtitle {font-size: 15px;}
      .leader-name {font-size: 24px;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# UI helpers
# -----------------------------

def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def render_hero(mode_label: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="hccl-hero">
          <div class="hccl-pill">🏏 OFFICIAL HCCL RANKINGS • DASHBOARD {APP_VERSION} • {esc(mode_label)}</div>
          <div class="hccl-title">HCCL Player Rankings Dashboard</div>
          <p class="hccl-subtitle">{esc(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: Any, help_text: str) -> str:
    return f"""
    <div class="metric-card">
      <div class="metric-label">{esc(label)}</div>
      <div class="metric-value">{esc(value)}</div>
      <div class="metric-help">{esc(help_text)}</div>
    </div>
    """


def leader_card(icon: str, title: str, player: Optional[str], team: Optional[str], rating: Optional[Any]) -> str:
    if not player:
        player = "No qualified player"
        team = "-"
        rating = "-"
    return f"""
    <div class="leader-card">
      <div class="leader-label">{esc(icon)} {esc(title)}</div>
      <div class="leader-name">{esc(player)}</div>
      <div class="leader-team">{esc(team or '-')}</div>
      <span class="rating-chip">{esc(rating)} rating</span>
    </div>
    """


def dataframe_from_rows(rows: List[Dict[str, Any]], display_cols: Optional[List[str]] = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if display_cols:
        existing = [c for c in display_cols if c in df.columns]
        df = df[existing]
    return df


def show_ranking_table(rows: List[Dict[str, Any]], key_prefix: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    display_cols = ["Rank", "Movement", "Player", "Team", "Rating", "Previous Rating", "Rating Change", "Status"]
    if df.empty:
        st.info("No rows to show.")
        return df
    df = df[display_cols]
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn("Rank", width="small"),
            "Movement": st.column_config.TextColumn("Move", width="small"),
            "Rating": st.column_config.NumberColumn("Rating", width="small"),
            "Previous Rating": st.column_config.NumberColumn("Previous", width="small"),
            "Rating Change": st.column_config.TextColumn("Change", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
        },
        key=key_prefix,
    )
    return df


def normalize_saved_rankings(rows: List[Dict[str, Any]], category: str, official_only: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        if str(r.get("category")) != category:
            continue
        if official_only and str(r.get("status") or "").lower() != "official":
            continue
        out.append({
            "Rank": r.get("rank"),
            "Movement": r.get("movement") or "",
            "Player": r.get("player"),
            "Team": r.get("team"),
            "Rating": r.get("rating"),
            "Previous Rank": r.get("previous_rank"),
            "Previous Rating": r.get("previous_rating"),
            "Rating Change": r.get("rating_change"),
            "Status": r.get("status"),
        })
    return sorted(out, key=lambda x: int(x.get("Rank") or 9999))


def normalize_saved_report(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "Report Section": r.get("report_section"),
            "Category": r.get("category"),
            "Player": r.get("player"),
            "Team": r.get("team"),
            "Current Rank": r.get("current_rank"),
            "Previous Rank": r.get("previous_rank"),
            "Movement": r.get("movement"),
            "Current Rating": r.get("current_rating"),
            "Previous Rating": r.get("previous_rating"),
            "Rating Change": r.get("rating_change"),
            "Status": r.get("status"),
        }
        for r in rows
    ]


def normalize_saved_team(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "Team": r.get("team"),
            "Category": r.get("category"),
            "Team Rank": r.get("team_rank"),
            "Overall Rank": r.get("overall_rank"),
            "Movement": r.get("movement"),
            "Player": r.get("player"),
            "Rating": r.get("rating"),
            "Previous Rating": r.get("previous_rating"),
            "Rating Change": r.get("rating_change"),
            "Status": r.get("status"),
        }
        for r in rows
    ]


def normalize_saved_details(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    details = []
    for r in rows:
        base = {"Player ID": r.get("player_id"), "Player": r.get("player"), "Team": r.get("team")}
        data = r.get("data") or {}
        if isinstance(data, dict):
            for k, v in data.items():
                if k not in base:
                    base[str(k)] = v
        details.append(base)
    return details


def normalize_saved_benchmarks(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Benchmark": r.get("benchmark_key"), "Value": r.get("benchmark_value")}
        for r in rows
    ])


def render_saved_snapshot_dashboard(snapshot_data: Dict[str, Any], official_only: bool) -> None:
    snapshot = snapshot_data.get("snapshot") or {}
    rankings_raw = snapshot_data.get("rankings") or []
    report_rows = normalize_saved_report(snapshot_data.get("weekly_report") or [])
    team_rows = normalize_saved_team(snapshot_data.get("team_rankings") or [])
    detail_rows = normalize_saved_details(snapshot_data.get("rating_details") or [])
    benchmark_df = normalize_saved_benchmarks(snapshot_data.get("benchmarks") or [])

    batting_rows = normalize_saved_rankings(rankings_raw, "Batting", official_only)
    bowling_rows = normalize_saved_rankings(rankings_raw, "Bowling", official_only)
    ar_rows = normalize_saved_rankings(rankings_raw, "All-Rounder", official_only)

    render_hero(
        "LIVE SAVED SNAPSHOT",
        "Your latest saved Supabase rankings are shown automatically. Upload a new stats CSV from the sidebar when you want to calculate the next ranking update.",
    )

    st.markdown(
        f"""
        <div class="snapshot-banner">
        🔄 Showing saved rankings: <b>{esc(snapshot.get('week_label') or 'Latest Snapshot')}</b> • {esc(snapshot.get('snapshot_date') or '')}
        &nbsp;|&nbsp; Saved: {esc(str(snapshot.get('created_at') or '')[:19])}
        </div>
        """,
        unsafe_allow_html=True,
    )

    official_bat = sum(1 for r in batting_rows if str(r.get("Status")) == "Official")
    official_bowl = sum(1 for r in bowling_rows if str(r.get("Status")) == "Official")
    official_ar = sum(1 for r in ar_rows if str(r.get("Status")) == "Official")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card("Players in Snapshot", len(detail_rows), "From last saved Supabase ranking"), unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Official Batters", official_bat, "10 innings + 100 runs"), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("Official Bowlers", official_bowl, "10 wickets minimum"), unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("Official All-Rounders", official_ar, "100 runs + 10 wickets"), unsafe_allow_html=True)

    st.markdown("<div class='section-title'>🏆 Current Ranking Leaders</div>", unsafe_allow_html=True)
    l1, l2, l3 = st.columns(3)
    top_bat = batting_rows[0] if batting_rows else {}
    top_bowl = bowling_rows[0] if bowling_rows else {}
    top_ar = ar_rows[0] if ar_rows else {}
    with l1:
        st.markdown(leader_card("🏏", "Batting #1", top_bat.get("Player"), top_bat.get("Team"), top_bat.get("Rating")), unsafe_allow_html=True)
    with l2:
        st.markdown(leader_card("🎯", "Bowling #1", top_bowl.get("Player"), top_bowl.get("Team"), top_bowl.get("Rating")), unsafe_allow_html=True)
    with l3:
        st.markdown(leader_card("👑", "All-Rounder #1", top_ar.get("Player"), top_ar.get("Team"), top_ar.get("Rating")), unsafe_allow_html=True)

    tabs = st.tabs(["🏏 Batting", "🎯 Bowling", "👑 All-Rounder", "📈 Weekly Report", "🛡️ Team Rankings", "🔎 Player Details", "⚙️ Benchmarks", "💾 Saved Snapshots"])
    with tabs[0]:
        st.markdown("<div class='section-title'>HCCL Batting Rankings</div>", unsafe_allow_html=True)
        show_ranking_table(batting_rows, "saved_batting")
    with tabs[1]:
        st.markdown("<div class='section-title'>HCCL Bowling Rankings</div>", unsafe_allow_html=True)
        show_ranking_table(bowling_rows, "saved_bowling")
    with tabs[2]:
        st.markdown("<div class='section-title'>HCCL All-Rounder Rankings</div>", unsafe_allow_html=True)
        show_ranking_table(ar_rows, "saved_ar")
    with tabs[3]:
        st.markdown("<div class='section-title'>Weekly Ranking Report</div>", unsafe_allow_html=True)
        report_df = pd.DataFrame(report_rows)
        if report_df.empty:
            st.info("No weekly report saved for this snapshot.")
        else:
            for section in ["Top Climbers", "Top Fallers", "Top Rating Gains", "New Entries"]:
                st.markdown(f"### {section}")
                sdf = report_df[report_df["Report Section"] == section]
                if sdf.empty:
                    st.caption("No players in this section.")
                else:
                    st.dataframe(sdf, use_container_width=True, hide_index=True)
    with tabs[4]:
        st.markdown("<div class='section-title'>Team-wise Player Rankings</div>", unsafe_allow_html=True)
        team_df = pd.DataFrame(team_rows)
        teams = sorted(team_df["Team"].dropna().unique().tolist()) if not team_df.empty else []
        categories = ["Batting", "Bowling", "All-Rounder"]
        a, b = st.columns(2)
        selected_team = a.selectbox("Select team", options=["All Teams"] + teams, key="saved_team_filter")
        selected_category = b.selectbox("Select category", options=["All Categories"] + categories, key="saved_category_filter")
        filtered = team_df.copy()
        if not filtered.empty and selected_team != "All Teams":
            filtered = filtered[filtered["Team"] == selected_team]
        if not filtered.empty and selected_category != "All Categories":
            filtered = filtered[filtered["Category"] == selected_category]
        st.dataframe(filtered, use_container_width=True, hide_index=True)
    with tabs[5]:
        st.markdown("<div class='section-title'>Player Details</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
    with tabs[6]:
        st.markdown("<div class='section-title'>Current Benchmarks</div>", unsafe_allow_html=True)
        st.dataframe(benchmark_df, use_container_width=True, hide_index=True)
    with tabs[7]:
        st.markdown("<div class='section-title'>Saved Snapshots</div>", unsafe_allow_html=True)
        try:
            snapshots = list_snapshots(limit=30)
            st.dataframe(pd.DataFrame(snapshots), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Could not load saved snapshots: {exc}")

    st.markdown("<div class='section-title'>⬇️ Downloads</div>", unsafe_allow_html=True)
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.download_button("Download rankings CSV", data=pd.DataFrame(batting_rows + bowling_rows + ar_rows).to_csv(index=False).encode(), file_name="HCCL_Rankings_Saved_Snapshot.csv", mime="text/csv")
    with d2:
        st.download_button("Download weekly report CSV", data=pd.DataFrame(report_rows).to_csv(index=False).encode(), file_name="HCCL_Weekly_Report_Saved.csv", mime="text/csv")
    with d3:
        st.download_button("Download team rankings CSV", data=pd.DataFrame(team_rows).to_csv(index=False).encode(), file_name="HCCL_Team_Rankings_Saved.csv", mime="text/csv")
    with d4:
        st.download_button("Download player details CSV", data=pd.DataFrame(detail_rows).to_csv(index=False).encode(), file_name="HCCL_Player_Details_Saved.csv", mime="text/csv")

# -----------------------------
# Sidebar controls
# -----------------------------

with st.sidebar:
    st.markdown("### 🏏 HCCL Control Room")
    db_ready = supabase_is_configured()

    st.markdown("---")
    st.subheader("Live View")
    saved_snapshots_for_live: List[Dict[str, Any]] = []
    live_snapshot_id: Optional[str] = None
    if db_ready:
        try:
            saved_snapshots_for_live = list_snapshots(limit=30)
        except Exception as exc:
            st.error(f"Could not load saved snapshots: {exc}")
            saved_snapshots_for_live = []
        if saved_snapshots_for_live:
            labels = [f"{s.get('week_label')} • {s.get('snapshot_date')} • {str(s.get('created_at',''))[:19]}" for s in saved_snapshots_for_live]
            live_label = st.selectbox("Saved ranking to display", labels, index=0, help="This is shown automatically before you upload a new weekly stats CSV.")
            live_snapshot_id = saved_snapshots_for_live[labels.index(live_label)]["id"]
        else:
            st.caption("No saved Supabase rankings yet.")
    else:
        st.caption("Configure Supabase to show saved rankings automatically.")

    st.markdown("---")
    st.subheader("Weekly Update")
    uploaded_file = st.file_uploader("Upload latest HCCL Stats CSV", type=["csv"])

    if uploaded_file is not None:
        upload_signature = f"{uploaded_file.name}:{uploaded_file.size}"
        if st.session_state.get("uploaded_stats_signature") != upload_signature:
            st.session_state["uploaded_stats_signature"] = upload_signature
            st.session_state["active_stats_csv_bytes"] = uploaded_file.getvalue()
            st.session_state["active_stats_source"] = uploaded_file.name

    if st.session_state.get("active_stats_source"):
        st.caption(f"Active stats source: {st.session_state['active_stats_source']}")
        if st.button("Reset to uploaded CSV") and uploaded_file is not None:
            st.session_state["active_stats_csv_bytes"] = uploaded_file.getvalue()
            st.session_state["active_stats_source"] = uploaded_file.name
            st.rerun()

    st.markdown("---")
    st.subheader("Previous Rankings")
    previous_options = ["No previous rankings", "Upload previous CSV"]
    if db_ready:
        previous_options.insert(0, "Use saved Supabase snapshot")

    default_previous_index = 0
    previous_source = st.radio("Comparison source", previous_options, index=default_previous_index)
    previous_file = None
    selected_snapshot_id = None

    saved_snapshots = []
    if previous_source == "Upload previous CSV":
        previous_file = st.file_uploader("Upload previous rankings CSV", type=["csv"])
    elif previous_source == "Use saved Supabase snapshot":
        saved_snapshots = saved_snapshots_for_live
        if saved_snapshots:
            snapshot_labels = [
                f"{s.get('week_label')} • {s.get('snapshot_date')} • {str(s.get('created_at', ''))[:19]}"
                for s in saved_snapshots
            ]
            selected_label = st.selectbox("Previous saved ranking", snapshot_labels, index=0)
            selected_snapshot_id = saved_snapshots[snapshot_labels.index(selected_label)]["id"]
        else:
            st.info("No saved snapshots yet. Calculate and save one first.")

    official_only = st.checkbox("Show official qualified players only", value=False)

    st.markdown("---")
    st.subheader("Database")
    if db_ready:
        st.markdown("<span class='db-ok'>● Connected</span>", unsafe_allow_html=True)
        st.caption("Supabase save/load is enabled.")
    else:
        st.markdown("<span class='db-miss'>● Not configured</span>", unsafe_allow_html=True)
        st.caption("Add SUPABASE_URL and SUPABASE_KEY in Streamlit secrets.")

# -----------------------------
# Mode 1: no CSV uploaded -> show last saved Supabase rankings
# -----------------------------

active_stats_csv_bytes = st.session_state.get("active_stats_csv_bytes")
if active_stats_csv_bytes is None and uploaded_file is not None:
    active_stats_csv_bytes = uploaded_file.getvalue()
    st.session_state["active_stats_csv_bytes"] = active_stats_csv_bytes
    st.session_state["active_stats_source"] = uploaded_file.name

if active_stats_csv_bytes is None:
    if db_ready and live_snapshot_id:
        try:
            snapshot_data = get_full_snapshot(live_snapshot_id)
            render_saved_snapshot_dashboard(snapshot_data, official_only=official_only)
        except Exception as exc:
            render_hero("SETUP NEEDED", "Supabase is configured, but the saved snapshot could not be loaded.")
            st.error(f"Could not load saved rankings from Supabase: {exc}")
            st.info("Upload your latest HCCL Stats CSV from the left sidebar to calculate rankings manually.")
    else:
        render_hero("READY", "Upload a weekly stats CSV to calculate rankings. Once you save a snapshot to Supabase, this page will open directly with the latest saved rankings.")
        st.info("Upload your latest `HCCL Stats.csv` file from the left sidebar to begin.")
    st.stop()

# -----------------------------
# Mode 2: uploaded stats CSV -> calculate rankings/update workflow
# -----------------------------

render_hero(
    "UPDATE MODE",
    "A stats CSV is loaded. Calculate updated rankings, compare against the last saved snapshot, update stats from scorecard PDFs, and save the new official snapshot.",
)
st.markdown(
    f"""
    <div class="update-banner">
    🧾 Update mode active • Stats source: <b>{esc(st.session_state.get('active_stats_source') or 'Uploaded CSV')}</b>
    </div>
    """,
    unsafe_allow_html=True,
)

with tempfile.TemporaryDirectory() as tmpdir:
    tmpdir_path = Path(tmpdir)
    stats_path = tmpdir_path / "HCCL Stats.csv"
    stats_path.write_bytes(active_stats_csv_bytes)

    previous = None
    previous_loaded = False
    previous_label = "None"

    if previous_source == "Upload previous CSV" and previous_file is not None:
        previous_path = tmpdir_path / "Previous Rankings.csv"
        previous_path.write_bytes(previous_file.getvalue())
        previous = parse_previous_rankings(previous_path)
        previous_loaded = True
        previous_label = previous_file.name
    elif previous_source == "Use saved Supabase snapshot" and selected_snapshot_id:
        try:
            previous = previous_dict_from_snapshot(selected_snapshot_id)
            previous_loaded = True
            previous_label = "Latest saved Supabase snapshot"
        except Exception as exc:
            st.error(f"Could not load previous rankings from Supabase: {exc}")
            previous = None
            previous_loaded = False

    players = read_stats_csv(stats_path)
    ratings, benchmarks = calculate_ratings(players)

    batting_rows = ranking_dicts(ratings, "batting", official_only=official_only, previous=previous)
    bowling_rows = ranking_dicts(ratings, "bowling", official_only=official_only, previous=previous)
    ar_rows = ranking_dicts(ratings, "all_rounder", official_only=official_only, previous=previous)

    top_bat = batting_rows[0] if batting_rows else None
    top_bowl = bowling_rows[0] if bowling_rows else None
    top_ar = ar_rows[0] if ar_rows else None

    official_bat = sum(1 for r in ratings if r.batting_qualified and r.batting_rating is not None)
    official_bowl = sum(1 for r in ratings if r.bowling_qualified and r.bowling_rating is not None)
    official_ar = sum(1 for r in ratings if r.all_rounder_qualified and r.all_rounder_rating is not None)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card("Players Loaded", len(players), "From active stats CSV"), unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Official Batters", official_bat, "10 innings + 100 runs"), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("Official Bowlers", official_bowl, "10 wickets minimum"), unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("Official All-Rounders", official_ar, "100 runs + 10 wickets"), unsafe_allow_html=True)

    st.markdown("<div class='section-title'>🏆 Ranking Leaders</div>", unsafe_allow_html=True)
    l1, l2, l3 = st.columns(3)
    with l1:
        st.markdown(leader_card("🏏", "Batting #1", top_bat.get("Player") if top_bat else None, top_bat.get("Team") if top_bat else None, top_bat.get("Rating") if top_bat else None), unsafe_allow_html=True)
    with l2:
        st.markdown(leader_card("🎯", "Bowling #1", top_bowl.get("Player") if top_bowl else None, top_bowl.get("Team") if top_bowl else None, top_bowl.get("Rating") if top_bowl else None), unsafe_allow_html=True)
    with l3:
        st.markdown(leader_card("👑", "All-Rounder #1", top_ar.get("Player") if top_ar else None, top_ar.get("Team") if top_ar else None, top_ar.get("Rating") if top_ar else None), unsafe_allow_html=True)

    if previous_loaded:
        st.success(f"Previous rankings loaded from: {previous_label}")
    else:
        st.warning("Movement, previous rating, and weekly climber/faller report need previous rankings. Choose a saved Supabase snapshot or upload a previous CSV.")

    report_rows = weekly_report_rows(ratings, previous, official_only=official_only) if previous else []
    team_rows = []
    for kind in ["batting", "bowling", "all_rounder"]:
        team_rows.extend(team_ranking_dicts(ratings, kind, official_only=official_only, previous=previous))
    detail_rows = [r.__dict__ for r in ratings]

    tabs = st.tabs([
        "🏏 Batting",
        "🎯 Bowling",
        "👑 All-Rounder",
        "📈 Weekly Report",
        "🛡️ Team Rankings",
        "🔎 Player Details",
        "⚙️ Benchmarks",
        "🧮 Formula Audit",
        "🧾 Scorecard Update",
        "💾 Save / Load",
    ])

    with tabs[0]:
        st.markdown("<div class='section-title'>HCCL Batting Rankings</div>", unsafe_allow_html=True)
        show_ranking_table(batting_rows, "batting_table")

    with tabs[1]:
        st.markdown("<div class='section-title'>HCCL Bowling Rankings</div>", unsafe_allow_html=True)
        show_ranking_table(bowling_rows, "bowling_table")

    with tabs[2]:
        st.markdown("<div class='section-title'>HCCL All-Rounder Rankings</div>", unsafe_allow_html=True)
        show_ranking_table(ar_rows, "ar_table")

    with tabs[3]:
        st.markdown("<div class='section-title'>Weekly Ranking Report</div>", unsafe_allow_html=True)
        if not previous:
            st.info("Choose a saved snapshot or upload previous rankings CSV to see top climbers, fallers, rating gains, and new entries.")
        else:
            report_df = pd.DataFrame(report_rows)
            for section in ["Top Climbers", "Top Fallers", "Top Rating Gains", "New Entries"]:
                st.markdown(f"### {section}")
                section_df = report_df[report_df["Report Section"] == section] if not report_df.empty else pd.DataFrame()
                if section_df.empty:
                    st.caption("No players in this section.")
                else:
                    st.dataframe(section_df, use_container_width=True, hide_index=True)

    with tabs[4]:
        st.markdown("<div class='section-title'>Team-wise Player Rankings</div>", unsafe_allow_html=True)
        team_df = pd.DataFrame(team_rows)
        teams = sorted(team_df["Team"].dropna().unique().tolist()) if not team_df.empty else []
        categories = ["Batting", "Bowling", "All-Rounder"]
        a, b = st.columns(2)
        selected_team = a.selectbox("Select team", options=["All Teams"] + teams)
        selected_category = b.selectbox("Select category", options=["All Categories"] + categories)
        filtered = team_df.copy()
        if not filtered.empty and selected_team != "All Teams":
            filtered = filtered[filtered["Team"] == selected_team]
        if not filtered.empty and selected_category != "All Categories":
            filtered = filtered[filtered["Category"] == selected_category]
        st.dataframe(filtered, use_container_width=True, hide_index=True)

    with tabs[5]:
        st.markdown("<div class='section-title'>Player Rating Details</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    with tabs[6]:
        st.markdown("<div class='section-title'>Current Benchmarks</div>", unsafe_allow_html=True)
        benchmark_df = pd.DataFrame([benchmarks]).T.reset_index()
        benchmark_df.columns = ["Benchmark", "Value"]
        st.dataframe(benchmark_df, use_container_width=True, hide_index=True)

    with tabs[7]:
        st.markdown("<div class='section-title'>Formula Audit / Player Calculation Check</div>", unsafe_allow_html=True)
        st.caption("Select a player to see exactly how batting, bowling, and all-rounder ratings are calculated from the uploaded stats CSV.")
        player_names = sorted([str(p.get("NAME", "")).strip() for p in players if str(p.get("NAME", "")).strip()])
        selected_audit_player = st.selectbox("Select player", player_names, key="formula_audit_player")
        if selected_audit_player:
            try:
                audit = calculate_formula_audit(players, selected_audit_player)
                rating_summary = audit["ratings"]
                a1, a2, a3 = st.columns(3)
                with a1:
                    st.metric("Batting Rating", rating_summary.get("Batting Rating", ""))
                with a2:
                    st.metric("Bowling Rating", rating_summary.get("Bowling Rating", ""))
                with a3:
                    st.metric("All-Rounder Rating", rating_summary.get("All-Rounder Rating", ""))
                st.markdown("### Player raw stats used")
                st.dataframe(pd.DataFrame([audit["player"]]), use_container_width=True, hide_index=True)
                st.markdown("### Current benchmarks used")
                benchmark_audit_df = pd.DataFrame([audit["benchmarks"]]).T.reset_index()
                benchmark_audit_df.columns = ["Benchmark", "Value"]
                st.dataframe(benchmark_audit_df, use_container_width=True, hide_index=True)
                st.markdown("### Batting rating calculation")
                st.dataframe(pd.DataFrame(audit["batting_steps"]), use_container_width=True, hide_index=True)
                with st.expander("Show batting recent 5 match point breakdown"):
                    st.dataframe(pd.DataFrame(audit["batting_recent_rows"]), use_container_width=True, hide_index=True)
                st.markdown("### Bowling rating calculation")
                st.dataframe(pd.DataFrame(audit["bowling_steps"]), use_container_width=True, hide_index=True)
                with st.expander("Show bowling recent 5 match point breakdown"):
                    st.dataframe(pd.DataFrame(audit["bowling_recent_rows"]), use_container_width=True, hide_index=True)
                st.markdown("### All-rounder calculation")
                st.dataframe(pd.DataFrame(audit["all_rounder_steps"]), use_container_width=True, hide_index=True)
                st.info("This audit uses the same calculation functions as the ranking tables, so the final rounded ratings should match the dashboard rankings.")
            except Exception as exc:
                st.error(f"Could not calculate formula audit: {exc}")

    with tabs[8]:
        st.markdown("<div class='section-title'>Update HCCL Stats CSV from Scorecard PDF</div>", unsafe_allow_html=True)
        st.caption("Upload one STUMPS match scorecard PDF. The app will update career totals and recent 5 form, then give you a new HCCL Stats CSV to download.")
        st.markdown("""
        **Your CSV can use the `Stumps Name` column.**  
        Put the exact name used in the STUMPS scorecard PDF there. If a scorecard player is not found, the app will safely add him as a new player row.
        """)
        scorecard_pdf = st.file_uploader("Upload match scorecard PDF", type=["pdf"], key="scorecard_pdf_upload")
        if scorecard_pdf is None:
            st.info("Upload a match scorecard PDF here to preview the stats update.")
        else:
            try:
                update_result = update_stats_csv_from_scorecard(active_stats_csv_bytes, scorecard_pdf.getvalue())
                summary = update_result["summary"]
                st.success("Scorecard parsed and stats CSV update prepared. Please review the tables before using the downloaded CSV.")
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("Match ID", summary.get("match_id") or "-")
                c2.metric("POTM", summary.get("player_of_match") or "-")
                c3.metric("Batting rows", summary.get("batting_rows_found", 0))
                c4.metric("Bowling rows", summary.get("bowling_rows_found", 0))
                c5.metric("Existing updated", summary.get("existing_players_updated", 0))
                c6.metric("New players", summary.get("new_players_added", 0))
                trace_df = pd.DataFrame(update_result.get("match_trace", []))
                st.markdown("### Player matching + update trace")
                if trace_df.empty:
                    st.warning("No scorecard player rows were matched or added. The PDF table was probably not parsed correctly.")
                else:
                    st.dataframe(trace_df.drop_duplicates(), use_container_width=True, hide_index=True)
                st.markdown("### Parsed batting updates")
                bat_df = pd.DataFrame(update_result["batting_updates"])
                st.dataframe(bat_df, use_container_width=True, hide_index=True) if not bat_df.empty else st.warning("No batting rows were updated.")
                st.markdown("### Parsed bowling updates")
                bowl_df = pd.DataFrame(update_result["bowling_updates"])
                st.dataframe(bowl_df, use_container_width=True, hide_index=True) if not bowl_df.empty else st.warning("No bowling rows were updated.")
                new_players_df = pd.DataFrame(update_result.get("new_players", []))
                if not new_players_df.empty:
                    st.markdown("### New players automatically added")
                    st.info("These players were found in the scorecard but not in your stats CSV, so the app added them to the downloaded updated CSV.")
                    st.dataframe(new_players_df, use_container_width=True, hide_index=True)
                unmatched_df = pd.DataFrame(update_result["unmatched"])
                if not unmatched_df.empty:
                    st.markdown("### Names that still need manual review")
                    st.error("These rows could not be processed automatically. Check the scorecard PDF text or fix the player/team name manually in the downloaded CSV.")
                    st.dataframe(unmatched_df, use_container_width=True, hide_index=True)
                elif new_players_df.empty:
                    st.success("All parsed scorecard names were matched to existing players.")
                else:
                    st.success("All parsed scorecard names were either matched or added as new players.")
                changed_players_df = pd.DataFrame(update_result.get("changed_players", []))
                st.markdown("### ✅ Stats changed in downloaded CSV")
                if changed_players_df.empty:
                    st.error("No player stat values changed. Do not use the downloaded CSV until this table shows changed players.")
                else:
                    st.success(f"{len(changed_players_df)} player rows changed in the generated CSV below.")
                    st.dataframe(changed_players_df, use_container_width=True, hide_index=True)
                csv_hash = hashlib.md5(update_result["updated_csv_bytes"]).hexdigest()[:8]
                match_id = str(summary.get("match_id") or "scorecard").replace("/", "-").replace(" ", "-")
                st.download_button(
                    "Download updated HCCL Stats CSV",
                    data=update_result["updated_csv_bytes"],
                    file_name=f"HCCL Stats Updated - {match_id} - {csv_hash}.csv",
                    mime="text/csv",
                    type="primary",
                    key=f"download_updated_stats_{csv_hash}",
                    disabled=changed_players_df.empty,
                )
                if st.button("✅ Apply updated stats to rankings now", type="primary", disabled=changed_players_df.empty):
                    st.session_state["active_stats_csv_bytes"] = update_result["updated_csv_bytes"]
                    label = summary.get("match_id") or "scorecard update"
                    st.session_state["active_stats_source"] = f"Updated from scorecard ({label})"
                    st.success("Updated stats applied. Refreshing rankings now...")
                    st.rerun()
                st.info("You can either click 'Apply updated stats to rankings now' or download the updated CSV and upload it later. The original uploaded file is not overwritten.")
            except Exception as exc:
                st.error(f"Could not update stats from scorecard PDF: {exc}")
                st.caption("This feature currently expects the STUMPS scorecard PDF format with 1st/2nd Innings Scorecard tables.")

    with tabs[9]:
        st.markdown("<div class='section-title'>Save Current Rankings to Supabase</div>", unsafe_allow_html=True)
        if not db_ready:
            st.error("Supabase is not configured yet. Add SUPABASE_URL and SUPABASE_KEY in Streamlit secrets, then restart/redeploy the app.")
        else:
            st.caption("Save one snapshot after you verify the weekly rankings. The dashboard will open with this saved snapshot next time.")
            week_label = st.text_input("Week label", value=f"Week {date.today().isoformat()}")
            snapshot_date = st.date_input("Snapshot date", value=date.today())
            notes = st.text_area("Notes", placeholder="Example: Rankings after Match 48 / Week 7 update")
            configured_password = get_admin_password()
            password_ok = True
            if configured_password:
                entered_password = st.text_input("Admin password", type="password")
                password_ok = entered_password == configured_password
            else:
                st.warning("No HCCL_ADMIN_PASSWORD is set. Anyone who can access this app can save snapshots.")
            if st.button("💾 Save Current Rankings", type="primary", disabled=bool(configured_password and not password_ok)):
                try:
                    snapshot = save_snapshot(
                        week_label=week_label,
                        snapshot_date=str(snapshot_date),
                        official_only=official_only,
                        notes=notes,
                        batting_rows=batting_rows,
                        bowling_rows=bowling_rows,
                        all_rounder_rows=ar_rows,
                        weekly_report_rows=report_rows,
                        team_rows=team_rows,
                        detail_rows=detail_rows,
                        benchmarks=benchmarks,
                    )
                    st.success(f"Saved ranking snapshot: {snapshot.get('week_label')} ({snapshot.get('id')})")
                    st.info("Next time you open this dashboard, the saved rankings can be shown automatically before uploading a new CSV.")
                except Exception as exc:
                    st.error(f"Could not save to Supabase: {exc}")
            st.markdown("### Saved Snapshots")
            try:
                snapshots = list_snapshots(limit=20)
                st.dataframe(pd.DataFrame(snapshots), use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"Could not load saved snapshots: {exc}")

    rankings_output = tmpdir_path / "HCCL_Rankings_Updated.csv"
    details_output = tmpdir_path / "HCCL_Rating_Details.csv"
    report_output = tmpdir_path / "HCCL_Weekly_Report.csv"
    team_output = tmpdir_path / "HCCL_Team_Rankings.csv"
    write_side_by_side_rankings(ratings, rankings_output, official_only=official_only, previous=previous)
    write_details(ratings, details_output)
    write_weekly_report(report_rows, report_output)
    write_team_rankings(team_rows, team_output)

    st.markdown("<div class='section-title'>⬇️ Downloads</div>", unsafe_allow_html=True)
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Download rankings CSV", data=rankings_output.read_bytes(), file_name="HCCL_Rankings_Updated.csv", mime="text/csv")
    d2.download_button("Download weekly report CSV", data=report_output.read_bytes(), file_name="HCCL_Weekly_Report.csv", mime="text/csv")
    d3.download_button("Download team rankings CSV", data=team_output.read_bytes(), file_name="HCCL_Team_Rankings.csv", mime="text/csv")
    d4.download_button("Download player details CSV", data=details_output.read_bytes(), file_name="HCCL_Rating_Details.csv", mime="text/csv")
