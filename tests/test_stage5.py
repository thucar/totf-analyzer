"""Combination depth, pattern damage, and counter-window shares."""

from pathlib import Path

import pytest

from totf_analyzer.analytics.metrics import build_analytics
from totf_analyzer.parser.session import COLOR_CORNER, load_session

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "Recordings"


def _recording(stamp: str) -> Path:
    matches = sorted(RECORDINGS.glob(f"*_{stamp}.zip"))
    if matches:
        return matches[0]
    return RECORDINGS / f"session_{stamp}.zip"


THREE_ROUNDS = _recording("20261115_061911")
WINDOWS = ("while_throwing", "post_punch_recovery", "neutral_guard")
DEPTHS = ("1", "2", "3", "4", "5+")


def _report(path: Path):
    assert path.is_file(), path
    return build_analytics(load_session(path))


def _hits(report, corner: int) -> int:
    color = "red" if corner == COLOR_CORNER["red"] else "blue"
    # Hits taken include stuns and knockdown blows, which m_hits leaves out.
    return sum(
        getattr(rnd, color).hits
        + getattr(rnd, color).stuns
        + getattr(rnd, color).punishment_stuns
        + getattr(rnd, color).all_knockdowns
        for rnd in report.rounds
        if rnd.completed
    )


def test_depth_and_patterns_partition_thrown_punches():
    report = _report(THREE_ROUNDS)
    for offense in report.offense:
        combos = offense.combinations
        combo_punches = [punch for punch in offense.punches if not punch.graze]
        grazes = [punch for punch in offense.punches if punch.graze]
        assert grazes
        assert all(punch.combo_id is None and punch.combo_depth is None and not punch.countered for punch in grazes)
        assert [row.depth for row in combos.by_depth] == list(DEPTHS)
        assert sum(row.thrown for row in combos.by_depth) == len(combo_punches)
        assert sum(row.landed for row in combos.by_depth) == sum(1 for punch in combo_punches if punch.landed)
        assert sum(row.thrown for row in combos.patterns) == len(combo_punches)
        assert combos.patterns == sorted(combos.patterns, key=lambda row: (-row.count, row.pattern))
        assert all("unknown" not in pattern.pattern for pattern in combos.patterns)
        assert combos.combo_count > 0
        assert combos.mean_combo_length is not None and combos.max_combo_length >= combos.mean_combo_length
        assert 0.0 <= combos.single_shot_percent <= 100.0
        if combos.alternating_hand_percent is not None:
            assert 0.0 <= combos.alternating_hand_percent <= 100.0
        for row in combos.by_depth:
            if row.thrown:
                assert row.accuracy == pytest.approx(row.landed / row.thrown)
                assert row.countered_rate == pytest.approx(row.countered_count / row.thrown)
            else:
                assert row.accuracy is None and row.countered_rate is None
        for pattern in combos.patterns:
            assert pattern.count >= 1
            assert pattern.thrown == pattern.count * pattern.length
            assert pattern.accuracy == pytest.approx(pattern.landed / pattern.thrown)
            assert pattern.mean_damage is not None
            assert pattern.mean_damage >= 0.0
            if pattern.landed == 0:
                assert pattern.mean_damage_landed is None
                assert pattern.mean_damage == 0.0


def test_round_combo_counts_sum_to_the_fight():
    report = _report(THREE_ROUNDS)
    for offense in report.offense:
        total = 0
        thrown = 0
        for rnd in report.rounds:
            if not rnd.completed or not rnd.offense:
                continue
            block = next(row.combinations for row in rnd.offense if row.corner == offense.corner)
            total += block.combo_count
            thrown += sum(row.thrown for row in block.patterns)
        assert offense.combinations.combo_count == total
        assert sum(row.thrown for row in offense.combinations.patterns) == thrown
        assert sum(1 for punch in offense.punches if not punch.graze) == thrown


def test_vulnerability_hits_match_the_scorecard_and_risk_ratio():
    report = _report(THREE_ROUNDS)
    for defense in report.defense:
        windows = [getattr(defense.vulnerability, name) for name in WINDOWS]
        assert sum(window.hits for window in windows) == _hits(report, defense.corner)
        shares = [window.hit_share for window in windows]
        assert all(share is not None for share in shares)
        assert sum(shares) == pytest.approx(100.0)
        time_shares = [window.time_share for window in windows]
        assert all(share is not None for share in time_shares)
        assert sum(time_shares) == pytest.approx(100.0)
        for window in windows:
            assert window.time_share > 0
            assert window.risk_ratio == pytest.approx(window.hit_share / window.time_share)
            if window.opponent_thrown:
                assert window.opponent_accuracy == pytest.approx(window.opponent_landed / window.opponent_thrown)
        opponent = next(item for item in report.offense if item.corner != defense.corner)
        assert sum(window.opponent_thrown for window in windows) == opponent.thrown
        for rnd in report.rounds:
            if not rnd.completed or not rnd.defense:
                continue
            block = next(row.vulnerability for row in rnd.defense if row.corner == defense.corner)
            color = "red" if defense.corner == COLOR_CORNER["red"] else "blue"
            card = getattr(rnd, color)
            taken = card.hits + card.stuns + card.punishment_stuns + card.all_knockdowns
            assert sum(getattr(block, name).hits for name in WINDOWS) == taken


def test_local_player_depth_and_hit_shares_on_061911():
    """Local fighter on this zip, grouping non-graze counted punches on launch ticks.

    Issue #1 sketched 51.7%, 53.1%, and 16.7% depth accuracy and 84.8/6.3/8.9 hit
    shares from an earlier pass. Those figures are not what this launch-gap
    definition produces, so the test locks the measured values instead.
    Contact records that are not strikes are left out of thrown, and low-damage
    rescued slow contacts (grazes) stay in thrown/landed but out of combo chains.
    """
    report = _report(THREE_ROUNDS)
    local = next(fighter for fighter in report.fighters if fighter.is_local_player)
    offense = next(item for item in report.offense if item.corner == local.corner)
    depth = {row.depth: row for row in offense.combinations.by_depth}
    assert depth["1"].accuracy == pytest.approx(96 / 144)
    assert depth["2"].accuracy == pytest.approx(81 / 116)
    assert depth["3"].accuracy == pytest.approx(22 / 52)
    vulnerability = next(item.vulnerability for item in report.defense if item.corner == local.corner)
    assert vulnerability.while_throwing.hit_share == pytest.approx(100 * 42 / 85)
    assert vulnerability.post_punch_recovery.hit_share == pytest.approx(100 * 23 / 85)
    assert vulnerability.neutral_guard.hit_share == pytest.approx(100 * 20 / 85)
    assert any(pattern.count >= 2 and pattern.mean_damage > 0 for pattern in offense.combinations.patterns)
    assert offense.thrown == 336 and offense.kinematic_thrown == 308 and offense.discarded_records == 291
    assert sum(1 for punch in offense.punches if punch.graze) == 11
    assert offense.combinations.max_combo_length == 6
    opponent = next(item for item in report.offense if item.corner != local.corner)
    assert opponent.thrown == 131 and opponent.kinematic_thrown == 0 and opponent.discarded_records == 485
    assert sum(1 for punch in opponent.punches if punch.graze) == 18
    # The opponent's 80 scored hits plus the 5 blows that stunned the local fighter.
    assert opponent.landed == 85 and opponent.official_hits == 80
    stuns = [moment for moment in report.key_moments if moment.type == "stun"]
    assert len(stuns) == 5 and all(moment.corners == [local.corner] for moment in stuns)
    assert opponent.combinations.max_combo_length == 3


@pytest.mark.parametrize("stamp", ["20261124_054822", "20261124_060157", "20261124_060913"])
def test_schema16_combinations_exclude_grazes_and_classify_followups(stamp: str):
    path = _recording(stamp)
    if not path.is_file():
        pytest.skip(f"{stamp} recording is not on this machine")
    report = _report(path)
    for offense in report.offense:
        assert all("unknown" not in pattern.pattern for pattern in offense.combinations.patterns)
        non_grazes = [punch for punch in offense.punches if not punch.graze]
        grazes = [punch for punch in offense.punches if punch.graze]
        assert sum(row.thrown for row in offense.combinations.by_depth) == len(non_grazes)
        assert all(punch.combo_id is None and punch.combo_depth is None for punch in grazes)
        assert all(punch.combo_id is not None and punch.combo_depth is not None for punch in non_grazes)


def test_combination_decode_notes():
    report = _report(THREE_ROUNDS)
    combos = next(item for item in report.decode_status if item.field == "offense.combinations")
    vulnerability = next(item for item in report.decode_status if item.field == "defense.vulnerability")
    assert combos.confidence == "inferred"
    assert vulnerability.confidence == "inferred"
    assert "0.65" in combos.note and "m_receivedDamage" in combos.note
    assert "0.15" in vulnerability.note and "0.60" in vulnerability.note and "risk_ratio" in vulnerability.note


def test_fighter_stats_include_round_combinations():
    from totf_analyzer.mcp_server import server

    report = _report(THREE_ROUNDS)
    local = next(fighter for fighter in report.fighters if fighter.is_local_player)
    server.configure(RECORDINGS)
    stats = server.get_fighter_stats(THREE_ROUNDS.name, local.corner)
    assert stats["offense"]["combinations"]["combo_count"] > 0
    assert stats["defense"]["vulnerability"]["while_throwing"]["hits"] >= 0
    completed = next(row for row in stats["rounds"] if row["completed"] and "offense" in row)
    assert "patterns" in completed["offense"]["combinations"]
    assert "while_throwing" in completed["defense"]["vulnerability"]
