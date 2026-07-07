from __future__ import annotations

import tempfile
from datetime import date
import hashlib
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
    calculate_formula_audit,
)
from scorecard_updater import update_stats_csv_from_scorecard

from supabase_storage import (
    get_admin_password,
    list_snapshots,
    previous_dict_from_snapshot,
    save_snapshot,
    supabase_is_configured,
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
    .db-ok {color: #48d17a; font-weight: 800;}
    .db-miss {color: #ffb86c; font-weight: 800;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hccl-hero">
        <div class="hccl-pill">OFFICIAL HCCL RANKINGS • DASHBOARD v4.8</div>
        <div class="hccl-title">HCCL Player Rankings Dashboard</div>
        <div class="hccl-subtitle">
            Upload weekly stats, update stats from scorecard PDFs, calculate official rankings, save snapshots to Supabase, and reuse saved rankings as next week's previous rankings.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Sidebar: files, previous source, DB status
# -----------------------------

with st.sidebar:
    st.header("Weekly Update")
    uploaded_file = st.file_uploader("1) Upload latest HCCL Stats CSV", type=["csv"])

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

    db_ready = supabase_is_configured()
    st.markdown("---")
    st.subheader("Previous Rankings Source")
    previous_options = ["No previous rankings", "Upload previous CSV"]
    if db_ready:
        previous_options.insert(1, "Use saved Supabase snapshot")

    previous_source = st.radio("2) Select previous source", previous_options)
    previous_file = None
    selected_snapshot_id = None

    saved_snapshots = []
    if previous_source == "Upload previous CSV":
        previous_file = st.file_uploader("Upload previous rankings CSV", type=["csv"])
    elif previous_source == "Use saved Supabase snapshot":
        try:
            saved_snapshots = list_snapshots(limit=30)
        except Exception as exc:
            st.error(f"Could not load saved snapshots: {exc}")
            saved_snapshots = []
        if saved_snapshots:
            snapshot_labels = [
                f"{s.get('week_label')} • {s.get('snapshot_date')} • {str(s.get('created_at', ''))[:19]}"
                for s in saved_snapshots
            ]
            selected_label = st.selectbox("Choose saved previous ranking", snapshot_labels)
            selected_snapshot_id = saved_snapshots[snapshot_labels.index(selected_label)]["id"]
        else:
            st.info("No saved snapshots yet. Calculate and save one first.")

    official_only = st.checkbox("Show official qualified players only", value=False)

    st.markdown("---")
    st.subheader("Database")
    if db_ready:
        st.markdown("<span class='db-ok'>Connected settings found</span>", unsafe_allow_html=True)
        st.caption("Supabase save/load is enabled.")
    else:
        st.markdown("<span class='db-miss'>Not configured</span>", unsafe_allow_html=True)
        st.caption("Add SUPABASE_URL and SUPABASE_KEY in Streamlit secrets to enable save/load.")

if uploaded_file is None and "active_stats_csv_bytes" not in st.session_state:
    st.info("Upload your latest `HCCL Stats.csv` file from the left sidebar to begin.")
    st.stop()

active_stats_csv_bytes = st.session_state.get("active_stats_csv_bytes")
if active_stats_csv_bytes is None and uploaded_file is not None:
    active_stats_csv_bytes = uploaded_file.getvalue()
    st.session_state["active_stats_csv_bytes"] = active_stats_csv_bytes
    st.session_state["active_stats_source"] = uploaded_file.name

# -----------------------------
# Main calculation
# -----------------------------

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
            previous_label = "Saved Supabase snapshot"
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

    if previous_loaded:
        st.success(f"Previous rankings loaded from: {previous_label}")
    else:
        st.warning("Movement, previous rating, and weekly climber/faller report need previous rankings. Upload a previous CSV or choose a saved Supabase snapshot.")

    def show_ranking_table(rows, key_prefix):
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
                "Rating": st.column_config.NumberColumn("New Rating", width="small"),
                "Previous Rating": st.column_config.NumberColumn("Previous", width="small"),
                "Rating Change": st.column_config.TextColumn("Change", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
            },
            key=key_prefix,
        )
        return df

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
        st.subheader("HCCL Batting Rankings")
        show_ranking_table(batting_rows, "batting_table")

    with tabs[1]:
        st.subheader("HCCL Bowling Rankings")
        show_ranking_table(bowling_rows, "bowling_table")

    with tabs[2]:
        st.subheader("HCCL All-Rounder Rankings")
        show_ranking_table(ar_rows, "ar_table")

    with tabs[3]:
        st.subheader("Weekly Ranking Report")
        if not previous:
            st.info("Upload previous rankings CSV or choose a saved snapshot to see top climbers, fallers, rating gains, and new entries.")
        else:
            report_df = pd.DataFrame(report_rows)
            section_order = ["Top Climbers", "Top Fallers", "Top Rating Gains", "New Entries"]
            for section in section_order:
                st.markdown(f"### {section}")
                section_df = report_df[report_df["Report Section"] == section] if not report_df.empty else pd.DataFrame()
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
        if not filtered.empty and selected_team != "All Teams":
            filtered = filtered[filtered["Team"] == selected_team]
        if not filtered.empty and selected_category != "All Categories":
            filtered = filtered[filtered["Category"] == selected_category]
        st.dataframe(filtered, use_container_width=True, hide_index=True)

    with tabs[5]:
        st.subheader("Player Rating Details")
        details_df = pd.DataFrame(detail_rows)
        st.dataframe(details_df, use_container_width=True, hide_index=True)

    with tabs[6]:
        st.subheader("Current Benchmarks")
        benchmark_df = pd.DataFrame([benchmarks]).T.reset_index()
        benchmark_df.columns = ["Benchmark", "Value"]
        st.dataframe(benchmark_df, use_container_width=True, hide_index=True)



    with tabs[7]:
        st.subheader("Formula Audit / Player Calculation Check")
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
        st.subheader("Update HCCL Stats CSV from Scorecard PDF")
        st.caption("Upload one STUMPS match scorecard PDF. The app will update career totals and recent 5 form, then give you a new HCCL Stats CSV to download. It will not overwrite your original file.")

        st.markdown("""
        **Your CSV can use the `Stumps Name` column.**  
        Put the exact name used in the STUMPS scorecard PDF there, for example `Kalana Thenu`, `Sasi18`, or `Pasindu Dilshan`.
        If a scorecard player is not found in the CSV, the app will first try a safe fuzzy match against `Stumps Name` and `NAME`. Only if no safe match exists will it add a new player row.
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
                with c1:
                    st.metric("Match ID", summary.get("match_id") or "-")
                with c2:
                    st.metric("POTM", summary.get("player_of_match") or "-")
                with c3:
                    st.metric("Batting rows found", summary.get("batting_rows_found", 0))
                with c4:
                    st.metric("Bowling rows found", summary.get("bowling_rows_found", 0))
                with c5:
                    st.metric("Existing players updated", summary.get("existing_players_updated", 0))
                with c6:
                    st.metric("New players added", summary.get("new_players_added", 0))

                trace_df = pd.DataFrame(update_result.get("match_trace", []))
                st.markdown("### Player matching + update trace")
                if trace_df.empty:
                    st.warning("No scorecard player rows were matched or added. The PDF table was probably not parsed correctly.")
                else:
                    st.dataframe(trace_df.drop_duplicates(), use_container_width=True, hide_index=True)

                st.markdown("### Parsed batting updates")
                bat_df = pd.DataFrame(update_result["batting_updates"])
                if bat_df.empty:
                    st.warning("No batting rows were updated.")
                else:
                    st.dataframe(bat_df, use_container_width=True, hide_index=True)

                st.markdown("### Parsed bowling updates")
                bowl_df = pd.DataFrame(update_result["bowling_updates"])
                if bowl_df.empty:
                    st.warning("No bowling rows were updated.")
                else:
                    st.dataframe(bowl_df, use_container_width=True, hide_index=True)

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
                    st.error(
                        "No player stat values changed. This means the PDF was not parsed into usable scorecard rows, "
                        "or this exact scorecard has already been applied. Do not use the downloaded CSV until this table shows changed players."
                    )
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
        st.subheader("Save Current Rankings to Supabase")
        if not db_ready:
            st.error("Supabase is not configured yet. Add SUPABASE_URL and SUPABASE_KEY in Streamlit secrets, then restart/redeploy the app.")
        else:
            st.caption("Save one snapshot after you verify the weekly rankings. Next week, use this saved snapshot as the previous rankings source.")
            week_label = st.text_input("Week label", value=f"Week {date.today().isoformat()}")
            snapshot_date = st.date_input("Snapshot date", value=date.today())
            notes = st.text_area("Notes", placeholder="Example: Rankings after Match 48 / Week 7 update")

            configured_password = get_admin_password()
            password_ok = True
            entered_password = ""
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
                    st.info("Next week, choose 'Use saved Supabase snapshot' in the sidebar and select this week as the previous ranking.")
                except Exception as exc:
                    st.error(f"Could not save to Supabase: {exc}")

            st.markdown("### Saved Snapshots")
            try:
                snapshots = list_snapshots(limit=20)
                if snapshots:
                    st.dataframe(pd.DataFrame(snapshots), use_container_width=True, hide_index=True)
                else:
                    st.caption("No snapshots saved yet.")
            except Exception as exc:
                st.error(f"Could not load saved snapshots: {exc}")

    # -----------------------------
    # Downloads
    # -----------------------------

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
