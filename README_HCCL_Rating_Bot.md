# HCCL Player Rankings Dashboard v2

This upgraded dashboard calculates official HCCL Batting, Bowling, and All-Rounder rankings from the weekly `HCCL Stats.csv` file.

## New in v2

1. Ranking movement compared with previous week: `↑`, `↓`, `—`, `New`
2. Previous rating, new rating, and rating change
3. Weekly report: top climbers, fallers, rating gains, and new entries
4. Team-wise player rankings
5. More official HCCL-style dashboard layout

## Weekly workflow

1. Update your latest `HCCL Stats.csv` file.
2. Start the app.
3. Upload the latest stats CSV.
4. Upload last week's rankings CSV for movement comparison.
5. Download the updated outputs.

## Start on Windows

Double-click:

```text
START_HCCL_BOT_WINDOWS.bat
```

## Start manually

Install packages:

```bash
pip install -r requirements.txt
```

Run the dashboard:

```bash
streamlit run streamlit_app.py
```

## Command line usage

Without movement:

```bash
python hccl_rating_engine.py "HCCL Stats.csv"
```

With movement:

```bash
python hccl_rating_engine.py "HCCL Stats.csv" --previous-rankings "HCCL_Rankings_Updated.csv"
```

Official qualified players only:

```bash
python hccl_rating_engine.py "HCCL Stats.csv" --previous-rankings "HCCL_Rankings_Updated.csv" --official-only
```

## Output files

- `HCCL_Rankings_Updated.csv` - side-by-side rankings with movement, previous rating, and rating change
- `HCCL_Weekly_Report.csv` - top climbers, fallers, rating gains, and new entries
- `HCCL_Team_Rankings.csv` - team-wise category rankings
- `HCCL_Rating_Details.csv` - detailed calculated data for every player

## Previous rankings file

For movement, upload last week's rankings file. The app supports both:

- Your old `HCCL RANKINGS.csv` format
- The new `HCCL_Rankings_Updated.csv` format

If no previous rankings file is uploaded, the app still calculates rankings, but movement and weekly report sections stay blank.
