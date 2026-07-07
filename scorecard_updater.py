"""HCCL Scorecard PDF Updater

Adds a safe, review-first workflow for updating the weekly HCCL Stats CSV from
STUMPS scorecard PDFs.

Important assumptions:
- Scorecard PDF is the STUMPS match report format used by HCCL.
- The stats CSV may include either "Stumps Name" or "Scorecard Username" to match
  PDF names faster. If both are missing, player NAME is used as fallback.
- If a scorecard player is not found in the CSV, the updater automatically adds
  a new player row with the scorecard name and starts their stats from this match.
- The updater appends helper columns for more accurate future updates:
  "Bat Dismissals" and "Bowl Runs Conceded". The rating engine ignores these
  extra columns, but the updater uses them to keep averages/economy accurate.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

# Canonical columns used internally. The app now supports both old HCCL Stats.csv
# and the new layout with a Stumps Name column inserted after NAME.
BASE_COLUMNS = [
    "ID", "NAME", "TEAM", "Innings", "RUNS", "Balls Faced", "Bat AVG", "SR",
    "30s", "50s", "0s", "POTMs", "RAP", "Bat Recent 5 Matches",
    "WICKETS", "Balls Bowled", "Bowl AVG", "ECO", "3Fers", "4Fers", "BSR", "BAP",
    "Bowl Recent 5 Matches", "Blank",
]

USERNAME_COL = "Scorecard Username"
USERNAME_ALIASES = ["Scorecard Username", "Stumps Name", "STUMPS Name", "Scorecard Name", "Stumps Username"]
BAT_DISMISSALS_COL = "Bat Dismissals"
BOWL_RUNS_CONCEDED_COL = "Bowl Runs Conceded"
HELPER_COLUMNS = [BAT_DISMISSALS_COL, BOWL_RUNS_CONCEDED_COL]


@dataclass
class BatterInnings:
    team: str
    scorecard_name: str
    runs: int
    balls: int
    fours: int
    sixes: int
    strike_rate: float
    not_out: bool
    dismissal: str


@dataclass
class BowlerFigures:
    bowling_to_team: str
    scorecard_name: str
    overs: str
    balls: int
    maidens: int
    runs_conceded: int
    wickets: int
    economy: float


@dataclass
class MatchScorecard:
    match_id: str
    player_of_match: str
    teams: List[str]
    batting: List[BatterInnings]
    bowling: List[BowlerFigures]


def _clean_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\((?:C|WK|c|wk)\)\s*", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def normalize_name(value: Any) -> str:
    text = _clean_name(value).lower()
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def to_int(value: Any) -> int:
    try:
        text = str(value or "").strip()
        if text == "" or text.lower() == "nan":
            return 0
        return int(float(text))
    except Exception:
        return 0


def to_float(value: Any) -> float:
    try:
        text = str(value or "").strip()
        if text == "" or text.lower() == "nan":
            return 0.0
        return float(text)
    except Exception:
        return 0.0


def fmt_number(value: float, decimals: int = 1) -> str:
    if abs(value - round(value)) < 0.000001:
        return str(int(round(value)))
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def overs_to_balls(overs: Any) -> int:
    text = str(overs or "0").strip()
    if not text:
        return 0
    if "." not in text:
        return int(float(text)) * 6
    whole, balls = text.split(".", 1)
    return int(whole or 0) * 6 + int(balls or 0)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Add pymupdf to requirements.txt and redeploy.")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = []
    for page in doc:
        texts.append(page.get_text("text"))
    return "\n".join(texts)


def _extract_potm(lines: List[str]) -> str:
    for i, line in enumerate(lines):
        if line.strip().lower() == "player of the match" and i + 1 < len(lines):
            return _clean_name(lines[i + 1])
    match = re.search(r"Player Of The Match\s+(.+?)(?:\n|$)", "\n".join(lines), re.I)
    return _clean_name(match.group(1)) if match else ""


def _extract_match_id(lines: List[str]) -> str:
    for i, line in enumerate(lines):
        if line.strip().lower() == "match id" and i + 1 < len(lines):
            return lines[i + 1].strip()
    match = re.search(r"Match ID\s+([A-Za-z0-9_-]+)", "\n".join(lines), re.I)
    return match.group(1).strip() if match else ""


def _parse_batter_line(line: str, team: str) -> Optional[BatterInnings]:
    # Example: Kalana Thenu (C) b Thulanja 29 11 0 2 263.6
    m = re.match(r"^(?P<left>.+?)\s+(?P<runs>\d+)\s+(?P<balls>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<sr>[0-9.]+)$", line.strip())
    if not m:
        return None

    left = m.group("left").strip()
    not_out = "not out" in left.lower()
    dismissal = ""
    name_part = left

    # Find common dismissal markers. Keep text before the marker as player name.
    marker = re.search(r"\s+(not out|retired hurt|retired out|b\s+|c\s+|lbw\s+|st\s+|run out|hit wicket).*$", left, flags=re.I)
    if marker:
        name_part = left[: marker.start()].strip()
        dismissal = left[marker.start():].strip()
    elif " retired" in left.lower():
        parts = re.split(r"\s+retired", left, maxsplit=1, flags=re.I)
        name_part = parts[0].strip()
        dismissal = "retired"

    return BatterInnings(
        team=team,
        scorecard_name=_clean_name(name_part),
        runs=int(m.group("runs")),
        balls=int(m.group("balls")),
        fours=int(m.group("fours")),
        sixes=int(m.group("sixes")),
        strike_rate=float(m.group("sr")),
        not_out=not_out,
        dismissal=dismissal,
    )


def _parse_bowler_line(line: str, batting_team: str) -> Optional[BowlerFigures]:
    # Example: Kalana Thenu (C) 2.0 0 28 4 14.0 6 1 3 0 0
    m = re.match(
        r"^(?P<name>.+?)\s+(?P<overs>\d+(?:\.\d+)?)\s+(?P<maidens>\d+)\s+(?P<runs>\d+)\s+(?P<wickets>\d+)\s+(?P<eco>[0-9.]+)\s+(?P<dots>\d+)\s+(?P<fours>\d+)\s+(?P<sixes>\d+)\s+(?P<wd>\d+)\s+(?P<nb>\d+)$",
        line.strip(),
    )
    if not m:
        return None
    return BowlerFigures(
        bowling_to_team=batting_team,
        scorecard_name=_clean_name(m.group("name")),
        overs=m.group("overs"),
        balls=overs_to_balls(m.group("overs")),
        maidens=int(m.group("maidens")),
        runs_conceded=int(m.group("runs")),
        wickets=int(m.group("wickets")),
        economy=float(m.group("eco")),
    )


def parse_scorecard_text(text: str) -> MatchScorecard:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in str(text).splitlines()]
    lines = [ln for ln in lines if ln]

    batting: List[BatterInnings] = []
    bowling: List[BowlerFigures] = []
    teams: List[str] = []

    i = 0
    while i < len(lines):
        if re.match(r"^(1st|2nd) Innings Scorecard$", lines[i], flags=re.I):
            i += 1
            if i >= len(lines):
                break

            team_line = lines[i]
            team_match = re.match(r"^(?P<team>.+?)\s+R\s+B\s+4s\s+6s\s+SR$", team_line, flags=re.I)
            if not team_match:
                i += 1
                continue
            batting_team = team_match.group("team").strip()
            if batting_team not in teams:
                teams.append(batting_team)
            i += 1

            while i < len(lines):
                low = lines[i].lower()
                if low.startswith("extras") or low.startswith("total") or low.startswith("fall of wickets"):
                    break
                row = _parse_batter_line(lines[i], batting_team)
                if row:
                    batting.append(row)
                i += 1

            # Move to the bowling header for this innings.
            while i < len(lines) and not re.match(r"^Bowler\s+O\s+M\s+R\s+W\s+Eco", lines[i], flags=re.I):
                if re.match(r"^(1st|2nd) Innings Scorecard$", lines[i], flags=re.I):
                    break
                i += 1

            if i < len(lines) and re.match(r"^Bowler\s+O\s+M\s+R\s+W\s+Eco", lines[i], flags=re.I):
                i += 1
                while i < len(lines) and not re.match(r"^(1st|2nd) Innings Scorecard$", lines[i], flags=re.I):
                    row = _parse_bowler_line(lines[i], batting_team)
                    if row:
                        bowling.append(row)
                    # Stop if footer/next pages start repeating non-scorecard content.
                    if lines[i].lower().startswith("download ") or lines[i].lower() == "over comparison":
                        break
                    i += 1
            continue
        i += 1

    return MatchScorecard(
        match_id=_extract_match_id(lines),
        player_of_match=_extract_potm(lines),
        teams=teams,
        batting=batting,
        bowling=bowling,
    )


def parse_scorecard_pdf_bytes(pdf_bytes: bytes) -> MatchScorecard:
    text = extract_pdf_text(pdf_bytes)
    return parse_scorecard_text(text)


def _decode_csv_bytes(stats_csv_bytes: bytes) -> str:
    """Decode CSV files saved by Excel/Google Sheets on different Windows setups."""
    last_error: Optional[Exception] = None
    for enc in ("utf-8-sig", "utf-8", "mac_roman", "cp1252", "latin-1"):
        try:
            return stats_csv_bytes.decode(enc)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Could not decode stats CSV. Last error: {last_error}")


def _read_stats_rows(stats_csv_bytes: bytes) -> Tuple[List[str], List[List[str]]]:
    text = _decode_csv_bytes(stats_csv_bytes)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("Stats CSV is empty.")
    return rows[0], rows[1:]


def _header_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\ufeff", "").strip().lower())


def _find_header(header: List[str], aliases: Iterable[str]) -> Optional[int]:
    wanted = {_header_key(a) for a in aliases}
    for i, h in enumerate(header):
        if _header_key(h) in wanted:
            return i
    return None


def _find_all_headers(header: List[str], aliases: Iterable[str]) -> List[int]:
    wanted = {_header_key(a) for a in aliases}
    return [i for i, h in enumerate(header) if _header_key(h) in wanted]


def _require_idx(idx: Dict[str, Optional[int]], name: str) -> int:
    value = idx.get(name)
    if value is None:
        raise ValueError(f"Required column not found in stats CSV: {name}")
    return value


def _detect_stats_indexes(header: List[str]) -> Dict[str, int]:
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
        USERNAME_COL: _find_header(header, USERNAME_ALIASES),
        BAT_DISMISSALS_COL: _find_header(header, [BAT_DISMISSALS_COL]),
        BOWL_RUNS_CONCEDED_COL: _find_header(header, [BOWL_RUNS_CONCEDED_COL]),
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

    # Required columns for updating. Username is optional and falls back to NAME.
    required = [
        "ID", "NAME", "TEAM", "Innings", "RUNS", "Balls Faced", "Bat AVG", "SR", "30s", "50s", "0s",
        "POTMs", "RAP", "Bat Recent 5 Matches", "WICKETS", "Balls Bowled", "Bowl AVG", "ECO", "3Fers",
        "4Fers", "BSR", "BAP", "Bowl Recent 5 Matches",
    ]
    return {name: _require_idx(idx, name) for name in required if name in idx} | {
        name: pos for name, pos in idx.items() if pos is not None and name not in required
    }


def _ensure_columns(header: List[str], rows: List[List[str]]) -> Tuple[List[str], List[List[str]], Dict[str, int]]:
    header = list(header)
    rows = [list(r) for r in rows]

    def add_column_if_missing(column_name: str) -> None:
        if _find_header(header, [column_name]) is None:
            header.append(column_name)

    # If neither Stumps Name nor Scorecard Username exists, add Scorecard Username at the end.
    if _find_header(header, USERNAME_ALIASES) is None:
        header.append(USERNAME_COL)

    for col in HELPER_COLUMNS:
        add_column_if_missing(col)

    max_len = len(header)
    rows = [r + [""] * (max_len - len(r)) for r in rows if any(str(c).strip() for c in r)]
    rows = [r[:max_len] if len(r) > max_len else r for r in rows]

    idx = _detect_stats_indexes(header)
    return header, rows, idx


def _csv_bytes(header: List[str], rows: List[List[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _split_aliases(value: str) -> List[str]:
    parts = re.split(r"[,;/|]+", str(value or ""))
    return [p.strip() for p in parts if p.strip()]


def _build_player_index(rows: List[List[str]], idx: Dict[str, int]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for row_idx, row in enumerate(rows):
        candidates = []
        username = row[idx[USERNAME_COL]].strip() if idx[USERNAME_COL] < len(row) else ""
        if username:
            candidates.extend(_split_aliases(username))
        candidates.append(row[idx["NAME"]])

        for candidate in candidates:
            key = normalize_name(candidate)
            if key and key not in mapping:
                mapping[key] = row_idx
    return mapping


def _get_row_number(value: Any) -> str:
    if isinstance(value, float):
        return fmt_number(value)
    return str(value)


def _set_int(row: List[str], pos: int, value: int) -> None:
    row[pos] = str(int(value))


def _set_float(row: List[str], pos: int, value: float, decimals: int = 1) -> None:
    row[pos] = fmt_number(value, decimals=decimals)


def _prepend_recent(existing: str, new_line: str, limit: int = 5) -> str:
    cleaned: List[str] = []
    for raw in str(existing or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\d+\.\s*", "", line)
        cleaned.append(line)
    lines = [new_line] + cleaned[: max(0, limit - 1)]
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))


def _init_helper_values(row: List[str], idx: Dict[str, int]) -> None:
    if not row[idx[BAT_DISMISSALS_COL]].strip():
        runs = to_float(row[idx["RUNS"]])
        avg = to_float(row[idx["Bat AVG"]])
        dismissals = int(round(runs / avg)) if avg > 0 else 0
        row[idx[BAT_DISMISSALS_COL]] = str(max(dismissals, 0))

    if not row[idx[BOWL_RUNS_CONCEDED_COL]].strip():
        balls = to_float(row[idx["Balls Bowled"]])
        eco = to_float(row[idx["ECO"]])
        runs_conceded = int(round(eco * balls / 6)) if balls > 0 and eco > 0 else 0
        row[idx[BOWL_RUNS_CONCEDED_COL]] = str(max(runs_conceded, 0))


def _recalculate_batting(row: List[str], idx: Dict[str, int]) -> None:
    runs = to_float(row[idx["RUNS"]])
    balls = to_float(row[idx["Balls Faced"]])
    dismissals = to_float(row[idx[BAT_DISMISSALS_COL]])
    avg = (runs / dismissals) if dismissals > 0 else (runs if runs > 0 else 0)
    sr = (runs / balls * 100) if balls > 0 else 0
    _set_float(row, idx["Bat AVG"], avg, decimals=1)
    _set_float(row, idx["SR"], sr, decimals=1)

    rap = (to_int(row[idx["30s"]]) * 15) + (to_int(row[idx["50s"]]) * 35) + (to_int(row[idx["POTMs"]]) * 50)
    _set_int(row, idx["RAP"], rap)


def _recalculate_bowling(row: List[str], idx: Dict[str, int]) -> None:
    wickets = to_float(row[idx["WICKETS"]])
    balls = to_float(row[idx["Balls Bowled"]])
    runs_conceded = to_float(row[idx[BOWL_RUNS_CONCEDED_COL]])
    bowl_avg = (runs_conceded / wickets) if wickets > 0 else 0
    eco = (runs_conceded * 6 / balls) if balls > 0 else 0
    bsr = (balls / wickets) if wickets > 0 else 0
    _set_float(row, idx["Bowl AVG"], bowl_avg, decimals=1)
    _set_float(row, idx["ECO"], eco, decimals=1)
    _set_float(row, idx["BSR"], bsr, decimals=2)

    bap = (to_int(row[idx["3Fers"]]) * 15) + (to_int(row[idx["4Fers"]]) * 35) + (to_int(row[idx["POTMs"]]) * 50)
    _set_int(row, idx["BAP"], bap)


def _next_player_id(rows: List[List[str]], idx: Dict[str, int]) -> str:
    max_id = 0
    id_pos = idx.get("ID")
    if id_pos is not None:
        for row in rows:
            raw = str(row[id_pos] if id_pos < len(row) else "").strip()
            m = re.search(r"(\d+)$", raw)
            if m:
                max_id = max(max_id, int(m.group(1)))
    return f"P{max_id + 1:03d}"


def _infer_bowling_team(batting_team: str, teams: List[str]) -> str:
    batting_key = normalize_name(batting_team)
    for team in teams:
        if normalize_name(team) != batting_key:
            return team
    return ""


def _set_default_new_player_values(row: List[str], idx: Dict[str, int]) -> None:
    # Keep text fields blank unless known. Numeric stats should start from zero.
    numeric_cols = [
        "Innings", "RUNS", "Balls Faced", "Bat AVG", "SR", "30s", "50s", "0s",
        "POTMs", "RAP", "WICKETS", "Balls Bowled", "Bowl AVG", "ECO", "3Fers",
        "4Fers", "BSR", "BAP", BAT_DISMISSALS_COL, BOWL_RUNS_CONCEDED_COL,
    ]
    for col in numeric_cols:
        if col in idx and idx[col] < len(row):
            row[idx[col]] = "0"


def _create_new_player_row(
    header: List[str],
    rows: List[List[str]],
    idx: Dict[str, int],
    scorecard_name: str,
    team: str = "",
) -> Tuple[List[str], int]:
    row = [""] * len(header)
    clean_name = _clean_name(scorecard_name) or "Unknown Player"
    row[idx["ID"]] = _next_player_id(rows, idx)
    row[idx["NAME"]] = clean_name
    row[idx["TEAM"]] = _clean_name(team)
    if USERNAME_COL in idx:
        row[idx[USERNAME_COL]] = clean_name
    _set_default_new_player_values(row, idx)
    rows.append(row)
    return row, len(rows) - 1


def _match_players(match: MatchScorecard) -> List[str]:
    names = []
    seen = set()
    for b in match.batting:
        key = normalize_name(b.scorecard_name)
        if key and key not in seen:
            seen.add(key)
            names.append(b.scorecard_name)
    for bw in match.bowling:
        key = normalize_name(bw.scorecard_name)
        if key and key not in seen:
            seen.add(key)
            names.append(bw.scorecard_name)
    return names




def _snapshot_player_stats(rows: List[List[str]], idx: Dict[str, int]) -> Dict[str, Dict[str, str]]:
    """Take a before/after snapshot of the important visible stats columns."""
    fields = [
        "Innings", "RUNS", "Balls Faced", "Bat AVG", "SR", "30s", "50s", "0s",
        "POTMs", "RAP", "Bat Recent 5 Matches", "WICKETS", "Balls Bowled", "Bowl AVG",
        "ECO", "3Fers", "4Fers", "BSR", "BAP", "Bowl Recent 5 Matches",
    ]
    snapshot: Dict[str, Dict[str, str]] = {}
    for row in rows:
        player_id = str(row[idx["ID"]] if idx["ID"] < len(row) else "").strip()
        if not player_id:
            player_id = normalize_name(row[idx["NAME"]] if idx["NAME"] < len(row) else "")
        if not player_id:
            continue
        snapshot[player_id] = {
            "ID": str(row[idx["ID"]] if idx["ID"] < len(row) else ""),
            "NAME": str(row[idx["NAME"]] if idx["NAME"] < len(row) else ""),
            "TEAM": str(row[idx["TEAM"]] if idx["TEAM"] < len(row) else ""),
        }
        for field in fields:
            if field in idx and idx[field] < len(row):
                snapshot[player_id][field] = str(row[idx[field]])
    return snapshot


def _diff_player_stats(before: Dict[str, Dict[str, str]], after: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    """Return one row per player whose important stats changed."""
    changes: List[Dict[str, str]] = []
    ignored = {"ID", "NAME", "TEAM"}
    for player_id, after_row in after.items():
        before_row = before.get(player_id, {})
        changed_fields = []
        for field, new_value in after_row.items():
            if field in ignored:
                continue
            old_value = before_row.get(field, "")
            if str(old_value) != str(new_value):
                # Keep the preview readable by shortening long recent-form fields.
                if "Recent 5" in field:
                    changed_fields.append(f"{field}: updated")
                else:
                    changed_fields.append(f"{field}: {old_value or 'blank'} → {new_value or 'blank'}")
        if changed_fields or player_id not in before:
            changes.append({
                "ID": after_row.get("ID", ""),
                "Player": after_row.get("NAME", ""),
                "Team": after_row.get("TEAM", ""),
                "Change Summary": "; ".join(changed_fields) if changed_fields else "New player row added",
            })
    return changes

def update_stats_csv_from_scorecard(
    stats_csv_bytes: bytes,
    scorecard_pdf_bytes: bytes,
) -> Dict[str, Any]:
    match = parse_scorecard_pdf_bytes(scorecard_pdf_bytes)
    return update_stats_csv_from_match(stats_csv_bytes, match)


def update_stats_csv_from_match(stats_csv_bytes: bytes, match: MatchScorecard) -> Dict[str, Any]:
    header, rows = _read_stats_rows(stats_csv_bytes)
    header, rows, idx = _ensure_columns(header, rows)

    for row in rows:
        _init_helper_values(row, idx)

    before_snapshot = _snapshot_player_stats(rows, idx)

    player_index = _build_player_index(rows, idx)
    potm_key = normalize_name(match.player_of_match)
    highest_runs = max([b.runs for b in match.batting], default=0)

    batting_updates: List[Dict[str, Any]] = []
    bowling_updates: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, str]] = []
    new_players: List[Dict[str, str]] = []
    matched_row_ids = set()
    bowling_names = {normalize_name(bw.scorecard_name) for bw in match.bowling}

    def find_or_add_row(scorecard_name: str, kind: str, team: str = "") -> Optional[List[str]]:
        key = normalize_name(scorecard_name)
        if not key:
            unmatched.append({"Type": kind, "Scorecard Name": scorecard_name, "Reason": "Blank/invalid scorecard name"})
            return None
        if key in player_index:
            row = rows[player_index[key]]
            matched_row_ids.add(player_index[key])
            return row

        # New scorecard player: automatically add a row to the stats CSV.
        row, row_idx = _create_new_player_row(header, rows, idx, scorecard_name, team)
        player_index[key] = row_idx
        player_index[normalize_name(row[idx["NAME"]])] = row_idx
        if USERNAME_COL in idx:
            player_index[normalize_name(row[idx[USERNAME_COL]])] = row_idx
        matched_row_ids.add(row_idx)
        new_players.append({
            "Scorecard Name": _clean_name(scorecard_name),
            "Added As": row[idx["NAME"]],
            "Team": row[idx["TEAM"]],
            "Reason": f"Not found in CSV during {kind} update",
        })
        return row

    # Batting update.
    for b in match.batting:
        row = find_or_add_row(b.scorecard_name, "Batting", b.team)
        if row is None:
            continue
        is_potm = normalize_name(b.scorecard_name) == potm_key
        is_highest = b.runs == highest_runs and highest_runs > 0

        _set_int(row, idx["Innings"], to_int(row[idx["Innings"]]) + 1)
        _set_int(row, idx["RUNS"], to_int(row[idx["RUNS"]]) + b.runs)
        _set_int(row, idx["Balls Faced"], to_int(row[idx["Balls Faced"]]) + b.balls)
        if not b.not_out:
            _set_int(row, idx[BAT_DISMISSALS_COL], to_int(row[idx[BAT_DISMISSALS_COL]]) + 1)
        if 30 <= b.runs < 50:
            _set_int(row, idx["30s"], to_int(row[idx["30s"]]) + 1)
        if b.runs >= 50:
            _set_int(row, idx["50s"], to_int(row[idx["50s"]]) + 1)
        if b.runs == 0 and not b.not_out and b.balls > 0:
            _set_int(row, idx["0s"], to_int(row[idx["0s"]]) + 1)

        recent_line = (
            f"{b.runs} runs, {fmt_number(b.strike_rate)} SR, "
            f"Highest scorer {'Yes' if is_highest else 'No'}, "
            f"Not out {'Yes' if b.not_out else 'No'}, "
            f"POTM {'Yes' if is_potm else 'No'}"
        )
        row[idx["Bat Recent 5 Matches"]] = _prepend_recent(row[idx["Bat Recent 5 Matches"]], recent_line)
        _recalculate_batting(row, idx)

        batting_updates.append({
            "Scorecard Name": b.scorecard_name,
            "Matched Player": row[idx["NAME"]],
            "Team": row[idx["TEAM"]],
            "Runs": b.runs,
            "Balls": b.balls,
            "Not Out": "Yes" if b.not_out else "No",
            "Highest Scorer": "Yes" if is_highest else "No",
            "POTM": "Yes" if is_potm else "No",
        })

    # Bowling update.
    for bw in match.bowling:
        row = find_or_add_row(bw.scorecard_name, "Bowling", _infer_bowling_team(bw.bowling_to_team, match.teams))
        if row is None:
            continue
        is_potm = normalize_name(bw.scorecard_name) == potm_key
        _set_int(row, idx["WICKETS"], to_int(row[idx["WICKETS"]]) + bw.wickets)
        _set_int(row, idx["Balls Bowled"], to_int(row[idx["Balls Bowled"]]) + bw.balls)
        _set_int(row, idx[BOWL_RUNS_CONCEDED_COL], to_int(row[idx[BOWL_RUNS_CONCEDED_COL]]) + bw.runs_conceded)
        if bw.wickets == 3:
            _set_int(row, idx["3Fers"], to_int(row[idx["3Fers"]]) + 1)
        if bw.wickets >= 4:
            _set_int(row, idx["4Fers"], to_int(row[idx["4Fers"]]) + 1)

        recent_line = f"{bw.wickets} Wickets, {fmt_number(bw.economy)} Eco, POTM {'YES' if is_potm else 'NO'}"
        row[idx["Bowl Recent 5 Matches"]] = _prepend_recent(row[idx["Bowl Recent 5 Matches"]], recent_line)
        _recalculate_bowling(row, idx)

        bowling_updates.append({
            "Scorecard Name": bw.scorecard_name,
            "Matched Player": row[idx["NAME"]],
            "Team": row[idx["TEAM"]],
            "Overs": bw.overs,
            "Runs Conceded": bw.runs_conceded,
            "Wickets": bw.wickets,
            "Economy": bw.economy,
            "POTM": "Yes" if is_potm else "No",
        })

    # Bowl DNB for players in the match who did not bowl.
    for scorecard_name in _match_players(match):
        key = normalize_name(scorecard_name)
        if key in bowling_names:
            continue
        row = find_or_add_row(scorecard_name, "Bowling DNB")
        if row is None:
            continue
        is_potm = key == potm_key
        recent_line = f"DNB, POTM {'YES' if is_potm else 'NO'}"
        row[idx["Bowl Recent 5 Matches"]] = _prepend_recent(row[idx["Bowl Recent 5 Matches"]], recent_line)
        bowling_updates.append({
            "Scorecard Name": scorecard_name,
            "Matched Player": row[idx["NAME"]],
            "Team": row[idx["TEAM"]],
            "Overs": "DNB",
            "Runs Conceded": "",
            "Wickets": "",
            "Economy": "",
            "POTM": "Yes" if is_potm else "No",
        })

    # POTM is one shared career count used by RAP and BAP. Increment once.
    if potm_key in player_index:
        potm_row = rows[player_index[potm_key]]
        _set_int(potm_row, idx["POTMs"], to_int(potm_row[idx["POTMs"]]) + 1)
        _recalculate_batting(potm_row, idx)
        _recalculate_bowling(potm_row, idx)
    elif match.player_of_match:
        potm_row = find_or_add_row(match.player_of_match, "POTM")
        if potm_row is not None:
            _set_int(potm_row, idx["POTMs"], to_int(potm_row[idx["POTMs"]]) + 1)
            _recalculate_batting(potm_row, idx)
            _recalculate_bowling(potm_row, idx)

    after_snapshot = _snapshot_player_stats(rows, idx)
    changed_players = _diff_player_stats(before_snapshot, after_snapshot)

    updated_csv = _csv_bytes(header, rows)
    return {
        "updated_csv_bytes": updated_csv,
        "changed_players": changed_players,
        "match": asdict(match),
        "batting_updates": batting_updates,
        "bowling_updates": bowling_updates,
        "unmatched": unmatched,
        "new_players": new_players,
        "helper_columns_added": HELPER_COLUMNS,
        "summary": {
            "match_id": match.match_id,
            "player_of_match": match.player_of_match,
            "teams": ", ".join(match.teams),
            "batting_rows_found": len(match.batting),
            "bowling_rows_found": len(match.bowling),
            "batting_rows_updated": len(batting_updates),
            "bowling_rows_updated": len(bowling_updates),
            "unmatched_count": len(unmatched),
            "new_players_added": len(new_players),
            "changed_players_count": len(changed_players),
        },
    }
