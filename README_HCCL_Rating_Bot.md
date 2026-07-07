# HCCL Rankings Dashboard v3

This version adds **Supabase save/load** to the HCCL Rankings Dashboard.

## What v3 can do

- Upload latest `HCCL Stats.csv`
- Calculate Batting, Bowling, and All-Rounder rankings
- Compare with previous rankings from either:
  - uploaded previous CSV, or
  - saved Supabase ranking snapshot
- Save the current rankings into Supabase
- Reuse saved rankings next week for movement columns
- Download rankings, weekly report, team rankings, and player details

---

## Files

- `streamlit_app.py` — the dashboard app
- `hccl_rating_engine.py` — the official HCCL rating calculation engine
- `supabase_storage.py` — Supabase save/load functions
- `supabase_schema.sql` — database tables to create in Supabase
- `requirements.txt` — Python packages
- `.streamlit/secrets.toml.example` — example secrets file, never commit real secrets
- `START_HCCL_BOT_WINDOWS.bat` — local Windows start file

---

## Supabase setup

### 1. Create a Supabase project

Go to Supabase and create a free project.

### 2. Create tables

Open your Supabase project:

`SQL Editor` → paste the full contents of `supabase_schema.sql` → click `Run`.

### 3. Add secrets to Streamlit Cloud

In Streamlit Community Cloud:

`Your app` → `Settings` → `Secrets`

Paste this, using your own values:

```toml
SUPABASE_URL = "https://YOUR_PROJECT_ID.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_SERVICE_ROLE_OR_ANON_KEY"
HCCL_ADMIN_PASSWORD = "choose-a-private-save-password"
```

Do **not** put real secrets inside GitHub.

### 4. Redeploy / reboot the Streamlit app

After adding secrets, redeploy or reboot the app.

---

## Weekly workflow

### First week with Supabase

1. Upload latest `HCCL Stats.csv`
2. Select `No previous rankings` or upload old previous rankings CSV
3. Check all ranking tabs
4. Go to `Save / Load`
5. Enter week label, for example `Week 07`
6. Enter admin password
7. Click `Save Current Rankings`

### Next week

1. Upload latest `HCCL Stats.csv`
2. In sidebar choose `Use saved Supabase snapshot`
3. Select last week's saved ranking
4. Check movement, rating changes, weekly report
5. Save this week as a new snapshot

---

## Telegram bot preparation

This database structure is ready for the next part: a Telegram bot can read from these tables:

- `hccl_snapshots`
- `hccl_rankings`
- `hccl_weekly_report`
- `hccl_team_rankings`
- `hccl_rating_details`
- `hccl_benchmarks`

Useful future commands:

- `/topbat`
- `/topbowl`
- `/topall`
- `/player Hasitha`
- `/team Team Name`
- `/movers`
- `/fallers`
- `/report`
- `/benchmarks`

## v3.1 Supabase save fix

This version fixes the Supabase save error:

```text
invalid input syntax for type integer: ""
```

The issue happened when a player had no previous rank/rating yet. The app used a blank value, but Supabase integer/numeric columns require `NULL`. v3.1 converts blank values to `NULL` before saving.

If a failed save already created an empty snapshot, you can delete it from the `hccl_snapshots` table in Supabase. Deleting the snapshot also deletes linked rows because the schema uses cascade delete.


## v4 Scorecard PDF Update + Auto Add Players Feature

Dashboard v4.4 adds a **Scorecard Update** tab.

Workflow:

1. Upload the latest `HCCL Stats.csv` in the sidebar.
2. Open the `🧾 Scorecard Update` tab.
3. Upload one STUMPS match scorecard PDF.
4. Review the parsed batting and bowling updates.
5. If any scorecard names are unmatched, add/fix the `Stumps Name` or `Stumps Name / Scorecard Username` column in your stats CSV and try again.
6. Download `HCCL Stats Updated From Scorecard.csv`.
7. Upload that downloaded CSV back in the sidebar to calculate new rankings.
8. Save the new ranking snapshot to Supabase.

Recommended extra columns in the stats CSV:

- `Stumps Name` or `Stumps Name / Scorecard Username` — exact name used in the scorecard PDF. You can add multiple aliases separated by commas.
- `Bat Dismissals` — helper column used to keep batting average accurate.
- `Bowl Runs Conceded` — helper column used to keep bowling average/economy accurate.

The rating engine ignores these helper columns, but the scorecard updater uses them for cleaner weekly updates.


## v4.4 Auto-add players

This version supports the user's new CSV layout with `Stumps Name` after `NAME`.

If a player appears in a STUMPS scorecard PDF but is not found in the CSV by `Stumps Name`, `Scorecard Username`, or `NAME`, the app automatically adds a new player row to the downloaded updated stats CSV. The new row starts with zero career stats and then applies the match stats from the PDF.

Recommended weekly process:
1. Upload your latest HCCL Stats CSV.
2. Open the Scorecard Update tab.
3. Upload the match scorecard PDF.
4. Review matched players and new players added.
5. Download the updated HCCL Stats CSV.
6. Upload the downloaded CSV in the sidebar to generate updated rankings.


## v4.4 Fix - Apply Scorecard Update Immediately

The Scorecard Update tab now has an **Apply updated stats to rankings now** button. After parsing a PDF, click this button to refresh the rankings in the same app session without downloading and re-uploading the CSV. You can still download the updated CSV for backup.


## v4.4 fix

The Scorecard Update tab now shows a `Stats changed in downloaded CSV` table before download. The download button is disabled if no player stat values changed, and generated filenames include match ID plus a hash so you do not accidentally open an older download.

## v4.5 Scorecard updater fix

This version adds a stronger existing-player matching step for scorecard PDF updates. The app now shows a **Player matching + update trace** table. Existing scorecard names should show **Updated existing player**. Only genuinely missing names should show **Added new player row**.

If a scorecard player name is slightly different from the CSV, the updater checks `Stumps Name`, `NAME`, short name tokens, and a safe fuzzy match before adding a new row. The downloaded updated stats CSV is disabled unless visible player stats changed.

## v4.6 exact stats update notes

The Scorecard Update tab now updates the actual player stats CSV, not only rankings.

For each player found in the uploaded scorecard:

- Batting: innings, runs, balls faced, 30s, 50s, ducks, batting recent form, batting average, strike rate and RAP are updated.
- Batting average uses estimated dismissals from `current RUNS / current AVG`, then adds one dismissal only if the batter was out in the scorecard.
- Bowling: wickets, balls bowled, runs conceded helper, 3Fers, 4Fers, bowling recent form, bowling average, economy, BSR and BAP are updated.
- Bowling runs conceded is estimated from `current Bowl AVG × current WICKETS` when the helper column is not already present.
- If a scorecard player is not already in the CSV, the app adds him as a new row.

Example: if Yasitha has 74 innings, 1138 runs, 458 balls, 16.5 average and 248.5 SR, then a scorecard innings of 10 off 5 while out becomes 75 innings, 1148 runs, 463 balls. Dismissals are estimated as round(1138 / 16.5) = 69, then +1 because he was out, so new average is 1148 / 70 = 16.4 and new SR is 1148 / 463 × 100 = 247.9.

## v4.7 Fix - STUMPS split-cell PDF parser

This version fixes STUMPS PDFs where PyMuPDF extracts table cells one by one instead of one full row per line. Example fixed structure:

```text
Yasitha (C)
b Kasun
12
3
0
2
400.0
```

The updater now reads these split-cell batting and bowling rows, updates existing players, recalculates batting average from estimated dismissals, recalculates bowling average from estimated runs conceded, and only adds genuinely missing players.

Tested with Match ID `wekv4064`:

- Batting rows found: 9
- Bowling rows found: 6
- Existing players updated: 10
- New players added: 1 (`Navindu Pamod`)


## v4.8 Formula Audit tab

This version adds a new `Formula Audit` tab.

Use it to select any player and recheck the rating calculation line by line:

- Raw player stats used from the uploaded HCCL Stats CSV
- Current benchmark values used for normalization
- Batting calculation steps: Runs Score, Average Score, Strike Rate Score, Career Score, Recent Form, Achievement Score, Experience Score and Final Rating
- Bowling calculation steps: Wickets Score, Bowling Average Score, Economy Score, BSR Score, Career Score, Recent Form, Achievement Score and Final Rating
- All-rounder calculation using the geometric mean
- Recent 5 match point breakdown for batting and bowling

This tab uses the same rating engine functions as the dashboard ranking tables, so the rounded final ratings should match the displayed Batting, Bowling and All-Rounder rankings.

## v4.9 fix

- Fixed Recent 5 Matches CSV parsing.
- The dashboard now preserves quoted multiline Recent 5 cells correctly.
- Formula Audit now shows all 5 recent matches instead of treating only the first joined line as Match 1.
- Added fallback support for older CSVs where recent-form entries were accidentally joined together without newlines.

## v5.0 Expose Bot Support

Player detail snapshots now save raw batting and bowling recent-5 data into Supabase:

- `batting_recent_raw`
- `bowling_recent_raw`
- `batting_recent_points`
- `bowling_recent_points`

This allows the Telegram bot `/expose` command to show inning-by-inning recent performances, not only final recent form scores. After updating to this dashboard version, save a fresh Supabase snapshot before using `/expose`.

## Dashboard v5.1 - Modern UI + Auto Saved Rankings

This version adds a redesigned modern interface and opens directly with the latest saved Supabase ranking snapshot when no new CSV is uploaded.

### New behavior

- When you open the Streamlit site, it automatically shows the latest saved rankings from Supabase.
- You can still upload a new weekly HCCL Stats CSV from the sidebar to enter update mode.
- When update mode is active, the previous rankings source defaults to the latest saved Supabase snapshot when available.
- The UI has redesigned hero section, leader cards, KPI cards, improved tabs, and cleaner saved-ranking view.

### Weekly workflow

1. Open the dashboard and view the latest saved rankings immediately.
2. Upload the new HCCL Stats CSV only when you want to calculate the next update.
3. Update stats from scorecard PDF if needed.
4. Verify rankings and formula audit.
5. Save the new snapshot to Supabase.
6. Next time the app opens, that saved snapshot is shown automatically.

## v5.3 Team Logo Upgrade

This version adds official team logo support for the dashboard.

Included logos are stored here:

```text
assets/team_logos/
```

Supported team keys:

```text
AURA
REAPERS
DRAGONS
MATRIX
TEARZ
LORDS
GAMERS
TITANS
```

The dashboard uses these logos in:

```text
- Team logo strip near the top of the dashboard
- Ranking leader cards
- Batting/Bowling/All-Rounder ranking tables
- Weekly report tables
- Team rankings
- Player details tables
```

If you replace a logo later, keep the same file name, for example:

```text
assets/team_logos/AURA.png
```

Then commit the updated image to GitHub and redeploy Streamlit.


## v5.3 update

- Removed the separate HCCL Teams logo strip from the top dashboard view because team logos already appear cleanly in leader cards and ranking tables.
- Team logos are still included in ranking leader cards and tables.
