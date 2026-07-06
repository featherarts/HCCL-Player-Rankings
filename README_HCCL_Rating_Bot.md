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
