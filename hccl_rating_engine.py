"""HCCL Rating Engine v2.0

Calculates official HCCL Batting, Bowling, and All-Rounder rankings from the
weekly HCCL stats CSV.

New in v2.0:
- Ranking movement compared with a previous rankings CSV
- Previous rating and rating change columns
- Weekly report: top climbers, fallers, rating gains, new entries
- Team-wise rankings

Usage:
    python hccl_rating_engine.py "HCCL Stats.csv" --previous-rankings "HCCL_Rankings_Updated.csv"

Outputs:
    HCCL_Rankings_Updated.csv
    HCCL_Rating_Details.csv
    HCCL_Weekly_Report.csv
    HCCL_Team_Rankings.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Canonical internal column map. The reader supports both the old HCCL Stats.csv layout
# and the new layout with a Stumps Name column inserted after NAME.
EXPECTED_COLUMNS = [
    "ID", "NAME", "TEAM", "Innings", "RUNS", "Balls Faced", "Bat AVG", "SR",
    "30s", "50s", "0s", "POTMs", "RAP", "Bat Recent 5 Matches",
    "WICKETS", "Balls Bowled", "Bowl AVG", "ECO", "3Fers", "4Fers", "BSR", "BAP",
    "Bowl Recent 5 Matches", "Blank",
]

KIND_LABELS = {
    "batting": "Batting",
    "bowling": "Bowling",
    "all_rounder": "All-Rounder",
}

KIND_TITLES = {
    "batting": "HCCL Batting Rankings",
    "bowling": "HCCL Bowling Rankings",
    "all_rounder": "HCCL All-Rounder Rankings",
}


# -----------------------------
# Helpers
# -----------------------------

def to_float(value: object) -> float:
    try:
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return 0.0
        return float(text)
    except Exception:
        return 0.0


def to_int(value: object) -> int:
    try:
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return 0
        return int(float(text))
    except Exception:
        return 0


def normalize_name(name: object) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def is_yes(line: str, label: str) -> bool:
    pattern = rf"{re.escape(label)}\s+Yes"
    return re.search(pattern, line, flags=re.IGNORECASE) is not None


def split_recent_lines(recent_text: object) -> List[str]:
    """Split a Recent 5 Matches cell into exactly the match lines it contains.

    The HCCL stats CSV stores recent-form cells as quoted multiline CSV values.
    Some older versions of the CSV reader accidentally removed those embedded
    newline characters and joined the lines together like `... POTM No2. 25 runs`.
    This splitter supports both valid multiline cells and those older joined cells.
    """
    text = str(recent_text or "").replace("\\n", "\n").strip()
    if not text or text.lower() == "nan":
        return []

    # Normal case: quoted CSV multiline field was preserved correctly.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines[:5]

    # Fallback case: lines were joined together. Split before numbered entries
    # like `2.`, but avoid decimals such as 163.6 or 0.5.
    joined = lines[0] if lines else text
    matches = list(re.finditer(r"(?<![\d.])([1-5])\.\s*", joined))
    if len(matches) > 1:
        entries: List[str] = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(joined)
            entry = joined[start:end].strip()
            if entry:
                entries.append(entry)
        return entries[:5]

    return [joined]


def rating_display(value: Optional[float]) -> str:
    if value is None:
        return ""
    return str(round(value))


def signed_int_display(value: Optional[float]) -> str:
    if value is None:
        return ""
    rounded = int(round(value))
    if rounded > 0:
        return f"+{rounded}"
    return str(rounded)


# -----------------------------
# Official formula helpers
# -----------------------------

def runs_points(runs: int) -> int:
    if runs == 0:
        return -10
    if 1 <= runs <= 5:
        return 0
    if 6 <= runs <= 9:
        return 5
    if 10 <= runs <= 19:
        return 10
    if 20 <= runs <= 29:
        return 25
    if 30 <= runs <= 49:
        return 35
    return 50


def batting_sr_bonus(strike_rate: float) -> int:
    # Official table: below 100 = -10, above 200 = +5, above 300 = +10.
    # Highest matching tier is used; bonuses are not cumulative.
    if strike_rate > 300:
        return 10
    if strike_rate > 200:
        return 5
    if strike_rate < 100:
        return -10
    return 0


def wicket_points(wickets: int) -> int:
    if wickets <= 0:
        return 0
    if wickets == 1:
        return 25
    if wickets == 2:
        return 50
    if wickets == 3:
        return 75
    return 100


def economy_bonus(economy: float) -> int:
    # Official table: above 15 = -10, below 12 = +5, below 9 = +10, below 6 = +20.
    # Highest matching tier is used; bonuses are not cumulative.
    if economy > 15:
        return -10
    if economy < 6:
        return 20
    if economy < 9:
        return 10
    if economy < 12:
        return 5
    return 0


def experience_score(innings: int) -> int:
    if innings >= 50:
        return 100
    if innings >= 40:
        return 70
    if innings >= 30:
        return 50
    if innings >= 20:
        return 30
    if innings >= 10:
        return 10
    return 0


def parse_batting_recent(recent_text: str) -> Tuple[float, List[int]]:
    """Return recent form score and individual match points for batting."""
    points: List[int] = []

    for line in split_recent_lines(recent_text):

        match_points = 0
        dnb = "DNB" in line.upper()

        if not dnb:
            runs_match = re.search(r"(\d+)\s*runs?", line, flags=re.IGNORECASE)
            sr_match = re.search(r"([0-9.]+)\s*SR", line, flags=re.IGNORECASE)

            runs = int(runs_match.group(1)) if runs_match else 0
            strike_rate = float(sr_match.group(1)) if sr_match else 0.0

            match_points += runs_points(runs)
            match_points += batting_sr_bonus(strike_rate)

            if is_yes(line, "Highest scorer"):
                match_points += 20
            if is_yes(line, "Not out"):
                match_points += 5

        if is_yes(line, "POTM"):
            match_points += 20

        points.append(match_points)

    # Formula says last 5 matches, so denominator is always 5.
    # Missing lines are treated as 0 points.
    return sum(points) / 5.0, points


def parse_bowling_recent(recent_text: str) -> Tuple[float, List[int]]:
    """Return recent form score and individual match points for bowling."""
    points: List[int] = []

    for line in split_recent_lines(recent_text):

        match_points = 0
        dnb = "DNB" in line.upper()

        if not dnb:
            wicket_match = re.search(r"(\d+)\s*Wickets?", line, flags=re.IGNORECASE)
            eco_match = re.search(r"([0-9.]+)\s*Eco", line, flags=re.IGNORECASE)

            wickets = int(wicket_match.group(1)) if wicket_match else 0
            economy = float(eco_match.group(1)) if eco_match else 0.0

            match_points += wicket_points(wickets)
            match_points += economy_bonus(economy)

        if is_yes(line, "POTM"):
            match_points += 20

        points.append(match_points)

    # Formula says last 5 team matches; DNB and missing lines are 0-point matches.
    return sum(points) / 5.0, points


# -----------------------------
# Dataclasses
# -----------------------------

@dataclass
class PlayerRating:
    player_id: str
    name: str
    team: str
    innings: int
    runs: float
    wickets: float
    batting_qualified: bool
    bowling_qualified: bool
    all_rounder_qualified: bool
    batting_rating: Optional[float]
    bowling_rating: Optional[float]
    all_rounder_rating: Optional[float]
    batting_recent_form: float
    bowling_recent_form: float
    batting_recent_raw: str
    bowling_recent_raw: str
    batting_recent_points: str
    bowling_recent_points: str
    batting_career_score: Optional[float]
    bowling_career_score: Optional[float]
    achievement_score_batting: Optional[float]
    achievement_score_bowling: Optional[float]
    experience_score: int


@dataclass
class PreviousEntry:
    rank: int
    player: str
    rating: float


# -----------------------------
# CSV readers
# -----------------------------

def _decode_csv_bytes(data: bytes) -> str:
    last_error: Optional[Exception] = None
    for enc in ("utf-8-sig", "utf-8", "mac_roman", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Could not decode stats CSV. Last error: {last_error}")


def _header_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\ufeff", "").strip().lower())


def _find_header(header: List[str], aliases: List[str]) -> Optional[int]:
    wanted = {_header_key(a) for a in aliases}
    for i, h in enumerate(header):
        if _header_key(h) in wanted:
            return i
    return None


def _find_all_headers(header: List[str], aliases: List[str]) -> List[int]:
    wanted = {_header_key(a) for a in aliases}
    return [i for i, h in enumerate(header) if _header_key(h) in wanted]


def _detect_stats_columns(header: List[str]) -> Dict[str, Optional[int]]:
    idx: Dict[str, Optional[int]] = {
        "ID": _find_header(header, ["ID"]),
        "NAME": _find_header(header, ["NAME", "Player", "Player Name"]),
        "TEAM": _find_header(header, ["TEAM", "Team"]),
        "Innings": _find_header(header, ["Innings", "Inns"]),
        "RUNS": _find_header(header, ["RUNS", "Runs"]),
        "Balls Faced": _find_header(header, ["Balls Faced", "BF", "Balls"]),
        "SR": _find_header(header, ["SR", "Strike Rate"]),
        "30s": _find_header(header, ["30s", "Thirties"]),
        "50s": _find_header(header, ["50s", "Fifties"]),
        "0s": _find_header(header, ["0s", "Ducks"]),
        "POTMs": _find_header(header, ["POTMs", "POTM"]),
        "RAP": _find_header(header, ["RAP"]),
        "WICKETS": _find_header(header, ["WICKETS", "Wickets"]),
        "Balls Bowled": _find_header(header, ["Balls Bowled", "BB"]),
        "ECO": _find_header(header, ["ECO", "Economy"]),
        "3Fers": _find_header(header, ["3Fers", "3-Fers", "3fers"]),
        "4Fers": _find_header(header, ["4Fers", "4-Fers", "4fers"]),
        "BSR": _find_header(header, ["BSR", "Bowling Strike Rate"]),
        "BAP": _find_header(header, ["BAP"]),
        "Blank": _find_header(header, [""]),
    }

    avg_cols = _find_all_headers(header, ["AVG", "Average"])
    idx["Bat AVG"] = _find_header(header, ["Bat AVG", "Batting AVG", "Batting Average"])
    idx["Bowl AVG"] = _find_header(header, ["Bowl AVG", "Bowling AVG", "Bowling Average"])
    if idx["Bat AVG"] is None and avg_cols:
        idx["Bat AVG"] = avg_cols[0]
    if idx["Bowl AVG"] is None:
        if len(avg_cols) >= 2:
            idx["Bowl AVG"] = avg_cols[1]
        elif avg_cols:
            idx["Bowl AVG"] = avg_cols[-1]

    recent_cols = _find_all_headers(header, ["Recent 5 Matches", "Recent Five Matches"])
    idx["Bat Recent 5 Matches"] = _find_header(header, ["Bat Recent 5 Matches", "Batting Recent 5 Matches"])
    idx["Bowl Recent 5 Matches"] = _find_header(header, ["Bowl Recent 5 Matches", "Bowling Recent 5 Matches"])
    if idx["Bat Recent 5 Matches"] is None and recent_cols:
        idx["Bat Recent 5 Matches"] = recent_cols[0]
    if idx["Bowl Recent 5 Matches"] is None:
        if len(recent_cols) >= 2:
            idx["Bowl Recent 5 Matches"] = recent_cols[1]
        elif recent_cols:
            idx["Bowl Recent 5 Matches"] = recent_cols[-1]

    return idx


def read_stats_csv(csv_path: str | Path) -> List[Dict[str, str]]:
    path = Path(csv_path)
    text = _decode_csv_bytes(path.read_bytes())
    rows = list(csv.reader(io.StringIO(text)))

    if not rows:
        raise ValueError("The stats CSV is empty.")

    header = rows[0]
    col_idx = _detect_stats_columns(header)

    missing = [col for col in EXPECTED_COLUMNS if col != "Blank" and col_idx.get(col) is None]
    if missing:
        raise ValueError("Missing required HCCL stats columns: " + ", ".join(missing))

    players: List[Dict[str, str]] = []
    for row in rows[1:]:
        if not any(str(cell).strip() for cell in row):
            continue
        player: Dict[str, str] = {}
        for col in EXPECTED_COLUMNS:
            pos = col_idx.get(col)
            player[col] = row[pos] if pos is not None and pos < len(row) else ""
        players.append(player)

    return players


def parse_previous_rankings(csv_path: str | Path) -> Dict[str, Dict[str, PreviousEntry]]:
    """Parse old or new side-by-side HCCL rankings CSV.

    Supported formats:
    - Old: Rank,Player,Rating,,Rank,Player,Rating,,Rank,Player,Rating
    - New v1: titles row + Rank,Player,Rating,Status...
    - New v2: titles row + Rank,Movement,Player,Team,Rating,Previous Rating...
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Previous rankings file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    result: Dict[str, Dict[str, PreviousEntry]] = {
        "batting": {},
        "bowling": {},
        "all_rounder": {},
    }

    if not rows:
        return result

    header_idx: Optional[int] = None
    for idx, row in enumerate(rows):
        lowered = [str(cell).strip().lower() for cell in row]
        if "rank" in lowered and "player" in lowered and "rating" in lowered:
            header_idx = idx
            break

    if header_idx is None:
        return result

    header = [str(cell).strip() for cell in rows[header_idx]]
    header_lower = [cell.lower() for cell in header]
    rank_indices = [i for i, cell in enumerate(header_lower) if cell == "rank"]
    kinds = ["batting", "bowling", "all_rounder"]

    for group_num, start in enumerate(rank_indices[:3]):
        kind = kinds[group_num]
        end = rank_indices[group_num + 1] if group_num + 1 < len(rank_indices) else len(header)
        group_headers = header_lower[start:end]

        def find_col(name: str) -> Optional[int]:
            try:
                return start + group_headers.index(name)
            except ValueError:
                return None

        player_col = find_col("player")
        rating_col = find_col("rating")
        if player_col is None or rating_col is None:
            continue

        for row in rows[header_idx + 1:]:
            padded = row + [""] * (max(start, player_col, rating_col) + 1 - len(row))
            rank = to_int(padded[start])
            player = str(padded[player_col]).strip()
            rating = to_float(padded[rating_col])
            if not rank or not player:
                continue
            result[kind][normalize_name(player)] = PreviousEntry(rank=rank, player=player, rating=rating)

    return result


# -----------------------------
# Qualification and ratings
# -----------------------------

def batting_qualified(player: Dict[str, str]) -> bool:
    return to_int(player["Innings"]) >= 10 and to_float(player["RUNS"]) >= 100


def bowling_qualified(player: Dict[str, str]) -> bool:
    return to_float(player["WICKETS"]) >= 10


def all_rounder_qualified(player: Dict[str, str]) -> bool:
    return to_float(player["RUNS"]) >= 100 and to_float(player["WICKETS"]) >= 10


def calculate_benchmarks(players: List[Dict[str, str]]) -> Dict[str, float]:
    bat_players = [p for p in players if batting_qualified(p)]
    bowl_players = [p for p in players if bowling_qualified(p)]

    if not bat_players:
        raise ValueError("No players meet batting qualification: 10 innings and 100 runs.")
    if not bowl_players:
        raise ValueError("No players meet bowling qualification: 10 wickets.")

    return {
        "highest_runs": max(to_float(p["RUNS"]) for p in bat_players),
        "highest_bat_avg": max(to_float(p["Bat AVG"]) for p in bat_players),
        "highest_sr": max(to_float(p["SR"]) for p in bat_players),
        "highest_rap": max(to_float(p["RAP"]) for p in bat_players),
        "highest_wickets": max(to_float(p["WICKETS"]) for p in bowl_players),
        "best_bowl_avg": min(to_float(p["Bowl AVG"]) for p in bowl_players if to_float(p["Bowl AVG"]) > 0),
        "best_eco": min(to_float(p["ECO"]) for p in bowl_players if to_float(p["ECO"]) > 0),
        "best_bsr": min(to_float(p["BSR"]) for p in bowl_players if to_float(p["BSR"]) > 0),
        "highest_bap": max(to_float(p["BAP"]) for p in bowl_players),
    }


def calculate_ratings(players: List[Dict[str, str]]) -> Tuple[List[PlayerRating], Dict[str, float]]:
    benchmarks = calculate_benchmarks(players)
    output: List[PlayerRating] = []

    for p in players:
        innings = to_int(p["Innings"])
        runs = to_float(p["RUNS"])
        wickets = to_float(p["WICKETS"])

        bat_recent, bat_recent_points = parse_batting_recent(p["Bat Recent 5 Matches"])
        bowl_recent, bowl_recent_points = parse_bowling_recent(p["Bowl Recent 5 Matches"])
        exp_score = experience_score(innings)

        bat_ok = batting_qualified(p)
        bowl_ok = bowling_qualified(p)
        ar_ok = all_rounder_qualified(p)

        batting_rating: Optional[float] = None
        batting_career: Optional[float] = None
        batting_achievement: Optional[float] = None

        # Calculate provisional ratings too. Status flags show official/provisional.
        if runs > 0 or innings > 0:
            runs_score = (runs / benchmarks["highest_runs"] * 100) if benchmarks["highest_runs"] else 0
            avg_score = (to_float(p["Bat AVG"]) / benchmarks["highest_bat_avg"] * 100) if benchmarks["highest_bat_avg"] else 0
            sr_score = (to_float(p["SR"]) / benchmarks["highest_sr"] * 100) if benchmarks["highest_sr"] else 0
            batting_career = (runs_score * 0.50) + (avg_score * 0.30) + (sr_score * 0.20)
            batting_achievement = (to_float(p["RAP"]) / benchmarks["highest_rap"] * 100) if benchmarks["highest_rap"] else 0
            batting_rating = 100 + (batting_career * 5) + (bat_recent * 3) + batting_achievement + exp_score

        bowling_rating: Optional[float] = None
        bowling_career: Optional[float] = None
        bowling_achievement: Optional[float] = None

        if wickets > 0:
            wickets_score = (wickets / benchmarks["highest_wickets"] * 100) if benchmarks["highest_wickets"] else 0
            avg_score = (benchmarks["best_bowl_avg"] / to_float(p["Bowl AVG"]) * 100) if to_float(p["Bowl AVG"]) else 0
            eco_score = (benchmarks["best_eco"] / to_float(p["ECO"]) * 100) if to_float(p["ECO"]) else 0
            bsr_score = (benchmarks["best_bsr"] / to_float(p["BSR"]) * 100) if to_float(p["BSR"]) else 0
            bowling_career = (wickets_score * 0.60) + (avg_score * 0.20) + (eco_score * 0.10) + (bsr_score * 0.10)
            bowling_achievement = (to_float(p["BAP"]) / benchmarks["highest_bap"] * 100) if benchmarks["highest_bap"] else 0
            bowling_rating = 100 + (bowling_career * 5) + (bowl_recent * 3) + (bowling_achievement * 2)

        all_rounder_rating: Optional[float] = None
        if batting_rating is not None and bowling_rating is not None:
            all_rounder_rating = math.sqrt(batting_rating * bowling_rating)

        output.append(
            PlayerRating(
                player_id=p["ID"],
                name=p["NAME"],
                team=p["TEAM"],
                innings=innings,
                runs=runs,
                wickets=wickets,
                batting_qualified=bat_ok,
                bowling_qualified=bowl_ok,
                all_rounder_qualified=ar_ok,
                batting_rating=batting_rating,
                bowling_rating=bowling_rating,
                all_rounder_rating=all_rounder_rating,
                batting_recent_form=bat_recent,
                bowling_recent_form=bowl_recent,
                batting_recent_raw=str(p.get("Bat Recent 5 Matches", "")),
                bowling_recent_raw=str(p.get("Bowl Recent 5 Matches", "")),
                batting_recent_points=", ".join(str(int(x)) for x in bat_recent_points),
                bowling_recent_points=", ".join(str(int(x)) for x in bowl_recent_points),
                batting_career_score=batting_career,
                bowling_career_score=bowling_career,
                achievement_score_batting=batting_achievement,
                achievement_score_bowling=bowling_achievement,
                experience_score=exp_score,
            )
        )

    return output, benchmarks


# -----------------------------
# Ranking views
# -----------------------------

def rating_for_kind(r: PlayerRating, kind: str) -> Optional[float]:
    if kind == "batting":
        return r.batting_rating
    if kind == "bowling":
        return r.bowling_rating
    if kind == "all_rounder":
        return r.all_rounder_rating
    raise ValueError(f"Unknown ranking kind: {kind}")


def qualification_for_kind(r: PlayerRating, kind: str) -> bool:
    if kind == "batting":
        return r.batting_qualified
    if kind == "bowling":
        return r.bowling_qualified
    if kind == "all_rounder":
        return r.all_rounder_qualified
    raise ValueError(f"Unknown ranking kind: {kind}")


def movement_display(current_rank: int, previous_rank: Optional[int]) -> str:
    if previous_rank is None:
        return "New"
    diff = previous_rank - current_rank
    if diff > 0:
        return f"↑ {diff}"
    if diff < 0:
        return f"↓ {abs(diff)}"
    return "—"


def ranking_dicts(
    ratings: List[PlayerRating],
    kind: str,
    official_only: bool = False,
    previous: Optional[Dict[str, Dict[str, PreviousEntry]]] = None,
) -> List[Dict[str, Any]]:
    values = [r for r in ratings if rating_for_kind(r, kind) is not None and (qualification_for_kind(r, kind) or not official_only)]
    values.sort(key=lambda r: rating_for_kind(r, kind) or 0, reverse=True)

    prev_for_kind = previous.get(kind, {}) if previous else {}
    rows: List[Dict[str, Any]] = []

    for idx, r in enumerate(values, start=1):
        current_rating = rating_for_kind(r, kind)
        prev = prev_for_kind.get(normalize_name(r.name))
        previous_rank = prev.rank if prev else None
        previous_rating = prev.rating if prev else None
        rating_change = (round(current_rating) - previous_rating) if (current_rating is not None and previous_rating is not None) else None

        rows.append({
            "Rank": idx,
            "Movement": movement_display(idx, previous_rank) if previous else "",
            "Player": r.name,
            "Team": r.team,
            "Rating": round(current_rating) if current_rating is not None else "",
            "Previous Rank": previous_rank if previous_rank is not None else "",
            "Previous Rating": round(previous_rating) if previous_rating is not None else "",
            "Rating Change": signed_int_display(rating_change),
            "Status": "Official" if qualification_for_kind(r, kind) else "Provisional",
            "Category": KIND_LABELS[kind],
        })

    return rows


def ranking_rows(ratings: List[PlayerRating], kind: str, official_only: bool = False) -> List[Tuple[int, str, str, str]]:
    """Backward-compatible simpler ranking rows."""
    rows = ranking_dicts(ratings, kind, official_only=official_only, previous=None)
    return [(row["Rank"], row["Player"], str(row["Rating"]), row["Status"]) for row in rows]


def team_ranking_dicts(
    ratings: List[PlayerRating],
    kind: str,
    official_only: bool = False,
    previous: Optional[Dict[str, Dict[str, PreviousEntry]]] = None,
) -> List[Dict[str, Any]]:
    overall_rows = ranking_dicts(ratings, kind, official_only=official_only, previous=previous)
    team_counters: Dict[str, int] = {}
    team_rows: List[Dict[str, Any]] = []

    for row in overall_rows:
        team = str(row["Team"])
        team_counters[team] = team_counters.get(team, 0) + 1
        team_row = {
            "Team": team,
            "Category": row["Category"],
            "Team Rank": team_counters[team],
            "Overall Rank": row["Rank"],
            "Movement": row["Movement"],
            "Player": row["Player"],
            "Rating": row["Rating"],
            "Previous Rating": row["Previous Rating"],
            "Rating Change": row["Rating Change"],
            "Status": row["Status"],
        }
        team_rows.append(team_row)

    team_rows.sort(key=lambda x: (str(x["Team"]), str(x["Category"]), int(x["Team Rank"])))
    return team_rows


# -----------------------------
# Weekly report
# -----------------------------

def rank_movement_amount(row: Dict[str, Any]) -> Optional[int]:
    previous_rank = row.get("Previous Rank")
    if previous_rank == "" or previous_rank is None:
        return None
    return int(previous_rank) - int(row["Rank"])


def rating_change_amount(row: Dict[str, Any]) -> Optional[int]:
    value = str(row.get("Rating Change", "")).strip()
    if value == "":
        return None
    try:
        return int(value.replace("+", ""))
    except Exception:
        return None


def weekly_report_rows(
    ratings: List[PlayerRating],
    previous: Optional[Dict[str, Dict[str, PreviousEntry]]],
    official_only: bool = False,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    report: List[Dict[str, Any]] = []

    for kind in ["batting", "bowling", "all_rounder"]:
        rows = ranking_dicts(ratings, kind, official_only=official_only, previous=previous)
        category = KIND_LABELS[kind]

        new_entries = [r for r in rows if r.get("Previous Rank") == ""]
        movers = []
        for r in rows:
            amount = rank_movement_amount(r)
            if amount is not None:
                item = dict(r)
                item["Rank Movement Amount"] = amount
                movers.append(item)

        climbers = sorted([r for r in movers if r["Rank Movement Amount"] > 0], key=lambda x: (x["Rank Movement Amount"], rating_change_amount(x) or 0), reverse=True)[:limit]
        fallers = sorted([r for r in movers if r["Rank Movement Amount"] < 0], key=lambda x: (x["Rank Movement Amount"], rating_change_amount(x) or 0))[:limit]

        changed = []
        for r in rows:
            amount = rating_change_amount(r)
            if amount is not None:
                item = dict(r)
                item["Rating Change Amount"] = amount
                changed.append(item)
        rating_gains = sorted([r for r in changed if r["Rating Change Amount"] > 0], key=lambda x: x["Rating Change Amount"], reverse=True)[:limit]

        sections = [
            ("Top Climbers", climbers),
            ("Top Fallers", fallers),
            ("Top Rating Gains", rating_gains),
            ("New Entries", new_entries[:limit]),
        ]

        for section, items in sections:
            for item in items:
                report.append({
                    "Category": category,
                    "Report Section": section,
                    "Player": item["Player"],
                    "Team": item["Team"],
                    "Current Rank": item["Rank"],
                    "Previous Rank": item["Previous Rank"],
                    "Movement": item["Movement"],
                    "Current Rating": item["Rating"],
                    "Previous Rating": item["Previous Rating"],
                    "Rating Change": item["Rating Change"],
                    "Status": item["Status"],
                })

    return report


# -----------------------------
# Writers
# -----------------------------

def write_side_by_side_rankings(
    ratings: List[PlayerRating],
    output_path: str | Path,
    official_only: bool = False,
    previous: Optional[Dict[str, Dict[str, PreviousEntry]]] = None,
) -> None:
    category_rows = [
        ranking_dicts(ratings, "batting", official_only=official_only, previous=previous),
        ranking_dicts(ratings, "bowling", official_only=official_only, previous=previous),
        ranking_dicts(ratings, "all_rounder", official_only=official_only, previous=previous),
    ]

    columns = ["Rank", "Movement", "Player", "Team", "Rating", "Previous Rating", "Rating Change", "Status"]
    max_len = max(len(rows) for rows in category_rows) if category_rows else 0

    title_row: List[str] = []
    header_row: List[str] = []
    for idx, kind in enumerate(["batting", "bowling", "all_rounder"]):
        title_row.extend([KIND_TITLES[kind]] + [""] * (len(columns) - 1))
        header_row.extend(columns)
        if idx < 2:
            title_row.append("")
            header_row.append("")

    out_rows: List[List[str]] = [title_row, header_row]
    for i in range(max_len):
        out_row: List[str] = []
        for category_idx, rows in enumerate(category_rows):
            if i < len(rows):
                row = rows[i]
                out_row.extend([str(row.get(col, "")) for col in columns])
            else:
                out_row.extend([""] * len(columns))
            if category_idx < 2:
                out_row.append("")
        out_rows.append(out_row)

    with Path(output_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(out_rows)


def write_details(ratings: List[PlayerRating], output_path: str | Path) -> None:
    fieldnames = list(asdict(ratings[0]).keys()) if ratings else []
    with Path(output_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in ratings:
            row = asdict(r)
            for key in [
                "batting_rating", "bowling_rating", "all_rounder_rating",
                "batting_recent_form", "bowling_recent_form", "batting_career_score",
                "bowling_career_score", "achievement_score_batting", "achievement_score_bowling",
            ]:
                if row[key] is not None:
                    row[key] = round(row[key], 3)
            writer.writerow(row)


def write_weekly_report(report_rows: List[Dict[str, Any]], output_path: str | Path) -> None:
    fieldnames = [
        "Category", "Report Section", "Player", "Team", "Current Rank", "Previous Rank",
        "Movement", "Current Rating", "Previous Rating", "Rating Change", "Status",
    ]
    with Path(output_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)


def write_team_rankings(team_rows: List[Dict[str, Any]], output_path: str | Path) -> None:
    fieldnames = [
        "Team", "Category", "Team Rank", "Overall Rank", "Movement", "Player",
        "Rating", "Previous Rating", "Rating Change", "Status",
    ]
    with Path(output_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(team_rows)


# -----------------------------
# CLI
# -----------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate HCCL player rankings from the HCCL stats CSV.")
    parser.add_argument("stats_csv", help="Path to HCCL Stats.csv")
    parser.add_argument("--previous-rankings", default=None, help="Optional path to previous HCCL rankings CSV for movement columns.")
    parser.add_argument("--official-only", action="store_true", help="Only include officially qualified players in ranking outputs.")
    parser.add_argument("--rankings-output", default="HCCL_Rankings_Updated.csv")
    parser.add_argument("--details-output", default="HCCL_Rating_Details.csv")
    parser.add_argument("--weekly-report-output", default="HCCL_Weekly_Report.csv")
    parser.add_argument("--team-rankings-output", default="HCCL_Team_Rankings.csv")
    args = parser.parse_args()

    players = read_stats_csv(args.stats_csv)
    ratings, benchmarks = calculate_ratings(players)

    previous = parse_previous_rankings(args.previous_rankings) if args.previous_rankings else None
    report = weekly_report_rows(ratings, previous, official_only=args.official_only) if previous else []
    team_rows = []
    for kind in ["batting", "bowling", "all_rounder"]:
        team_rows.extend(team_ranking_dicts(ratings, kind, official_only=args.official_only, previous=previous))

    write_side_by_side_rankings(ratings, args.rankings_output, official_only=args.official_only, previous=previous)
    write_details(ratings, args.details_output)
    write_weekly_report(report, args.weekly_report_output)
    write_team_rankings(team_rows, args.team_rankings_output)

    print("Calculated HCCL rankings successfully.")
    print(f"Players loaded: {len(players)}")
    print("Benchmarks:")
    for key, value in benchmarks.items():
        print(f"  {key}: {value}")
    if previous:
        print("Previous rankings loaded: yes")
    else:
        print("Previous rankings loaded: no - movement columns will be blank")
    print(f"Rankings output: {args.rankings_output}")
    print(f"Details output: {args.details_output}")
    print(f"Weekly report output: {args.weekly_report_output}")
    print(f"Team rankings output: {args.team_rankings_output}")


if __name__ == "__main__":
    main()

# -----------------------------
# Formula audit helpers for Streamlit dashboard
# -----------------------------

def _round2(value: object) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _safe_div(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator else 0.0


def _recent_line_items(recent_text: str, kind: str) -> List[Dict[str, Any]]:
    """Return match-by-match recent-form audit rows."""
    rows: List[Dict[str, Any]] = []
    lines = split_recent_lines(recent_text)
    for i, line in enumerate(lines[:5], start=1):
        if kind == "batting":
            dnb = "DNB" in line.upper()
            runs_match = re.search(r"(\d+)\s*runs?", line, flags=re.IGNORECASE)
            sr_match = re.search(r"([0-9.]+)\s*SR", line, flags=re.IGNORECASE)
            runs = int(runs_match.group(1)) if runs_match else 0
            sr = float(sr_match.group(1)) if sr_match else 0.0
            run_pts = 0 if dnb else runs_points(runs)
            sr_pts = 0 if dnb else batting_sr_bonus(sr)
            highest_pts = 20 if is_yes(line, "Highest scorer") else 0
            not_out_pts = 5 if is_yes(line, "Not out") else 0
            potm_pts = 20 if is_yes(line, "POTM") else 0
            total = run_pts + sr_pts + highest_pts + not_out_pts + potm_pts
            rows.append({
                "Match": i,
                "Raw recent line": line,
                "Runs": runs if not dnb else "DNB",
                "SR/Eco": sr if not dnb else "DNB",
                "Base points": run_pts,
                "SR/Eco bonus": sr_pts,
                "Highest scorer / POTM bonus": highest_pts + potm_pts,
                "Not out bonus": not_out_pts,
                "Total points": total,
            })
        else:
            dnb = "DNB" in line.upper()
            wicket_match = re.search(r"(\d+)\s*Wickets?", line, flags=re.IGNORECASE)
            eco_match = re.search(r"([0-9.]+)\s*Eco", line, flags=re.IGNORECASE)
            wickets = int(wicket_match.group(1)) if wicket_match else 0
            eco = float(eco_match.group(1)) if eco_match else 0.0
            wicket_pts = 0 if dnb else wicket_points(wickets)
            eco_pts = 0 if dnb else economy_bonus(eco)
            potm_pts = 20 if is_yes(line, "POTM") else 0
            total = wicket_pts + eco_pts + potm_pts
            rows.append({
                "Match": i,
                "Raw recent line": line,
                "Wickets": wickets if not dnb else "DNB",
                "SR/Eco": eco if not dnb else "DNB",
                "Base points": wicket_pts,
                "SR/Eco bonus": eco_pts,
                "Highest scorer / POTM bonus": potm_pts,
                "Not out bonus": 0,
                "Total points": total,
            })

    for i in range(len(rows) + 1, 6):
        rows.append({
            "Match": i,
            "Raw recent line": "Missing / treated as 0",
            "Runs" if kind == "batting" else "Wickets": 0,
            "SR/Eco": 0,
            "Base points": 0,
            "SR/Eco bonus": 0,
            "Highest scorer / POTM bonus": 0,
            "Not out bonus": 0,
            "Total points": 0,
        })
    return rows


def calculate_formula_audit(players: List[Dict[str, str]], player_name: str) -> Dict[str, Any]:
    """Return a line-by-line calculation audit for a selected player."""
    selected: Optional[Dict[str, str]] = None
    target = normalize_name(player_name)
    for p in players:
        if normalize_name(p.get("NAME", "")) == target:
            selected = p
            break
    if selected is None:
        raise ValueError(f"Player not found: {player_name}")

    ratings, benchmarks = calculate_ratings(players)
    rating_by_name = {normalize_name(r.name): r for r in ratings}
    r = rating_by_name.get(target)
    if r is None:
        raise ValueError(f"Could not calculate rating for: {player_name}")

    runs = to_float(selected["RUNS"])
    innings = to_int(selected["Innings"])
    balls_faced = to_float(selected["Balls Faced"])
    bat_avg = to_float(selected["Bat AVG"])
    sr = to_float(selected["SR"])
    rap = to_float(selected["RAP"])
    wickets = to_float(selected["WICKETS"])
    balls_bowled = to_float(selected["Balls Bowled"])
    bowl_avg = to_float(selected["Bowl AVG"])
    eco = to_float(selected["ECO"])
    bsr = to_float(selected["BSR"])
    bap = to_float(selected["BAP"])

    batting_recent_form, batting_recent_points = parse_batting_recent(selected["Bat Recent 5 Matches"])
    bowling_recent_form, bowling_recent_points = parse_bowling_recent(selected["Bowl Recent 5 Matches"])

    runs_score = _safe_div(runs, benchmarks["highest_runs"]) * 100
    bat_avg_score = _safe_div(bat_avg, benchmarks["highest_bat_avg"]) * 100
    sr_score = _safe_div(sr, benchmarks["highest_sr"]) * 100
    batting_career = (runs_score * 0.50) + (bat_avg_score * 0.30) + (sr_score * 0.20)
    batting_achievement = _safe_div(rap, benchmarks["highest_rap"]) * 100
    exp = experience_score(innings)
    batting_rating = 100 + (batting_career * 5) + (batting_recent_form * 3) + batting_achievement + exp if (runs > 0 or innings > 0) else None

    wickets_score = _safe_div(wickets, benchmarks["highest_wickets"]) * 100
    bowling_avg_score = _safe_div(benchmarks["best_bowl_avg"], bowl_avg) * 100 if bowl_avg else 0
    eco_score = _safe_div(benchmarks["best_eco"], eco) * 100 if eco else 0
    bsr_score = _safe_div(benchmarks["best_bsr"], bsr) * 100 if bsr else 0
    bowling_career = (wickets_score * 0.60) + (bowling_avg_score * 0.20) + (eco_score * 0.10) + (bsr_score * 0.10)
    bowling_achievement = _safe_div(bap, benchmarks["highest_bap"]) * 100
    bowling_rating = 100 + (bowling_career * 5) + (bowling_recent_form * 3) + (bowling_achievement * 2) if wickets > 0 else None

    ar_rating = math.sqrt(batting_rating * bowling_rating) if batting_rating is not None and bowling_rating is not None else None

    batting_steps = [
        {"Step": "Runs Score", "Formula": "Player Runs / Highest Runs × 100", "Values Used": f"{runs} / {benchmarks['highest_runs']} × 100", "Result": _round2(runs_score)},
        {"Step": "Average Score", "Formula": "Player Bat AVG / Highest Bat AVG × 100", "Values Used": f"{bat_avg} / {benchmarks['highest_bat_avg']} × 100", "Result": _round2(bat_avg_score)},
        {"Step": "Strike Rate Score", "Formula": "Player SR / Highest SR × 100", "Values Used": f"{sr} / {benchmarks['highest_sr']} × 100", "Result": _round2(sr_score)},
        {"Step": "Career Score", "Formula": "Runs Score×0.50 + AVG Score×0.30 + SR Score×0.20", "Values Used": f"{_round2(runs_score)}×0.50 + {_round2(bat_avg_score)}×0.30 + {_round2(sr_score)}×0.20", "Result": _round2(batting_career)},
        {"Step": "Recent Form", "Formula": "Sum last 5 match points / 5", "Values Used": f"{[int(x) for x in batting_recent_points]} / 5", "Result": _round2(batting_recent_form)},
        {"Step": "Achievement Score", "Formula": "Player RAP / Highest RAP × 100", "Values Used": f"{rap} / {benchmarks['highest_rap']} × 100", "Result": _round2(batting_achievement)},
        {"Step": "Experience Score", "Formula": "Based on innings bands", "Values Used": f"{innings} innings", "Result": exp},
        {"Step": "Final Batting Rating", "Formula": "100 + Career×5 + Recent×3 + Achievement + Experience", "Values Used": f"100 + {_round2(batting_career)}×5 + {_round2(batting_recent_form)}×3 + {_round2(batting_achievement)} + {exp}", "Result": round(batting_rating) if batting_rating is not None else ""},
    ]

    bowling_steps = [
        {"Step": "Wickets Score", "Formula": "Player Wickets / Highest Wickets × 100", "Values Used": f"{wickets} / {benchmarks['highest_wickets']} × 100", "Result": _round2(wickets_score)},
        {"Step": "Bowling AVG Score", "Formula": "Best Bowling AVG / Player Bowling AVG × 100", "Values Used": f"{benchmarks['best_bowl_avg']} / {bowl_avg} × 100", "Result": _round2(bowling_avg_score)},
        {"Step": "Economy Score", "Formula": "Best Economy / Player Economy × 100", "Values Used": f"{benchmarks['best_eco']} / {eco} × 100", "Result": _round2(eco_score)},
        {"Step": "BSR Score", "Formula": "Best BSR / Player BSR × 100", "Values Used": f"{benchmarks['best_bsr']} / {bsr} × 100", "Result": _round2(bsr_score)},
        {"Step": "Career Score", "Formula": "Wickets×0.60 + AVG×0.20 + Economy×0.10 + BSR×0.10", "Values Used": f"{_round2(wickets_score)}×0.60 + {_round2(bowling_avg_score)}×0.20 + {_round2(eco_score)}×0.10 + {_round2(bsr_score)}×0.10", "Result": _round2(bowling_career)},
        {"Step": "Recent Form", "Formula": "Sum last 5 team match points / 5", "Values Used": f"{[int(x) for x in bowling_recent_points]} / 5", "Result": _round2(bowling_recent_form)},
        {"Step": "Achievement Score", "Formula": "Player BAP / Highest BAP × 100", "Values Used": f"{bap} / {benchmarks['highest_bap']} × 100", "Result": _round2(bowling_achievement)},
        {"Step": "Final Bowling Rating", "Formula": "100 + Career×5 + Recent×3 + Achievement×2", "Values Used": f"100 + {_round2(bowling_career)}×5 + {_round2(bowling_recent_form)}×3 + {_round2(bowling_achievement)}×2", "Result": round(bowling_rating) if bowling_rating is not None else ""},
    ]

    all_rounder_steps = [{
        "Step": "Final All-Rounder Rating",
        "Formula": "√(Batting Rating × Bowling Rating)",
        "Values Used": f"√({round(batting_rating) if batting_rating is not None else ''} × {round(bowling_rating) if bowling_rating is not None else ''})",
        "Result": round(ar_rating) if ar_rating is not None else "",
    }]

    raw_stats = {
        "ID": selected.get("ID", ""),
        "Player": selected.get("NAME", ""),
        "Team": selected.get("TEAM", ""),
        "Innings": innings,
        "Runs": runs,
        "Balls Faced": balls_faced,
        "Bat AVG": bat_avg,
        "SR": sr,
        "RAP": rap,
        "Wickets": wickets,
        "Balls Bowled": balls_bowled,
        "Bowl AVG": bowl_avg,
        "ECO": eco,
        "BSR": bsr,
        "BAP": bap,
        "Batting Qualified": "Yes" if r.batting_qualified else "No",
        "Bowling Qualified": "Yes" if r.bowling_qualified else "No",
        "All-Rounder Qualified": "Yes" if r.all_rounder_qualified else "No",
    }

    return {
        "player": raw_stats,
        "benchmarks": benchmarks,
        "ratings": {
            "Batting Rating": round(batting_rating) if batting_rating is not None else "",
            "Bowling Rating": round(bowling_rating) if bowling_rating is not None else "",
            "All-Rounder Rating": round(ar_rating) if ar_rating is not None else "",
        },
        "batting_steps": batting_steps,
        "bowling_steps": bowling_steps,
        "all_rounder_steps": all_rounder_steps,
        "batting_recent_rows": _recent_line_items(selected["Bat Recent 5 Matches"], "batting"),
        "bowling_recent_rows": _recent_line_items(selected["Bowl Recent 5 Matches"], "bowling"),
    }
