"""Stage 6: compact MCP payloads, get_punches, get_key_moments filters, and new series."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from totf_analyzer.analytics.metrics import COMBO_GAP_SEC
from totf_analyzer.api.app import create_app
from totf_analyzer.mcp_server import server

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "Recordings"


def _recording(stamp: str) -> Path:
    matches = sorted(RECORDINGS.glob(f"*_{stamp}.zip"))
    if matches:
        return matches[0]
    return RECORDINGS / f"session_{stamp}.zip"


SAMPLE = _recording("20261115_054837")
THREE_ROUNDS = _recording("20261115_061911")
NEW_SERIES = (
    "left_guard_up",
    "right_guard_up",
    "hips_x",
    "hips_z",
    "head_slip_lateral",
    "fighter_distance",
    "blade_angle",
    "tangential_speed",
)


@pytest.fixture(autouse=True)
def _configure_server():
    server.configure(RECORDINGS)


@pytest.mark.skipif(not THREE_ROUNDS.is_file(), reason="061911 recording is not on this machine")
def test_default_mcp_payloads_stay_under_80kb_and_restore_when_flagged():
    compact = server.analyze_recording(THREE_ROUNDS.name)
    compact_bytes = len(json.dumps(compact))
    assert compact_bytes < 80_000, compact_bytes
    assert "series" not in compact
    assert "key_moments" not in compact
    assert compact["decode_status"]
    for offense in compact["offense"]:
        assert "punches" not in offense
        assert "combinations" in offense
        assert len(offense["combinations"]["patterns"]) <= 5
    for defense in compact["defense"]:
        for key in ("guard_discipline", "footwork", "head_movement", "vulnerability"):
            assert key in defense
    for rnd in compact["rounds"]:
        assert "series" not in rnd
        assert "key_moments" not in rnd
        for offense in rnd["offense"]:
            assert "punches" not in offense
            assert len(offense["combinations"]["patterns"]) <= 5

    for corner in (1, 2):
        fighter_compact = server.get_fighter_stats(THREE_ROUNDS.name, corner)
        fighter_bytes = len(json.dumps(fighter_compact))
        assert fighter_bytes < 80_000, fighter_bytes
        assert "punches" not in fighter_compact["offense"]
        assert len(fighter_compact["offense"]["combinations"]["patterns"]) <= 10
        for key in ("guard_discipline", "footwork", "head_movement", "vulnerability"):
            assert key in fighter_compact["defense"]

    full = server.analyze_recording(
        THREE_ROUNDS.name,
        include_series=True,
        include_punches=True,
        include_moments=True,
        max_patterns=None,
    )
    assert full["series"]
    assert full["key_moments"]
    assert all("punches" in offense and offense["punches"] for offense in full["offense"])
    assert any(len(offense["combinations"]["patterns"]) > 5 for offense in full["offense"])
    completed = [rnd for rnd in full["rounds"] if rnd["completed"]]
    assert all(rnd["series"] and rnd["key_moments"] for rnd in completed)
    assert all("punches" in offense and offense["punches"] for rnd in completed for offense in rnd["offense"])

    fighter_full = server.get_fighter_stats(
        THREE_ROUNDS.name,
        1,
        include_punches=True,
        max_patterns=None,
    )
    assert fighter_full["offense"]["punches"]
    assert len(fighter_full["offense"]["combinations"]["patterns"]) > 10


@pytest.mark.skipif(not THREE_ROUNDS.is_file(), reason="061911 recording is not on this machine")
def test_get_punches_filters_combo_fields_and_launch_slips():
    stats = server.get_fighter_stats(THREE_ROUNDS.name, 1, max_patterns=None)
    punches = server.get_punches(THREE_ROUNDS.name, 1)
    assert len(punches) == stats["offense"]["thrown"]
    assert all(row["hand_index"] != -1 for row in punches)
    assert all(row["punch_type"] == row["trajectory"] for row in punches)
    assert all(row["launch_sec"] is not None and row["launch_sec"] <= row["t_sec"] for row in punches)
    assert all(row["head_slip_m"] is not None and math.isfinite(row["head_slip_m"]) for row in punches)

    landed = server.get_punches(THREE_ROUNDS.name, 1, landed_only=True)
    assert landed
    assert all(row["landed"] and row["impact_sec"] is not None for row in landed)
    assert all(row["impact_sec"] is None for row in punches if not row["landed"])

    by_combo: dict[int, list[dict]] = {}
    for row in punches:
        if row["graze"]:
            assert row["combo_id"] is None
            assert row["combo_depth"] is None
            assert not row["countered"]
            continue
        assert row["combo_id"] is not None and row["combo_id"] >= 1
        assert row["combo_depth"] in {"1", "2", "3", "4", "5+"}
        by_combo.setdefault(row["combo_id"], []).append(row)
    assert len(by_combo) == stats["offense"]["combinations"]["combo_count"]
    for group in by_combo.values():
        ordered = sorted(group, key=lambda item: (item["launch_sec"], item["tick"]))
        assert ordered[0]["combo_depth"] == "1"
        for prev, curr in zip(ordered, ordered[1:]):
            assert curr["launch_sec"] - prev["launch_sec"] <= COMBO_GAP_SEC + 1.0e-3

    expected_countered = sum(row["countered_count"] for row in stats["offense"]["combinations"]["by_depth"])
    assert sum(1 for row in punches if row["countered"]) == expected_countered

    round_zero = server.get_punches(THREE_ROUNDS.name, 1, round_index=0)
    assert round_zero
    assert len(round_zero) < len(punches)
    duration = stats["rounds"][0]["duration_sec"]
    assert min(row["t_sec"] for row in round_zero) >= -8.0
    assert max(row["t_sec"] for row in round_zero) <= duration + 3.0

    with pytest.raises(ValueError):
        server.get_punches(THREE_ROUNDS.name, 99)
    with pytest.raises(ValueError):
        server.get_punches(THREE_ROUNDS.name, 1, round_index=99)


@pytest.mark.skipif(not THREE_ROUNDS.is_file(), reason="061911 recording is not on this machine")
def test_get_key_moments_filters_by_type_corner_and_round():
    all_moments = server.get_key_moments(THREE_ROUNDS.name)
    assert all_moments
    ducks_c1 = server.get_key_moments(THREE_ROUNDS.name, type="duck", corner=1)
    assert ducks_c1
    assert all(row["type"] == "duck" and 1 in row["corners"] for row in ducks_c1)
    round_one = server.get_key_moments(THREE_ROUNDS.name, corner=1, round_index=0)
    assert round_one
    assert len(round_one) < len(all_moments)
    assert all(1 in row["corners"] for row in round_one)

    with pytest.raises(ValueError):
        server.get_key_moments(THREE_ROUNDS.name, corner=99)
    with pytest.raises(ValueError):
        server.get_key_moments(THREE_ROUNDS.name, round_index=99)


@pytest.mark.skipif(not SAMPLE.is_file(), reason="sample recording is not on this machine")
def test_new_series_channels_and_http_report_stays_complete():
    paths = [SAMPLE] + ([THREE_ROUNDS] if THREE_ROUNDS.is_file() else [])
    for path in paths:
        stats = server.get_fighter_stats(path.name, 1)
        # Clock length of the round. duration_sec is fighting time and leaves out knockdown counts.
        round_duration = stats["rounds"][0]["end_sec"] - stats["rounds"][0]["bell_sec"]
        for name in NEW_SERIES:
            both = server.get_series(path.name, name)
            assert len(both) == 2
            for corner in (1, 2):
                rows = server.get_series(path.name, name, corner=corner)
                assert len(rows) == 1
                series = rows[0]
                assert series["t"] and len(series["t"]) == len(series["y"])
                assert all(math.isfinite(val) for val in series["y"])
                if name in {"left_guard_up", "right_guard_up"}:
                    assert all(0.0 <= val <= 1.0 for val in series["y"])
                rnd_rows = server.get_series(path.name, name, corner=corner, round_index=0)
                assert len(rnd_rows) == 1
                rnd_series = rnd_rows[0]
                assert rnd_series["t"] and len(rnd_series["t"]) == len(rnd_series["y"])
                assert min(rnd_series["t"]) >= -8.0
                assert max(rnd_series["t"]) <= round_duration + 3.0

    full = server.analyze_recording(SAMPLE.name, include_series=True, include_punches=True, include_moments=True)
    fields = {note["field"] for note in full["decode_status"]}
    assert "offense.punches" in fields
    assert "series.biomechanics" in fields

    client = TestClient(create_app(RECORDINGS))
    response = client.get(f"/api/sessions/{SAMPLE.name}/report")
    assert response.status_code == 200
    body = response.json()
    assert body["series"]
    assert body["key_moments"]
    assert all(offense["punches"] for offense in body["offense"])
