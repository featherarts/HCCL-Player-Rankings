import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from hccl_rating_engine import (
    calculate_ratings,
    parse_previous_rankings,
    read_stats_csv,
    ranking_dicts,
    team_ranking_dicts,
    weekly_report_rows,
    write_details,
    write_side_by_side_rankings,
    write_team_rankings,
    write_weekly_report,
)

st.set_page_config(page_title="HCCL Official Rankings Dashboard", page_icon="🏏", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
    .hccl-hero {
        padding: 28px 32px;
        border-radius: 22px;
        background: linear-gradient(135deg, #171923 0%, #2b1117 46%, #121212 100%);
        border: 1px solid rgba(255,255,255,0.12);
        box-shadow: 0 10px 30px rgba(0,0,0,0.35);
        margin-bottom: 22px;
    }
    .hccl-title {font-size: 42px; font-weight: 900; color: #ffffff; margin-bottom: 2px;}
    .hccl-subtitle {font-size: 17px; color: #e8e8e8; margin-top: 8px;}
    .hccl-pill {
        display: inline-block; padding: 6px 12px; border-radius: 999px;
        background: rgba(255, 59, 48, 0.18); color: #ffb3ad;
        border: 1px solid rgba(255, 59, 48, 0.38); font-weight: 700; margin-bottom: 10px;
    }
    .metric-card {
        padding: 18px 18px;
        border-radius: 16px;
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.10);
        min-height: 112px;
    }
    .metric-label {font-size: 14px; color: #b9b9b9; font-weight: 700;}
    .metric-value {font-size: 30px; color: #ffffff; font-weight: 900; margin-top: 8px;}
    .metric-help {font-size: 13px; color: #cfcfcf; margin-top: 4px;}
    .section-title {font-size: 24px; font-weight: 900; margin-top: 12px; margin-bottom: 8px;}
    .small-note {font-size: 14px; opacity: 0.85;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hccl-hero">
        <div class="hccl-pill">OFFICIAL HCCL RANKINGS</div>
        <div class="hccl-title">HCCL Player Rankings Dashboard</div>
        <div class="hccl-subtitle">
            Upload the weekly stats CSV and, optionally, last week's rankings CSV to calculate rankings, movement, team tables, and the weekly report.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Weekly Update")
    uploaded_file = st.file_uploader("1) Upload latest HCCL Stats CSV", type=["csv"])
    previous_file = st.file_uploader("2) Upload previous rankings CSV for movement", type=["csv"])
    official_only = st.checkbox("Show official qualified players only", value=False)
    st.markdown("---")
    st.caption("Tip: for movement, upload last week's `HCCL_Rankings_Updated.csv` or your old `HCCL RANKINGS.csv`.")

if uploaded_file is None:
    st.info("Upload your latest `HCCL Stats.csv` file from the left sidebar to begin.")
    st.stop()

with tempfile.TemporaryDirectory() as tmpdir:
    tmpdir_path = Path(tmpdir)
    stats_path = tmpdir_path / "HCCL Stats.csv"
    stats_path.write_bytes(uploaded_file.getvalue())

    previous = None
    previous_loaded = False
    if previous_file is not None:
        previous_path = tmpdir_path / "Previous Rankings.csv"
        previous_path.write_bytes(previous_file.getvalue())
        previous = parse_previous_rankings(previous_path)
        previous_loaded = True

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
        st.markdown(f"""<div class="metric-card"><div class="metric-label">Players Loaded</div><div class="metric-value">{len(players)}</div><div class="metric-help">From latest stats CSV</div></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card"><div class="metric-label">Official Batters</div><div class="metric-value">{official_bat}</div><div class="metric-help">10 innings + 100 runs</div></div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="metric-card"><div class="metric-label">Official Bowlers</div><div class="metric-value">{official_bowl}</div><div class="metric-help">10 wickets minimum</div></div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="metric-card"><div class="metric-label">Official All-Rounders</div><div class="metric-value">{official_ar}</div><div class="metric-help">100 runs + 10 wickets</div></div>""", unsafe_allow_html=True)

    st.markdown("<div class='section-title'>🏆 Ranking Leaders</div>", unsafe_allow_html=True)
    l1, l2, l3 = st.columns(3)
    with l1:
        if top_bat:
            st.metric("Batting #1", top_bat["Player"], f'{top_bat["Rating"]} rating')
    with l2:
        if top_bowl:
            st.metric("Bowling #1", top_bowl["Player"], f'{top_bowl["Rating"]} rating')
    with l3:
        if top_ar:
            st.metric("All-Rounder #1", top_ar["Player"], f'{top_ar["Rating"]} rating')

    if not previous_loaded:
        st.warning("Movement, previous rating, and weekly climber/faller report need a previous rankings CSV. Upload it in the sidebar to activate those features.")

    def show_ranking_table(rows, key_prefix):
        df = pd.DataFrame(rows)
        display_cols = ["Rank", "Movement", "Player", "Team", "Rating", "Previous Rating", "Rating Change", "Status"]
        df = df[display_cols]
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Movement": st.column_config.TextColumn("Move", width="small"),
                "Rating": st.column_config.NumberColumn("New Rating", width="small"),
                "Previous Rating": st.column_config.NumberColumn("Previous", width="small"),
                "Rating Change": st.column_config.TextColumn("Change", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
            },
            key=key_prefix,
        )
        return df

    tabs = st.tabs(["🏏 Batting", "🎯 Bowling", "👑 All-Rounder", "📈 Weekly Report", "🛡️ Team Rankings", "🔎 Player Details", "⚙️ Benchmarks"])

    with tabs[0]:
        st.subheader("HCCL Batting Rankings")
        show_ranking_table(batting_rows, "batting_table")

    with tabs[1]:
        st.subheader("HCCL Bowling Rankings")
        show_ranking_table(bowling_rows, "bowling_table")

    with tabs[2]:
        st.subheader("HCCL All-Rounder Rankings")
        show_ranking_table(ar_rows, "ar_table")

    report_rows = weekly_report_rows(ratings, previous, official_only=official_only) if previous else []
    team_rows = []
    for kind in ["batting", "bowling", "all_rounder"]:
        team_rows.extend(team_ranking_dicts(ratings, kind, official_only=official_only, previous=previous))

    with tabs[3]:
        st.subheader("Weekly Ranking Report")
        if not previous:
            st.info("Upload previous rankings CSV to see top climbers, fallers, rating gains, and new entries.")
        else:
            report_df = pd.DataFrame(report_rows)
            section_order = ["Top Climbers", "Top Fallers", "Top Rating Gains", "New Entries"]
            for section in section_order:
                st.markdown(f"### {section}")
                section_df = report_df[report_df["Report Section"] == section]
                if section_df.empty:
                    st.caption("No players in this section.")
                else:
                    st.dataframe(section_df, use_container_width=True, hide_index=True)

    with tabs[4]:
        st.subheader("Team-wise Player Rankings")
        team_df = pd.DataFrame(team_rows)
        teams = sorted(team_df["Team"].dropna().unique().tolist()) if not team_df.empty else []
        categories = ["Batting", "Bowling", "All-Rounder"]
        selected_team = st.selectbox("Select team", options=["All Teams"] + teams)
        selected_category = st.selectbox("Select category", options=["All Categories"] + categories)
        filtered = team_df.copy()
        if selected_team != "All Teams":
            filtered = filtered[filtered["Team"] == selected_team]
        if selected_category != "All Categories":
            filtered = filtered[filtered["Category"] == selected_category]
        st.dataframe(filtered, use_container_width=True, hide_index=True)

    with tabs[5]:
        st.subheader("Player Rating Details")
        details_df = pd.DataFrame([r.__dict__ for r in ratings])
        st.dataframe(details_df, use_container_width=True, hide_index=True)

    with tabs[6]:
        st.subheader("Current Benchmarks")
        benchmark_df = pd.DataFrame([benchmarks]).T.reset_index()
        benchmark_df.columns = ["Benchmark", "Value"]
        st.dataframe(benchmark_df, use_container_width=True, hide_index=True)

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
    with d1:
        st.download_button("Download rankings CSV", data=rankings_output.read_bytes(), file_name="HCCL_Rankings_Updated.csv", mime="text/csv")
    with d2:
        st.download_button("Download weekly report CSV", data=report_output.read_bytes(), file_name="HCCL_Weekly_Report.csv", mime="text/csv")
    with d3:
        st.download_button("Download team rankings CSV", data=team_output.read_bytes(), file_name="HCCL_Team_Rankings.csv", mime="text/csv")
    with d4:
        st.download_button("Download player details CSV", data=details_output.read_bytes(), file_name="HCCL_Rating_Details.csv", mime="text/csv")
