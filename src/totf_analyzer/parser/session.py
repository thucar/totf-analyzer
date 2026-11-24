"""Load a TotF2 session zip into aligned track data."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from totf_analyzer.parser.t2sr import (
    EventRecord,
    PunchRecord,
    read_events,
    read_guard_channels,
    read_punches,
    read_punishment,
    read_skeleton_positions,
    read_stiffness,
)

# Corner 1 is blue and corner 2 is red. A fighter's scored-hit events match that corner's m_hits.
CORNER_COLOR = {1: "blue", 2: "red"}
COLOR_CORNER = {"red": 2, "blue": 1}
STANCE_BY_CODE = {1: "orthodox"}
# Used when a track snapshot does not publish m_scaledHandLength.
DEFAULT_HAND_LENGTH_M = 0.095


@dataclass
class TrackData:
    folder: str
    corner: int
    color: str
    name: str
    is_local_player: bool
    stance: str | None
    stance_confirmed: bool
    height_m: float | None
    hand_length_m: float
    ai_archetype: str | None
    ai_difficulty: str | None
    start_tick: int
    end_tick: int
    punches: list[PunchRecord]
    events: list[EventRecord]
    punishment_ticks: np.ndarray
    punishment: np.ndarray
    stiffness_ticks: np.ndarray
    stiffness: np.ndarray
    guard_ticks: np.ndarray
    guard_primary: np.ndarray
    skeleton_ticks: np.ndarray
    skeleton_pos: np.ndarray
    # Mid-punishment meter settings from m_snapshot.m_punishmentConfigJson (None if unavailable).
    mid_punishment_capacity: float | None = None
    mid_punishment_critical_threshold: float | None = None
    breathing_threshold: float | None = None
    # Punch records that analytics judged not to be punches (set by analytics, empty after load).
    rejected_punches: list[PunchRecord] = field(default_factory=list)


@dataclass
class ParsedSession:
    path: Path
    metadata: dict
    fixed_timestep: float
    start_tick: int
    end_tick: int
    tracks: dict[int, TrackData] = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        return (self.end_tick - self.start_tick) * self.fixed_timestep


def _zip_names(zf: zipfile.ZipFile) -> set[str]:
    return set(zf.namelist())


def _assign_folders(zf: zipfile.ZipFile, track_metas: list[dict]) -> dict[str, dict]:
    names = _zip_names(zf)
    folders = [folder for folder in ("p1", "p2") if any(name.startswith(f"{folder}/") for name in names)]
    if len(folders) != len(track_metas):
        raise ValueError(
            f"session has {len(track_metas)} metadata tracks but folders {folders or 'none'}"
        )
    local_folders = [
        folder
        for folder in folders
        if f"{folder}/rawinput.bin" in names or f"{folder}/limitless.bin" in names
    ]
    if len(local_folders) == 1:
        local_meta = next((track for track in track_metas if track.get("m_isLocalPlayer")), None)
        if local_meta is None:
            raise ValueError("local-player binary layers are present but no track is marked local")
        assigned = {local_folders[0]: local_meta}
        other_folders = [folder for folder in folders if folder not in assigned]
        other_meta = [track for track in track_metas if track is not local_meta]
        for folder, meta in zip(other_folders, other_meta, strict=True):
            assigned[folder] = meta
        return assigned
    return dict(zip(folders, track_metas, strict=True))


def _stance(track_meta: dict) -> tuple[str | None, bool]:
    ai = track_meta.get("m_aiOpponent") or {}
    named = ai.get("m_stance")
    if isinstance(named, str) and named:
        return named.lower(), True
    code = (track_meta.get("m_snapshot") or {}).get("m_bodyStance")
    if code in STANCE_BY_CODE:
        return STANCE_BY_CODE[code], False
    return None, False


def _height(track_meta: dict) -> float | None:
    calibration = (track_meta.get("m_snapshot") or {}).get("m_calibration") or {}
    height = calibration.get("m_height")
    if isinstance(height, (int, float)):
        return float(height)
    return None


def _hand_length(track_meta: dict) -> float:
    snapshot = track_meta.get("m_snapshot") or {}
    length = snapshot.get("m_scaledHandLength")
    if isinstance(length, (int, float)) and float(length) > 0:
        return float(length)
    return DEFAULT_HAND_LENGTH_M


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if out > 0.0 else None


def _punishment_config(track_meta: dict) -> tuple[float | None, float | None, float | None]:
    """Return (mid_capacity, mid_critical_threshold, breathing_threshold) from snapshot config JSON."""
    snapshot = track_meta.get("m_snapshot") or {}
    raw = snapshot.get("m_punishmentConfigJson")
    if not isinstance(raw, str) or not raw.strip():
        return None, None, None
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, None
    if not isinstance(cfg, dict):
        return None, None, None
    mid = cfg.get("<MidPunishmentSettings>k__BackingField")
    mid_dict = mid if isinstance(mid, dict) else {}
    capacity = _positive_float(mid_dict.get("<MeterCapacity>k__BackingField"))
    critical = _positive_float(mid_dict.get("<CriticalThreshold>k__BackingField"))
    breathing = _positive_float(cfg.get("<OpponentBreathingStartThreshold>k__BackingField"))
    return capacity, critical, breathing


def _read_track(zf: zipfile.ZipFile, folder: str, meta: dict, origin: int) -> TrackData:
    corner = int(meta["m_corner"])
    color = CORNER_COLOR.get(corner)
    if color is None:
        raise ValueError(f"unsupported corner id {corner}")
    stance, stance_confirmed = _stance(meta)
    ai = meta.get("m_aiOpponent") or {}
    mid_cap, mid_crit, breathing = _punishment_config(meta)
    punishment_ticks, punishment = read_punishment(zf.read(f"{folder}/punishment.bin"), origin)
    stiffness_ticks, stiffness = read_stiffness(zf.read(f"{folder}/stiffness.bin"), origin)
    guard_ticks, guard_primary = read_guard_channels(zf.read(f"{folder}/guard.bin"), origin)
    skeleton_ticks, skeleton_pos = read_skeleton_positions(zf.read(f"{folder}/skeleton.bin"), origin)
    return TrackData(
        folder=folder,
        corner=corner,
        color=color,
        name=str(meta.get("m_boxerName") or folder).strip() or folder,
        is_local_player=bool(meta.get("m_isLocalPlayer")),
        stance=stance,
        stance_confirmed=stance_confirmed,
        height_m=_height(meta),
        hand_length_m=_hand_length(meta),
        ai_archetype=ai.get("m_archetype"),
        ai_difficulty=ai.get("m_difficulty"),
        start_tick=int(meta["m_startTick"]),
        end_tick=int(meta["m_endTick"]),
        punches=read_punches(zf.read(f"{folder}/punches.bin")),
        events=read_events(zf.read(f"{folder}/events.bin")),
        punishment_ticks=punishment_ticks,
        punishment=punishment,
        stiffness_ticks=stiffness_ticks,
        stiffness=stiffness,
        guard_ticks=guard_ticks,
        guard_primary=guard_primary,
        skeleton_ticks=skeleton_ticks,
        skeleton_pos=skeleton_pos,
        mid_punishment_capacity=mid_cap,
        mid_punishment_critical_threshold=mid_crit,
        breathing_threshold=breathing,
    )


def load_session(path: Path | str) -> ParsedSession:
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        if "metadata.json" not in _zip_names(zf):
            raise ValueError(f"{path.name} is not a TotF session zip (missing metadata.json)")
        metadata = json.loads(zf.read("metadata.json"))
        track_metas = metadata.get("m_tracks") or []
        if len(track_metas) < 1:
            raise ValueError("session metadata has no tracks")
        fixed = float(metadata["m_fixedTimestep"])
        assigned = _assign_folders(zf, track_metas)
        origin = min(int(track["m_startTick"]) for track in track_metas)
        end = max(int(track["m_endTick"]) for track in track_metas)
        tracks = {}
        for folder, meta in assigned.items():
            track = _read_track(zf, folder, meta, origin)
            tracks[track.corner] = track
    return ParsedSession(
        path=path,
        metadata=metadata,
        fixed_timestep=fixed,
        start_tick=origin,
        end_tick=end,
        tracks=tracks,
    )
