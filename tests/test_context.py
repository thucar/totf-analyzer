"""Contextual fight analytics tests: stun, punishment/hurt, range zone, engagement, PunchRow tags, series, and MCP."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from totf_analyzer.analytics.metrics import STUN_DURATION_SEC, _stun_mask, build_analytics
from totf_analyzer.mcp_server import server
from totf_analyzer.parser.session import load_session
from totf_analyzer.parser.t2sr import HIT_KIND_PUNISHMENT_STUN, HIT_KIND_STUN, SCORED_HIT_TYPE, EventRecord

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "Recordings"


def _recording(stamp: str) -> Path:
    matches = sorted(RECORDINGS.glob(f"*_{stamp}.zip"))
    if matches:
        return matches[0]
    return RECORDINGS / f"session_{stamp}.zip"


SAMPLE = _recording("20261115_054837")
SELF_STUN_BOUT = _recording("20261115_060819")
THREE_ROUNDS = _recording("20261115_061911")
TKO_BOUT = _recording("20261124_060157")
OPP_STUN_BOUT = _recording("20261124_060913")


def test_stun_mask_is_strictly_after_event_and_clipped_to_fighting_span():
    dt = 1.0 / 120.0
    ticks = np.arange(1000, 2200, dtype=np.int64)
    # Fighting span 1 ends at 1400 (e.g. knockdown count 1400..1700), span 2 resumes at 1700..2199.
    spans = [(1000, 1400), (1700, 2199)]
    events = [
        EventRecord(tick=1200, type_code=SCORED_HIT_TYPE, subtype=1, scored_hit=False, hit_kind=HIT_KIND_STUN),
        EventRecord(tick=1750, type_code=SCORED_HIT_TYPE, subtype=1, scored_hit=False, hit_kind=HIT_KIND_PUNISHMENT_STUN),
    ]
    mask = _stun_mask(ticks, events, spans, dt)
    # Impact tick itself is NOT stunned (blow is attributed to the pre-stun state).
    assert not mask[1200 - 1000]
    assert mask[1201 - 1000]
    # Clipped at span 1 end (1400), not bleeding into 1401..1680.
    assert mask[1400 - 1000]
    assert not mask[1401 - 1000]
    assert not mask[1699 - 1000]
    # Second stun runs strictly after 1750 for exactly STUN_DURATION_SEC (480 ticks -> 2230, clipped at 2199).
    assert not mask[1750 - 1000]
    assert mask[1751 - 1000]
    assert mask[2199 - 1000]

    # Unclipped 4.0 s duration check on a long span.
    long_ticks = np.arange(0, 1000, dtype=np.int64)
    long_mask = _stun_mask(
        long_ticks,
        [EventRecord(tick=100, type_code=SCORED_HIT_TYPE, subtype=1, scored_hit=False, hit_kind=HIT_KIND_STUN)],
        [(0, 999)],
        dt,
    )
    expected_ticks = int(round(STUN_DURATION_SEC / dt))
    assert int(long_mask.sum()) == expected_ticks
    assert not long_mask[100]
    assert long_mask[101]
    assert long_mask[100 + expected_ticks]
    assert not long_mask[100 + expected_ticks + 1]


@pytest.mark.skipif(not SAMPLE.is_file(), reason="sample recording is not on this machine")
def test_parser_extracts_punishment_config_and_context_partitions_sum_to_100():
    session = load_session(SAMPLE)
    for track in session.tracks.values():
        assert track.mid_punishment_capacity is not None and track.mid_punishment_capacity > 0
        assert track.mid_punishment_critical_threshold is not None
        assert 0.0 < track.mid_punishment_critical_threshold <= 1.0
        assert track.breathing_threshold is not None

    report = build_analytics(session)
    assert len(report.context) == 2

    for ctx in report.context:
        for dim_name in ("by_stun_state", "by_punishment_state", "by_range_zone", "by_engagement_state"):
            buckets = getattr(ctx, dim_name)
            assert buckets, dim_name
            total_share = sum(b.time_share or 0.0 for b in buckets)
            assert total_share == pytest.approx(100.0, abs=0.05), (ctx.corner, dim_name, total_share)

        # Thrown and hits_taken sums must agree across all four mutually exclusive partitions.
        thrown_totals = {
            sum(b.thrown for b in getattr(ctx, dim))
            for dim in ("by_stun_state", "by_punishment_state", "by_range_zone", "by_engagement_state")
        }
        hits_totals = {
            sum(b.hits_taken for b in getattr(ctx, dim))
            for dim in ("by_stun_state", "by_punishment_state", "by_range_zone", "by_engagement_state")
        }
        assert len(thrown_totals) == 1
        assert len(hits_totals) == 1

    # Corner 1 (local player) stunned Red (corner 2) 7 times -> opponent_stunned time > 0 for corner 1,
    # self_stunned time > 0 for corner 2.
    c1 = next(c for c in report.context if c.corner == 1)
    c2 = next(c for c in report.context if c.corner == 2)
    c1_opp_stun = next(b for b in c1.by_stun_state if b.state == "opponent_stunned")
    c2_self_stun = next(b for b in c2.by_stun_state if b.state == "self_stunned")
    assert c1_opp_stun.time_sec > 15.0
    assert c1_opp_stun.thrown > 0
    assert c1_opp_stun.guard_up_percent is not None
    assert c2_self_stun.time_sec == pytest.approx(c1_opp_stun.time_sec, abs=0.2)

    # Range zone guard separation: outside guard > clinch guard on corner 1.
    c1_range = {b.state: b for b in c1.by_range_zone}
    assert c1_range["outside"].guard_up_percent is not None
    assert c1_range["clinch"].guard_up_percent is not None
    assert c1_range["outside"].guard_up_percent > c1_range["clinch"].guard_up_percent

    # Completed round carries context too.
    completed = [r for r in report.rounds if r.completed]
    assert completed and len(completed[0].context) == 2

    # PunchRow carries hit_kind (including KD and KO) and launch-state context tags.
    off1 = next(o for o in report.offense if o.corner == 1)
    assert any(p.hit_kind == "stun" for p in off1.punches)
    assert any(p.hit_kind == "punishment_stun" for p in off1.punches)
    assert any(p.hit_kind == "punishment_knockdown" for p in off1.punches)
    assert any(p.hit_kind == "knockout" for p in off1.punches)
    assert any(p.opponent_stunned for p in off1.punches)
    assert all(p.range_zone in {"outside", "pocket", "clinch"} for p in off1.punches if p.fighter_distance_m is not None)
    assert all(p.hit_kind is None for p in off1.punches if not p.landed)

    # New series channels: stunned in [0, 1] and punishment_ratio in [0, 1.05].
    for name in ("stunned", "punishment_ratio"):
        rows = [s for s in report.series if s.name == name]
        assert len(rows) == 2
        for s in rows:
            assert s.t and len(s.t) == len(s.y)
            assert all(math.isfinite(v) and 0.0 <= v <= 1.05 for v in s.y)
    c2_stun_series = next(s for s in report.series if s.name == "stunned" and s.corner == 2)
    assert max(c2_stun_series.y) == pytest.approx(1.0)


@pytest.mark.skipif(not SELF_STUN_BOUT.is_file(), reason="060819 recording is not on this machine")
def test_self_stun_context_and_cause_attribution():
    report = build_analytics(load_session(SELF_STUN_BOUT))
    # Corner 1 (thucar) took 5 stuns in 060819.
    c1 = next(c for c in report.context if c.corner == 1)
    by_stun = {b.state: b for b in c1.by_stun_state}
    assert by_stun["self_stunned"].time_sec == pytest.approx(20.0, abs=0.5)
    assert by_stun["self_stunned"].guard_up_percent is not None
    # Because stun mask starts strictly after event.tick, the stun-causing blows are attributed to neutral (not self_stunned).
    assert by_stun["neutral"].stuns_taken == 5
    assert by_stun["self_stunned"].stuns_taken == 0


@pytest.mark.skipif(not TKO_BOUT.is_file(), reason="060157 TKO recording is not on this machine")
def test_tko_and_knockdown_punch_markers():
    report = build_analytics(load_session(TKO_BOUT))
    assert report.session.method == "technical_knockout"
    off2 = next(o for o in report.offense if o.corner == 2)
    kd_punches = [p for p in off2.punches if p.hit_kind == "punishment_knockdown"]
    tko_punches = [p for p in off2.punches if p.hit_kind == "tko"]
    assert len(kd_punches) == 3
    assert len(tko_punches) == 1
    assert tko_punches[0].impact_sec == pytest.approx(315.83, abs=0.05)
    # Timeline knockdown count now matches all_knockdowns (4) and includes a tko stoppage moment.
    kd_moments = [m for m in report.key_moments if m.type == "knockdown"]
    assert len(kd_moments) == 4
    assert any(m.detail.get("hit_kind") == "tko" for m in kd_moments)
    assert any(m.type == "tko" and m.corners == [1] for m in report.key_moments)
    kd_note = next(n for n in report.decode_status if n.field == "timeline.knockdown")
    assert kd_note.confidence == "confirmed"


@pytest.mark.skipif(not OPP_STUN_BOUT.is_file(), reason="060913 recording is not on this machine")
def test_opponent_stunned_guard_and_punishment_rate():
    report = build_analytics(load_session(OPP_STUN_BOUT))
    # Local player is corner 2 (red) in 060913.
    local_corner = next(f.corner for f in report.fighters if f.is_local_player)
    ctx = next(c for c in report.context if c.corner == local_corner)
    by_stun = {b.state: b for b in ctx.by_stun_state}
    assert by_stun["opponent_stunned"].time_sec == pytest.approx(12.0, abs=0.5)
    assert by_stun["opponent_stunned"].hits_taken > 0
    assert by_stun["opponent_stunned"].hits_taken_per_minute is not None
    assert by_stun["neutral"].guard_up_percent is not None
    assert by_stun["opponent_stunned"].guard_up_percent is not None


@pytest.mark.skipif(not THREE_ROUNDS.is_file(), reason="061911 recording is not on this machine")
def test_mcp_context_tools_and_payload_budgets():
    server.configure(RECORDINGS)

    # Default analyze_recording omits context and stays under 80 KB.
    compact = server.analyze_recording(THREE_ROUNDS.name)
    assert "context" not in compact
    assert all("context" not in rnd for rnd in compact["rounds"])
    assert len(json.dumps(compact)) < 80_000

    # include_context=True restores fight and round context.
    with_ctx = server.analyze_recording(THREE_ROUNDS.name, include_context=True)
    assert len(with_ctx["context"]) == 2
    completed = [r for r in with_ctx["rounds"] if r["completed"]]
    assert all(len(r["context"]) == 2 for r in completed)

    # get_fighter_stats includes fight-level context by default and stays well under 80 KB.
    fighter = server.get_fighter_stats(THREE_ROUNDS.name, 2)
    assert "context" in fighter
    assert fighter["context"]["corner"] == 2
    assert len(json.dumps(fighter)) < 80_000
    assert all("context" not in r for r in fighter["rounds"])

    fighter_with_rounds = server.get_fighter_stats(THREE_ROUNDS.name, 2, include_round_context=True)
    assert all("context" in r for r in fighter_with_rounds["rounds"] if r["completed"])

    # Dedicated get_context_stats supports corner and round_index filtering.
    both = server.get_context_stats(THREE_ROUNDS.name)
    assert len(both) == 2
    one = server.get_context_stats(THREE_ROUNDS.name, corner=2)
    assert len(one) == 1 and one[0]["corner"] == 2
    rnd0 = server.get_context_stats(THREE_ROUNDS.name, corner=2, round_index=0)
    assert len(rnd0) == 1 and rnd0[0]["corner"] == 2
    assert sum(b["time_sec"] for b in rnd0[0]["by_stun_state"]) < sum(
        b["time_sec"] for b in one[0]["by_stun_state"]
    )

    # get_series returns stunned and punishment_ratio.
    for name in ("stunned", "punishment_ratio"):
        series = server.get_series(THREE_ROUNDS.name, name, corner=2)
        assert len(series) == 1 and series[0]["t"]

    with pytest.raises(ValueError):
        server.get_context_stats(THREE_ROUNDS.name, corner=99)
    with pytest.raises(ValueError):
        server.get_context_stats(THREE_ROUNDS.name, round_index=99)
