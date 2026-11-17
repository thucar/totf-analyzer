"""Per-hand guard, off-hand discipline, and punch retraction."""

from pathlib import Path

import numpy as np
import pytest

from totf_analyzer.analytics.metrics import _round_windows, build_analytics
from totf_analyzer.parser.session import load_session

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "Recordings"


def _recording(stamp: str) -> Path:
    matches = sorted(RECORDINGS.glob(f"*_{stamp}.zip"))
    if matches:
        return matches[0]
    return RECORDINGS / f"session_{stamp}.zip"


SAMPLE = _recording("20261115_054837")
THREE_ROUNDS = _recording("20261115_061911")


def _report(path: Path):
    assert path.is_file(), path
    return load_session(path), build_analytics(load_session(path))


def test_guard_coverage_matches_both_hands_and_rounds():
    session, report = _report(THREE_ROUNDS)
    windows = {window.index: window for window in _round_windows(session)}
    fight = {item.corner: item for item in report.defense}
    for corner, track in session.tracks.items():
        defense = fight[corner]
        discipline = defense.guard_discipline
        assert discipline.both_guard_up_percent == defense.guard_up_percent
        assert discipline.either_guard_up_percent >= discipline.left_guard_up_percent
        assert discipline.either_guard_up_percent >= discipline.right_guard_up_percent
        assert discipline.left_guard_up_percent >= discipline.both_guard_up_percent
        assert discipline.right_guard_up_percent >= discipline.both_guard_up_percent
        weighted = {name: 0.0 for name in ("left", "right", "both", "either")}
        frames = 0
        for rnd in report.rounds:
            if not rnd.completed or not rnd.defense:
                continue
            window = windows[rnd.index]
            round_defense = next(item for item in rnd.defense if item.corner == corner)
            assert round_defense.guard_discipline.both_guard_up_percent == round_defense.guard_up_percent
            selected = (track.skeleton_ticks >= window.warning_tick) & (track.skeleton_ticks <= window.stats_end)
            count = int(np.sum(selected))
            assert count > 0
            block = round_defense.guard_discipline
            weighted["left"] += block.left_guard_up_percent * count
            weighted["right"] += block.right_guard_up_percent * count
            weighted["both"] += block.both_guard_up_percent * count
            weighted["either"] += block.either_guard_up_percent * count
            frames += count
        assert frames > 0
        assert discipline.left_guard_up_percent == pytest.approx(weighted["left"] / frames, abs=1.0e-4)
        assert discipline.right_guard_up_percent == pytest.approx(weighted["right"] / frames, abs=1.0e-4)
        assert discipline.both_guard_up_percent == pytest.approx(weighted["both"] / frames, abs=1.0e-4)
        assert discipline.either_guard_up_percent == pytest.approx(weighted["either"] / frames, abs=1.0e-4)


def test_punch_guard_fields_are_consistent():
    for path in (SAMPLE, THREE_ROUNDS):
        _session, report = _report(path)
        seen = 0
        for offense in report.offense:
            assert offense.punches
            for punch in offense.punches:
                if punch.offhand_in_guard is None:
                    assert punch.offhand_drop_m is None
                    assert punch.offhand_flare_m is None
                else:
                    seen += 1
                    assert punch.offhand_drop_m is not None and punch.offhand_drop_m >= 0
                    assert punch.offhand_flare_m is not None and punch.offhand_flare_m >= 0
                if punch.retraction_ms is None:
                    assert punch.retraction_droop_m is None
                    assert punch.retraction_directness is None
                else:
                    assert punch.retraction_ms >= 0
                    assert punch.retraction_droop_m is not None and punch.retraction_droop_m >= 0
                    assert punch.retraction_directness is not None
                    assert 0.0 <= punch.retraction_directness <= 1.0
        assert seen > 0


def test_local_player_matches_061911_prototype():
    """Kinematic punches on the orthodox local player.

    Issue #1's exploratory script reported off-hand kept of 49.7% / 4.5% and a
    133 ms median return. Return rate in that script was 73.1%. This definition
    — kinematic records only, the 0.28 / 0.38 m box, excluding a hand that never
    left and same-hand double-ups — matches the time, sag, and droop figures and
    lands the kept rates within a couple of points.

    Contact records that repeat a swing no longer count as a next same-hand
    launch, so punches that touched something are no longer excluded from the
    return figures. That population returns in a 158 ms median at an 81% rate,
    and the test locks those counts.
    """
    _session, report = _report(THREE_ROUNDS)
    local = next(fighter for fighter in report.fighters if fighter.is_local_player)
    assert local.stance == "orthodox"
    discipline = next(item.guard_discipline for item in report.defense if item.corner == local.corner)
    assert discipline.offhand_guard_kept_percent_throwing_left == pytest.approx(49.7, abs=2.0)
    assert discipline.offhand_guard_kept_percent_throwing_right == pytest.approx(4.5, abs=2.0)
    assert discipline.offhand_drop_below_head_m_rear.median == pytest.approx(0.241, abs=0.02)
    assert discipline.offhand_drop_below_head_m_lead.median == pytest.approx(0.487, abs=0.03)
    assert discipline.retraction_time_ms.median == pytest.approx(158.3, abs=1.0)
    assert discipline.retraction_droop_m.sag_over_10cm_percent == pytest.approx(36.7, abs=2.0)
    assert discipline.retraction_droop_m.p90 == pytest.approx(0.495, abs=0.01)
    assert discipline.retraction_returned_percent == pytest.approx(80.8, abs=1.0)
    assert discipline.retraction_directness_ratio.median is not None
    assert 0.0 <= discipline.retraction_directness_ratio.median <= 1.0
    note = next(item for item in report.decode_status if item.field == "defense.guard_discipline")
    assert note.confidence == "inferred"
    assert "0.28" in note.note and "kinematic" in note.note
