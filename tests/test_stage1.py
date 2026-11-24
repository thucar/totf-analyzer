"""Schema-15 joint, punch, and guard decoding."""

from pathlib import Path

import numpy as np
import pytest

from totf_analyzer.analytics.metrics import _round_windows, build_analytics
from totf_analyzer.parser.session import ParsedSession, TrackData, load_session
from totf_analyzer.parser.t2sr import (
    BONE_LEFT_WRIST,
    BONE_RIGHT_WRIST,
    HAND_LEFT,
    HAND_RIGHT,
    L_ELBOW,
    L_SHOULDER,
    PHASE_EVENT_TYPE,
    PHASE_FIGHT,
    PHASE_FIGHT_OVER,
    PHASE_KNOCKDOWN,
    PHASE_ROUND_END,
    PHASE_WARNING,
    EventRecord,
    guard_channel_scales,
)

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "Recordings"


def _recording(stamp: str) -> Path:
    matches = sorted(RECORDINGS.glob(f"*_{stamp}.zip"))
    if matches:
        return matches[0]
    return RECORDINGS / f"session_{stamp}.zip"


SAMPLE = _recording("20261115_054837")
THREE_ROUNDS = _recording("20261115_061911")

GUARD_BOUNDS = {
    "brace": (0.0, 8.0),
    "friction": (0.0, 4.0),
    "mass": (0.0, 8.0),
    "ladder": (0.0, 5.0),
}


def _scaled_upper_arm(session, corner: int) -> float:
    for track in session.metadata["m_tracks"]:
        if int(track["m_corner"]) == corner:
            return float(track["m_snapshot"]["m_scaledUpperArmLength"])
    raise AssertionError(f"no snapshot for corner {corner}")


def test_guard_header_scales():
    import zipfile

    for path in (SAMPLE, THREE_ROUNDS):
        assert path.is_file(), path
        with zipfile.ZipFile(path) as archive:
            for folder in ("p1", "p2"):
                scales = guard_channel_scales(archive.read(f"{folder}/guard.bin"))
                assert scales.keys() == GUARD_BOUNDS.keys()
                for name, bounds in GUARD_BOUNDS.items():
                    assert scales[name] == pytest.approx(bounds)


def test_upper_arm_matches_snapshot():
    session = load_session(SAMPLE)
    for track in session.tracks.values():
        segment = track.skeleton_pos[:, L_SHOULDER] - track.skeleton_pos[:, L_ELBOW]
        length = np.linalg.norm(segment, axis=1)
        assert np.median(length) == pytest.approx(_scaled_upper_arm(session, track.corner), abs=0.005)


def test_punch_hand_bone_and_launch():
    session = load_session(SAMPLE)
    for track in session.tracks.values():
        assert track.punches
        for punch in track.punches:
            assert punch.launch_tick <= punch.tick
            if punch.hand_index == HAND_LEFT:
                assert punch.bone_index == BONE_LEFT_WRIST
            elif punch.hand_index == HAND_RIGHT:
                assert punch.bone_index == BONE_RIGHT_WRIST
            else:
                raise AssertionError(punch.hand_index)


def test_three_round_guard_excludes_breaks():
    assert THREE_ROUNDS.is_file(), THREE_ROUNDS
    session = load_session(THREE_ROUNDS)
    report = build_analytics(session)
    windows = {window.index: window for window in _round_windows(session)}
    limits = {f"guard_{name}": upper for name, (_lower, upper) in GUARD_BOUNDS.items()}
    for series in report.series:
        upper = limits.get(series.name)
        if upper is None:
            continue
        assert series.y
        assert min(series.y) >= -1.0e-4
        assert max(series.y) <= upper + 1.0e-4

    fight = {item.corner: item for item in report.defense}
    for corner, track in session.tracks.items():
        assert fight[corner].guard_up_percent is not None
        assert fight[corner].guard_up_percent > 0
        weighted = 0.0
        frames = 0
        for rnd in report.rounds:
            if not rnd.completed or not rnd.defense:
                continue
            window = windows[rnd.index]
            defense = next(item for item in rnd.defense if item.corner == corner)
            assert defense.guard_up_percent is not None
            assert defense.guard_up_percent > 0
            selected = (track.skeleton_ticks >= window.warning_tick) & (track.skeleton_ticks <= window.stats_end)
            count = int(np.sum(selected))
            assert count > 0
            weighted += defense.guard_up_percent * count
            frames += count
        assert frames > 0
        assert fight[corner].guard_up_percent == pytest.approx(weighted / frames, abs=1.0e-4)

    hands = {row.hand for item in report.offense for row in item.hands}
    assert {"left", "right"} <= hands
    assert "hand_0" not in hands and "hand_1" not in hands


def _synthetic_phase_session(phases: list[tuple[int, int]], *, round_sec: float = 120.0) -> ParsedSession:
    empty_u32 = np.zeros(0, dtype=np.uint32)
    empty_f32 = np.zeros((0, 3), dtype=np.float32)
    start_tick = min(tick for tick, _ in phases) - 100
    end_tick = max(tick for tick, _ in phases) + 500
    events = [
        EventRecord(tick=tick, type_code=PHASE_EVENT_TYPE, subtype=0, scored_hit=False, phase=phase)
        for tick, phase in phases
    ]
    track = TrackData(
        folder="p1",
        corner=1,
        color="blue",
        name="tester",
        is_local_player=True,
        stance="orthodox",
        stance_confirmed=True,
        height_m=1.8,
        hand_length_m=0.095,
        ai_archetype=None,
        ai_difficulty=None,
        start_tick=start_tick,
        end_tick=end_tick,
        punches=[],
        events=events,
        punishment_ticks=empty_u32,
        punishment=empty_f32,
        stiffness_ticks=empty_u32,
        stiffness=empty_f32,
        guard_ticks=empty_u32,
        guard_primary=np.zeros((0, 4), dtype=np.float32),
        skeleton_ticks=empty_u32,
        skeleton_pos=np.zeros((0, 21, 3), dtype=np.float32),
    )
    return ParsedSession(
        path=Path("synthetic.zip"),
        metadata={"m_venue": {"m_roundDurationSeconds": round_sec}},
        fixed_timestep=1.0 / 120.0,
        start_tick=start_tick,
        end_tick=end_tick,
        tracks={1: track},
    )


def test_round_windows_handles_varying_warning_to_bell_gaps():
    # Schema-16 recordings emit warning->bell gaps of 735..738 ticks (not always 735).
    # Mid-round knockdown (5->4) and foul/clinch (7->4) resumes must not start new rounds.
    phases = [
        (1000, PHASE_WARNING),
        (1738, PHASE_FIGHT),  # gap = 738
        (5000, 7),  # clinch / foul break
        (5400, PHASE_FIGHT),
        (16140, PHASE_ROUND_END),
        (22000, PHASE_WARNING),
        (22737, PHASE_FIGHT),  # gap = 737
        (28000, PHASE_KNOCKDOWN),
        (29200, PHASE_FIGHT),  # 10s knockdown count
        (37139, PHASE_ROUND_END),
        (43000, PHASE_WARNING),
        (43736, PHASE_FIGHT),  # gap = 736
        (58138, PHASE_FIGHT_OVER),
    ]
    windows = _round_windows(_synthetic_phase_session(phases, round_sec=120.0))
    assert len(windows) == 3
    assert [(w.warning_tick, w.bell_tick) for w in windows] == [
        (1000, 1738),
        (22000, 22737),
        (43000, 43736),
    ]
    assert windows[0].duration_sec == pytest.approx(120.0, abs=0.05)
    assert windows[1].pauses == ((28000, 29200),)
    assert windows[1].duration_sec == pytest.approx(110.0, abs=0.05)
    assert windows[2].duration_sec == pytest.approx(120.0, abs=0.05)


@pytest.mark.parametrize(
    ("stamp", "expected_rounds"),
    [
        ("20261124_054822", 3),
        ("20261124_060157", 2),
        ("20261124_060913", 3),
    ],
)
def test_schema16_matches_populate_all_rounds_and_bell_metrics(stamp: str, expected_rounds: int):
    path = _recording(stamp)
    if not path.is_file():
        pytest.skip(f"{stamp} recording is not on this machine")
    session = load_session(path)
    windows = _round_windows(session)
    assert len(windows) == expected_rounds
    report = build_analytics(session)
    completed = [rnd for rnd in report.rounds if rnd.completed]
    assert len(completed) == expected_rounds
    for rnd in completed:
        assert rnd.bell_sec is not None
        assert rnd.end_sec is not None
        assert rnd.duration_sec is not None and rnd.duration_sec > 0
        assert len(rnd.offense) == 2
        assert len(rnd.defense) == 2
    for defense in report.defense:
        assert defense.footwork.total_distance_m is not None and defense.footwork.total_distance_m > 0
        assert defense.head_movement.off_centerline_percent is not None
        assert defense.vulnerability.while_throwing.time_share is not None

