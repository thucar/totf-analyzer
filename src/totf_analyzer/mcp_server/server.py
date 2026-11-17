"""Streamable HTTP MCP server. Tools return measurements, not coaching opinions."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from totf_analyzer.analytics.metrics import build_analytics
from totf_analyzer.models.analytics import FightAnalytics, OffenseStats, PunchRow
from totf_analyzer.parser.session import COLOR_CORNER, load_session

mcp = MCPServer("totf-analyzer")
_recordings = Path(os.environ.get("TOTF_RECORDINGS", "Recordings"))
_cache: dict[tuple[str, int, int], FightAnalytics] = {}


def configure(recordings: Path) -> None:
    global _recordings
    _recordings = recordings


def _resolve(path: str) -> Path:
    root = _recordings.resolve()
    raw = Path(path)
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if candidate.suffix.lower() != ".zip" or not candidate.is_file() or not candidate.is_relative_to(root):
        raise FileNotFoundError(f"session zip not found: {path}")
    return candidate


def _load(path: str) -> FightAnalytics:
    resolved = _resolve(path)
    stat = resolved.stat()
    key = (str(resolved), stat.st_mtime_ns, stat.st_size)
    if key not in _cache:
        _cache[key] = build_analytics(load_session(resolved))
    return _cache[key]


def _trim_offense(offense: dict, *, include_punches: bool, max_patterns: int | None) -> None:
    if not include_punches:
        offense.pop("punches", None)
    if max_patterns is not None:
        combos = offense.get("combinations")
        if isinstance(combos, dict) and isinstance(combos.get("patterns"), list):
            combos["patterns"] = combos["patterns"][:max_patterns]


def _compact_report(
    payload: dict,
    *,
    include_series: bool,
    include_punches: bool,
    include_moments: bool,
    max_patterns: int | None,
) -> dict:
    if not include_series:
        payload.pop("series", None)
    if not include_moments:
        payload.pop("key_moments", None)
    for offense in payload.get("offense", []):
        _trim_offense(offense, include_punches=include_punches, max_patterns=max_patterns)
    for rnd in payload.get("rounds", []):
        if not include_series:
            rnd.pop("series", None)
        if not include_moments:
            rnd.pop("key_moments", None)
        for offense in rnd.get("offense", []):
            _trim_offense(offense, include_punches=include_punches, max_patterns=max_patterns)
    return payload


def _punch_dict(row: PunchRow) -> dict:
    data = row.model_dump(mode="json")
    data["punch_type"] = row.trajectory
    return data


def _offense_for(report: FightAnalytics, corner: int, round_index: int | None) -> OffenseStats:
    if not any(fighter.corner == corner for fighter in report.fighters):
        raise ValueError(f"corner {corner} is not in this session")
    if round_index is None:
        offense = next((item for item in report.offense if item.corner == corner), None)
        if offense is None:
            raise ValueError(f"corner {corner} is not in this session")
        return offense
    rnd = next((item for item in report.rounds if item.index == round_index), None)
    if rnd is None or not rnd.completed:
        raise ValueError(f"round {round_index} is not in this session")
    offense = next((item for item in rnd.offense if item.corner == corner), None)
    if offense is None:
        raise ValueError(f"round {round_index} has no offense for corner {corner}")
    return offense


@mcp.tool()
def list_recordings() -> list[dict]:
    """List TotF2 session zip files in the recordings directory."""
    root = _recordings
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("*.zip")):
        stat = path.stat()
        rows.append({"name": path.name, "path": str(path.resolve()), "size": stat.st_size})
    return rows


@mcp.tool()
def analyze_recording(
    path: str,
    include_series: bool = False,
    include_punches: bool = False,
    include_moments: bool = False,
    max_patterns: int | None = 5,
) -> dict:
    """Parse a session zip and return the FightAnalytics summary.

    `path` is a file name or an absolute path inside the recordings directory.
    By default, `series`, `punches`, and `key_moments` arrays are omitted and
    `combinations.patterns` is capped at `max_patterns` so the response stays compact.
    Use `get_punches`, `get_series`, and `get_key_moments` to drill down, or pass
    `include_series=True`, `include_punches=True`, `include_moments=True`, and
    `max_patterns=None` for the full report.
    """
    payload = _load(path).model_dump(mode="json")
    return _compact_report(
        payload,
        include_series=include_series,
        include_punches=include_punches,
        include_moments=include_moments,
        max_patterns=max_patterns,
    )


@mcp.tool()
def get_fighter_stats(
    path: str,
    corner: int,
    include_punches: bool = False,
    max_patterns: int | None = 10,
) -> dict:
    """Offense and defense stats for one corner (1 = blue, 2 = red).

    Omits `offense.punches` by default (`include_punches=False`) and caps
    `combinations.patterns` to `max_patterns` (`None` keeps all patterns).
    """
    report = _load(path)
    fighter = next((item for item in report.fighters if item.corner == corner), None)
    offense = next((item for item in report.offense if item.corner == corner), None)
    defense = next((item for item in report.defense if item.corner == corner), None)
    if fighter is None or offense is None or defense is None:
        raise ValueError(f"corner {corner} is not in this session")
    offense_dict = offense.model_dump(mode="json")
    _trim_offense(offense_dict, include_punches=include_punches, max_patterns=max_patterns)
    rounds = []
    for rnd in report.rounds:
        block = rnd.red if corner == COLOR_CORNER["red"] else rnd.blue
        round_offense = next((item for item in rnd.offense if item.corner == corner), None)
        round_defense = next((item for item in rnd.defense if item.corner == corner), None)
        row = {
            "index": rnd.index,
            "completed": rnd.completed,
            "bell_sec": rnd.bell_sec,
            "end_sec": rnd.end_sec,
            "duration_sec": rnd.duration_sec,
            **block.model_dump(mode="json"),
        }
        if round_offense is not None:
            combos = round_offense.combinations.model_dump(mode="json")
            if max_patterns is not None and isinstance(combos.get("patterns"), list):
                combos["patterns"] = combos["patterns"][:max_patterns]
            row["offense"] = {
                "thrown": round_offense.thrown,
                "landed": round_offense.landed,
                "accuracy": round_offense.accuracy,
                "punches_per_minute": round_offense.punches_per_minute,
                "mean_speed": round_offense.velocity.mean_thrown,
                "combinations": combos,
            }
        if round_defense is not None:
            row["defense"] = {
                "guard_up_percent": round_defense.guard_up_percent,
                "guard_up_percent_under_fire": round_defense.guard_up_percent_under_fire,
                "under_fire_seconds": round_defense.under_fire_seconds,
                "head_mean_speed": round_defense.head_mean_speed,
                "received_damage_official": round_defense.received_damage_official,
                "guard_discipline": round_defense.guard_discipline.model_dump(mode="json"),
                "footwork": round_defense.footwork.model_dump(mode="json"),
                "head_movement": round_defense.head_movement.model_dump(mode="json"),
                "vulnerability": round_defense.vulnerability.model_dump(mode="json"),
            }
        rounds.append(row)
    return {
        "fighter": fighter.model_dump(mode="json"),
        "offense": offense_dict,
        "defense": defense.model_dump(mode="json"),
        "rounds": rounds,
    }


@mcp.tool()
def get_punches(
    path: str,
    corner: int,
    round_index: int | None = None,
    landed_only: bool = False,
) -> list[dict]:
    """Per-punch rows for one corner (1 = blue, 2 = red), optionally for one completed round.

    Omit `round_index` for fight-clock seconds across the recording. Pass a completed
    `round_index` (0-based) for seconds after that round's bell. `landed_only=True`
    keeps only landed punches.
    """
    report = _load(path)
    offense = _offense_for(report, corner, round_index)
    rows = [
        _punch_dict(row)
        for row in offense.punches
        if row.hand_index != -1 and (not landed_only or row.landed)
    ]
    return rows


@mcp.tool()
def get_key_moments(
    path: str,
    type: str | None = None,
    corner: int | None = None,
    round_index: int | None = None,
) -> list[dict]:
    """Timestamped moments. Optional `type`, `corner`, and `round_index` filters."""
    report = _load(path)
    if corner is not None and not any(fighter.corner == corner for fighter in report.fighters):
        raise ValueError(f"corner {corner} is not in this session")
    if round_index is None:
        moments = report.key_moments
    else:
        rnd = next((item for item in report.rounds if item.index == round_index), None)
        if rnd is None or not rnd.completed:
            raise ValueError(f"round {round_index} is not in this session")
        moments = rnd.key_moments
    if type:
        moments = [moment for moment in moments if moment.type == type]
    if corner is not None:
        moments = [moment for moment in moments if corner in moment.corners]
    return [moment.model_dump(mode="json") for moment in moments]


@mcp.tool()
def get_series(path: str, name: str, corner: int | None = None, round_index: int | None = None) -> list[dict]:
    """Downsampled series by name, optionally for one corner and one round.

    Omit round_index for the whole recording. Pass a completed round index (0-based)
    for that round only; those timestamps are seconds after the bell.

    Names include punishment_0, punishment_1, punishment_2, guard_up, left_guard_up,
    right_guard_up, guard_brace, guard_friction, guard_mass, guard_ladder, head_speed,
    head_height, hips_x, hips_z, head_slip_lateral, fighter_distance, blade_angle,
    tangential_speed, punch_density, and stiffness_max.
    """
    report = _load(path)
    if round_index is None:
        source = report.series
    else:
        rnd = next((item for item in report.rounds if item.index == round_index), None)
        if rnd is None:
            raise ValueError(f"round {round_index} is not in this session")
        source = rnd.series
    rows = [series for series in source if series.name == name]
    if corner is not None:
        rows = [series for series in rows if series.corner == corner]
    return [series.model_dump(mode="json") for series in rows]


def main(host: str = "127.0.0.1", port: int = 8010) -> None:
    mcp.run(transport="streamable-http", host=host, port=port)
