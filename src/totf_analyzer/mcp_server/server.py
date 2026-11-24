"""Streamable HTTP MCP server. Tools return measurements, not coaching opinions."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from totf_analyzer.analytics.metrics import build_analytics
from totf_analyzer.models.analytics import FightAnalytics, OffenseStats, PunchRow
from totf_analyzer.parser.metadata import inspect_zip_metadata
from totf_analyzer.parser.session import COLOR_CORNER, load_session
from totf_analyzer.sync.quest import SyncConfig, get_sync_status, run_sync

mcp = MCPServer("totf-analyzer")
_recordings = Path(os.environ.get("TOTF_RECORDINGS", "Recordings"))
_game_recordings: Path | None = None
_cache: dict[tuple[str, int, int], FightAnalytics] = {}


def configure(recordings: Path, game_recordings: Path | None = None) -> None:
    global _recordings, _game_recordings
    _recordings = recordings
    _game_recordings = game_recordings


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
    include_context: bool,
    max_patterns: int | None,
) -> dict:
    if not include_series:
        payload.pop("series", None)
    if not include_moments:
        payload.pop("key_moments", None)
    if not include_context:
        payload.pop("context", None)
    for offense in payload.get("offense", []):
        _trim_offense(offense, include_punches=include_punches, max_patterns=max_patterns)
    for rnd in payload.get("rounds", []):
        if not include_series:
            rnd.pop("series", None)
        if not include_moments:
            rnd.pop("key_moments", None)
        if not include_context:
            rnd.pop("context", None)
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


def _sync_config() -> SyncConfig:
    return SyncConfig.from_env(
        dest_dir=_game_recordings,
        library_dir=_recordings.resolve(),
        copy_to_library=True,
    )


@mcp.tool()
def list_recordings(kind: str | None = None) -> list[dict]:
    """List TotF2 session zip files in the recordings directory.

    Each entry includes `session_kind` (`"match"` or `"training"`), `is_training`,
    `bout`, `match_type`, fighter names, and `result`. Pass `kind="match"` or
    `kind="training"` to filter.
    """
    if kind is not None and kind not in {"", "all", "match", "training"}:
        raise ValueError("kind must be 'match', 'training', or 'all'")
    root = _recordings
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("*.zip")):
        if not path.is_file():
            continue
        stat = path.stat()
        meta = inspect_zip_metadata(path)
        if kind in {"match", "training"} and meta["session_kind"] != kind:
            continue
        rows.append(
            {
                "name": path.name,
                "path": str(path.resolve()),
                "size": stat.st_size,
                "bout": meta["bout"],
                "created": meta["created"],
                "red": meta["red"],
                "blue": meta["blue"],
                "result": meta["result"],
                "match_type": meta["match_type"],
                "session_kind": meta["session_kind"],
                "is_training": meta["is_training"],
            }
        )
    return rows


@mcp.tool()
def quest_sync_status() -> dict:
    """Inspect Quest 3 Wi-Fi discovery, ADB reachability, ledger count, and pending recordings."""
    return get_sync_status(_sync_config()).to_dict()


@mcp.tool()
def sync_quest_recordings(
    dry_run: bool = False,
    ignore_ledger: bool = False,
    resync: list[str] | None = None,
) -> dict:
    """Pull new TotF2 recordings from Quest 3 over Wi-Fi into Steam Spectator and Recordings/."""
    if resync is not None:
        for name in resync:
            if Path(name).name != name or not name.lower().endswith(".zip"):
                raise ValueError(f"resync name must be a session zip file name: {name}")
    return run_sync(
        _sync_config(),
        dry_run=dry_run,
        ignore_ledger=ignore_ledger,
        resync=resync,
        notify=True,
    ).to_dict()


@mcp.tool()
def analyze_recording(
    path: str,
    include_series: bool = False,
    include_punches: bool = False,
    include_moments: bool = False,
    include_context: bool = False,
    max_patterns: int | None = 5,
) -> dict:
    """Parse a session zip and return the FightAnalytics summary.

    `path` is a file name or an absolute path inside the recordings directory.
    By default, `series`, `punches`, `key_moments`, and `context` arrays are omitted
    and `combinations.patterns` is capped at `max_patterns` so the response stays compact.
    Use `get_context_stats`, `get_punches`, `get_series`, and `get_key_moments` to drill down,
    or pass `include_series=True`, `include_punches=True`, `include_moments=True`,
    `include_context=True`, and `max_patterns=None` for the full report.
    """
    payload = _load(path).model_dump(mode="json")
    return _compact_report(
        payload,
        include_series=include_series,
        include_punches=include_punches,
        include_moments=include_moments,
        include_context=include_context,
        max_patterns=max_patterns,
    )


@mcp.tool()
def get_fighter_stats(
    path: str,
    corner: int,
    include_punches: bool = False,
    include_round_context: bool = False,
    max_patterns: int | None = 10,
) -> dict:
    """Offense, defense, and fight-level situational context stats for one corner (1 = blue, 2 = red).

    Includes fight-level `context` breakdowns (`by_stun_state`, `by_punishment_state`,
    `by_range_zone`, `by_engagement_state`) by default. Pass `include_round_context=True`
    (or call `get_context_stats`) for per-round situational breakdowns. Omits `offense.punches`
    by default (`include_punches=False`) and caps `combinations.patterns` to `max_patterns`.
    """
    report = _load(path)
    fighter = next((item for item in report.fighters if item.corner == corner), None)
    offense = next((item for item in report.offense if item.corner == corner), None)
    defense = next((item for item in report.defense if item.corner == corner), None)
    context = next((item for item in report.context if item.corner == corner), None)
    if fighter is None or offense is None or defense is None:
        raise ValueError(f"corner {corner} is not in this session")
    offense_dict = offense.model_dump(mode="json")
    _trim_offense(offense_dict, include_punches=include_punches, max_patterns=max_patterns)
    rounds = []
    for rnd in report.rounds:
        block = rnd.red if corner == COLOR_CORNER["red"] else rnd.blue
        round_offense = next((item for item in rnd.offense if item.corner == corner), None)
        round_defense = next((item for item in rnd.defense if item.corner == corner), None)
        round_context = next((item for item in rnd.context if item.corner == corner), None)
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
        if include_round_context and round_context is not None:
            row["context"] = round_context.model_dump(mode="json")
        rounds.append(row)
    result = {
        "fighter": fighter.model_dump(mode="json"),
        "offense": offense_dict,
        "defense": defense.model_dump(mode="json"),
        "rounds": rounds,
    }
    if context is not None:
        result["context"] = context.model_dump(mode="json")
    return result


@mcp.tool()
def get_context_stats(
    path: str,
    corner: int | None = None,
    round_index: int | None = None,
) -> list[dict]:
    """Situational context breakdowns (`by_stun_state`, `by_punishment_state`, `by_range_zone`, `by_engagement_state`).

    Each bucket reports time, share, punch volume/accuracy/speed/damage, guard/off-hand/head/stance
    discipline, and hits/damage/stuns taken plus countered rate. Optional `corner` (1 = blue, 2 = red)
    and completed `round_index` (0-based) filters.
    """
    report = _load(path)
    if corner is not None and not any(fighter.corner == corner for fighter in report.fighters):
        raise ValueError(f"corner {corner} is not in this session")
    if round_index is None:
        rows = report.context
    else:
        rnd = next((item for item in report.rounds if item.index == round_index), None)
        if rnd is None or not rnd.completed:
            raise ValueError(f"round {round_index} is not in this session")
        rows = rnd.context
    if corner is not None:
        rows = [item for item in rows if item.corner == corner]
    return [item.model_dump(mode="json") for item in rows]


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
    keeps only landed punches. Each row includes outcome `hit_kind` and launch-state context
    (`self_stunned`, `opponent_stunned`, `self_hurt`, `opponent_hurt`, `range_zone`,
    `fighter_distance_m`, `under_fire`, `in_exchange`).
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

    Names include punishment_0, punishment_1, punishment_2, punishment_ratio, stunned,
    guard_up, left_guard_up, right_guard_up, guard_brace, guard_friction, guard_mass,
    guard_ladder, head_speed, head_height, hips_x, hips_z, head_slip_lateral,
    fighter_distance, blade_angle, tangential_speed, punch_density, and stiffness_max.
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
