from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from totf_analyzer.analytics.metrics import build_analytics
from totf_analyzer.api.app import create_app
from totf_analyzer.parser.session import load_session

ROOT = Path(__file__).resolve().parents[1]


def _recording(folder: Path, stamp: str) -> Path:
    matches = sorted(folder.glob(f"*_{stamp}.zip"))
    if matches:
        return matches[0]
    return folder / f"session_{stamp}.zip"


SAMPLE = _recording(ROOT / "Recordings", "20261115_054837")


@pytest.fixture(scope="module")
def report():
    assert SAMPLE.is_file(), SAMPLE
    return build_analytics(load_session(SAMPLE))


def test_parser_frame_counts():
    session = load_session(SAMPLE)
    blue = session.tracks[1]
    red = session.tracks[2]
    assert blue.color == "blue" and red.color == "red"
    assert blue.is_local_player
    assert blue.name.strip()
    assert red.name.strip()
    assert blue.name != red.name
    assert len(blue.punches) == 110
    assert len(red.punches) == 102
    assert len(blue.events) == 17
    assert len(red.events) == 58
    assert len(blue.skeleton_ticks) == 16886
    assert int(blue.skeleton_ticks[0]) == 14441
    assert int(blue.skeleton_ticks[-1]) == 31326
    assert len(blue.punishment_ticks) == 4221
    assert int(blue.punishment_ticks[0]) == 14444
    assert sum(1 for event in red.events if event.scored_hit) == 33
    assert sum(1 for event in blue.events if event.scored_hit) == 17


def test_official_scorecard(report):
    assert report.session.method == "knockout"
    assert report.session.winner_corner == 1
    assert report.session.winner_color == "blue"
    assert report.session.red_total_score == 7
    assert report.session.blue_total_score == 10
    assert report.rounds[0].completed
    assert report.rounds[0].red.hits == 33
    assert report.rounds[0].blue.hits == 17
    assert report.rounds[0].red.received_damage == 1032
    assert report.rounds[0].blue.received_damage == 134
    assert report.rounds[0].red.knocked_out
    assert report.rounds[0].red.stuns == 4
    assert 140 < report.session.duration_sec < 142
    measured = [rnd for rnd in report.rounds if rnd.completed and rnd.offense]
    assert len(measured) == 1
    rnd = measured[0]
    assert rnd.bell_sec is not None and rnd.duration_sec is not None
    assert 30 < rnd.bell_sec < 40
    assert rnd.duration_sec < report.session.duration_sec
    by_round = {item.corner: item for item in rnd.offense}
    assert by_round[1].thrown == 70
    assert by_round[1].landed == rnd.red.hits == 33
    assert by_round[2].thrown == 24
    assert by_round[2].landed == rnd.blue.hits == 17
    times = [punch.t_sec for item in rnd.offense for punch in item.punches]
    assert min(times) >= -7
    assert max(times) <= rnd.duration_sec + 3
    assert all(not later.offense for later in report.rounds if not later.completed)
    assert any(moment.type == "knockout" for moment in rnd.key_moments)


def test_cross_stream_metrics(report):
    by_corner = {item.corner: item for item in report.offense}
    assert by_corner[1].thrown == 70
    assert by_corner[1].landed == 33
    assert by_corner[1].official_hits == 33
    assert by_corner[2].thrown == 24
    assert by_corner[2].landed == 17
    assert by_corner[2].official_hits == 17
    assert by_corner[1].accuracy == pytest.approx(33 / 70)
    assert by_corner[2].accuracy == pytest.approx(17 / 24)
    red_hands = {row.hand: row for row in by_corner[1].hands}
    assert sum(row.landed for row in by_corner[1].hands) == 33
    assert sum(row.thrown for row in by_corner[1].hands) == 70
    assert {"left", "right"} <= set(red_hands)
    assert "hand_0" not in red_hands and "hand_1" not in red_hands
    assert by_corner[1].kinematic_thrown == 61
    assert by_corner[1].velocity.samples == 61
    assert by_corner[1].velocity.mean_thrown is not None
    assert by_corner[2].velocity.samples == 0
    trajectories = {row.trajectory: row for row in by_corner[1].trajectories}
    assert {"jab", "cross", "left_hook", "right_hook"} <= set(trajectories)
    assert trajectories["left_hook"].thrown >= 9
    assert trajectories["right_hook"].thrown >= 22
    assert trajectories["jab"].thrown >= 16
    assert trajectories["cross"].thrown >= 9


def test_contact_records_are_not_all_punches(report):
    session = load_session(SAMPLE)
    for offense in report.offense:
        recorded = len(session.tracks[offense.corner].punches)
        assert offense.thrown == offense.kinematic_thrown + offense.contact_thrown
        assert offense.thrown + offense.discarded_records == recorded
        assert offense.combinations.max_combo_length <= 6
    by_corner = {item.corner: item for item in report.offense}
    # The local player: every game-detected swing is kept, and 9 of 49 contact stamps are strikes.
    assert by_corner[1].kinematic_thrown == 61
    assert by_corner[1].contact_thrown == 9
    assert by_corner[1].discarded_records == 40
    assert 35 < by_corner[1].punches_per_minute < 45
    # The AI track only has contact stamps. Blocks and glove clashes are left out.
    assert by_corner[2].kinematic_thrown == 0
    assert by_corner[2].contact_thrown == 24
    assert by_corner[2].discarded_records == 78
    assert sum(1 for punch in by_corner[2].punches if punch.landed) == 16
    thrown = next(note for note in report.decode_status if note.field == "offense.thrown")
    assert thrown.confidence == "inferred"
    assert "4.0 m/s" in thrown.note and "scored hit" in thrown.note and "discarded_records" in thrown.note
    assert sum(1 for punch in by_corner[1].punches if punch.landed) == 31

    defense = {item.corner: item for item in report.defense}
    for corner in (1, 2):
        assert defense[corner].guard_up_percent is not None
        assert 1.0 < defense[corner].guard_up_percent < 99.0
        assert defense[corner].guard_up_percent_under_fire is not None
        assert defense[corner].head_mean_speed is not None
        assert defense[corner].head_mean_speed_under_fire is not None
        assert defense[corner].under_fire_seconds > 0
    assert defense[1].received_damage_official == 134
    assert defense[2].received_damage_official == 1032

    types = {moment.type for moment in report.key_moments}
    assert {"stun", "knockdown", "knockout", "exchange", "punishment_spike", "high_velocity_landed"} <= types
    assert sum(1 for moment in report.key_moments if moment.type == "stun") == 4
    names = {series.name for series in report.series}
    assert {"punishment_0", "guard_up", "head_speed", "punch_density", "guard_brace"} <= names
    assert all(len(series.t) == len(series.y) and series.t for series in report.series)
    fields = " ".join(note.field for note in report.decode_status)
    assert "advice" not in fields and "improve" not in fields
    landed = next(note for note in report.decode_status if note.field == "offense.landed")
    assert landed.confidence == "confirmed"


def test_mcp_tools():
    from totf_analyzer.mcp_server import server

    server.configure(ROOT / "Recordings")
    listing = server.list_recordings()
    assert any(row["name"] == SAMPLE.name for row in listing)
    stats = server.get_fighter_stats(SAMPLE.name, 1)
    assert stats["offense"]["landed"] == 33
    assert stats["defense"]["received_damage_official"] == 134
    knockouts = server.get_key_moments(str(SAMPLE), "knockout")
    assert len(knockouts) == 1
    assert knockouts[0]["corners"] == [2]
    series = server.get_series(SAMPLE.name, "head_speed", 1)
    assert len(series) == 1
    assert series[0]["t"]


def test_api_lists_and_analyzes_sample():
    client = TestClient(create_app(ROOT / "Recordings"))
    listing = client.get("/api/sessions")
    assert listing.status_code == 200
    row = next(item for item in listing.json() if item["name"] == SAMPLE.name)
    assert row["bout"] == "3x2"
    assert row["created"] == "2026-11-15T03:48:37.963Z"
    assert row["red"] and row["blue"]
    assert row["red"] != row["blue"]
    assert row["winner"] == "blue"
    assert row["local"] == "blue"
    assert row["method"] == "KO"
    assert row["result"] == "W-KO"
    report = client.get(f"/api/sessions/{SAMPLE.name}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["offense"][0]["official_hits"] in (17, 33)
    assert body["session"]["method"] == "knockout"
    finished = [rnd for rnd in body["rounds"] if rnd["completed"]]
    assert len(finished) == 1
    assert finished[0]["offense"][0]["landed"] in (17, 33)


GAME_DECISION = _recording(
    Path.home()
    / ".local/share/Steam/steamapps/compatdata/3279600/pfx/drive_c/users/steamuser"
    / "AppData/LocalLow/Halfbrick Studios/The Thrill of the Fight 2/SessionRecordings",
    "20261115_055310",
)


@pytest.mark.skipif(not GAME_DECISION.is_file(), reason="three-round recording is not on this machine")
def test_decision_splits_into_three_rounds():
    report = build_analytics(load_session(GAME_DECISION))
    completed = [rnd for rnd in report.rounds if rnd.completed]
    assert len(completed) == 3
    fight_thrown = {item.corner: item.thrown for item in report.offense}
    summed = {corner: 0 for corner in fight_thrown}
    for rnd in completed:
        assert rnd.duration_sec == pytest.approx(120, abs=1)
        by_corner = {item.corner: item for item in rnd.offense}
        assert by_corner[1].landed == rnd.red.hits
        assert by_corner[2].landed == rnd.blue.hits
        for corner, item in by_corner.items():
            summed[corner] += item.thrown
        for series in rnd.series:
            if series.t:
                assert min(series.t) >= -8
                assert max(series.t) <= (rnd.duration_sec or 0) + 3
    assert summed == fight_thrown
