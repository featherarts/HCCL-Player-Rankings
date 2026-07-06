HCCL RANKINGS DASHBOARD v3 - EASY GUIDE
========================================

This version can save your weekly rankings online in Supabase.

WHAT YOU NEED TO DO FIRST
-------------------------
1. Create a Supabase project.
2. Open Supabase SQL Editor.
3. Paste and run the file named: supabase_schema.sql
4. Add your Supabase secrets to Streamlit Cloud.
5. Reboot/redeploy the Streamlit app.

SECRETS YOU NEED IN STREAMLIT CLOUD
-----------------------------------
SUPABASE_URL = "https://YOUR_PROJECT_ID.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_KEY"
HCCL_ADMIN_PASSWORD = "your-private-password"

Do not upload real secrets to GitHub.

HOW TO USE EVERY WEEK
---------------------
1. Open the Streamlit app.
2. Upload latest HCCL Stats.csv.
3. Choose previous rankings source:
   - First week: upload old CSV or choose no previous rankings.
   - After first Supabase save: choose saved Supabase snapshot.
4. Check Batting, Bowling, All-Rounder, Team Rankings, Weekly Report.
5. Open Save / Load tab.
6. Enter week label, for example Week 07.
7. Enter admin password.
8. Click Save Current Rankings.

NEXT TELEGRAM BOT STEP
----------------------
The saved Supabase data can be used by Telegram bot commands like:
/topbat
/topbowl
/topall
/player Hasitha
/team TeamName
/movers
/report
