"""Cross-stream fight metrics. Numbers and timestamps only."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace

import numpy as np

from totf_analyzer.models.analytics import (
    CombinationStats,
    ComboPatternStats,
    CornerRound,
    DecodeNote,
    DefenseStats,
    DepthStats,
    DirectnessRatio,
    DistanceSpread,
    FightAnalytics,
    Fighter,
    FootworkStats,
    GuardDisciplineStats,
    HandStats,
    HeadMovementStats,
    HistogramBin,
    KeyMoment,
    MedianP90,
    OffenseStats,
    PunchRow,
    RetractionDroop,
    RetractionTime,
    RoundScore,
    Series,
    SessionFacts,
    SlipSpread,
    TrajectoryStats,
    VelocityStats,
    VulnerabilityStats,
    VulnerabilityWindow,
)
from totf_analyzer.parser.session import COLOR_CORNER, CORNER_COLOR, ParsedSession, TrackData
from totf_analyzer.parser.t2sr import (
    CHEST,
    HAND_LABEL,
    HIT_KIND_KNOCKDOWN,
    HIT_KIND_LABEL,
    HIT_KIND_PUNISHMENT_KNOCKDOWN,
    HIT_KIND_PUNISHMENT_STUN,
    HIT_KIND_STUN,
    HEAD,
    HIPS,
    L_ANKLE,
    L_ELBOW,
    L_SHOULDER,
    L_WRIST,
    PHASE_EVENT_TYPE,
    PHASE_FIGHT,
    PHASE_FIGHT_OVER,
    PHASE_KNOCKDOWN,
    PHASE_KNOCKDOWN_FINAL,
    PHASE_ROUND_END,
    PUNCH_CLASS_LABEL,
    R_ANKLE,
    R_ELBOW,
    R_SHOULDER,
    R_WRIST,
    SPINE,
    EventRecord,
    PunchRecord,
)

# Hands count as "up" when both are within these distances of the head joint.
GUARD_DY_MAX = 0.38
GUARD_HORIZ_MAX = 0.40
# Tighter box for the non-punching glove at the punching hand's peak extension.
OFFHAND_DY_MAX = 0.28
OFFHAND_HORIZ_MAX = 0.38
# Return-to-guard is measured from peak extension until this deadline.
RETRACTION_WINDOW_SEC = 0.800
SAG_DROOP_M = 0.10
# Opponent punch records mark the surrounding ticks as under fire.
UNDER_FIRE_BEFORE = 6
UNDER_FIRE_AFTER = 36
# A hit with no punch record sharing its contact point links to a punch when it falls in
# [launch_tick - lead, end_tick + lag].
HIT_LAUNCH_LEAD = 6
HIT_END_LAG = 12
# Launch-to-peak wrist displacement, as a unit vector in the opponent frame.
UPPERCUT_UP = 0.45
OVERHAND_DOWN = -0.35
HOOK_LATERAL = 0.40
STRAIGHT_FORWARD = 0.25
MIN_EXTENSION_M = 0.02
MIN_SKELETON_FRAMES = 3
# A contact record (byte 9 != 0) is a fixed 12-tick glove-contact stamp, not a detected swing.
# It counts as a punch when the glove was closing on the opponent's head or trunk at least this
# fast just before the contact, and it is not a second contact of a swing already counted.
CONTACT_LOOKBACK_SEC = 0.15
CONTACT_LOOKAHEAD_SEC = 0.033
CONTACT_SMOOTH_TICKS = 3
CONTACT_CLOSING_MIN = 4.0
SAME_SWING_GRACE_SEC = 0.10
# A slower contact record still counts when a hit taken by the opponent, not already
# explained by a counted punch, falls this close to its contact tick.
SCORED_CONTACT_BEFORE_SEC = 0.025
SCORED_CONTACT_AFTER_SEC = 0.05
TARGET_JOINTS = (HEAD, CHEST, SPINE, HIPS)
SPEED_BINS = (0.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 30.0)
SERIES_STEP_SEC = 0.25
HEAD_DROP_METERS = 0.28
HEAD_DROP_TICKS = 48
HEAD_SPEED_CAP = 5.0
EXCHANGE_MIN_EACH = 2
# A round start is two type-5 events this many ticks apart: the warning, then the bell.
ROUND_START_GAP = 735
# The end bell lands a few ticks after round_duration / fixed_timestep.
END_BELL_TOLERANCE = 12
# Punches that land just after the bell still belong to the round.
BELL_GRACE_TICKS = 240
# Footwork uses the official bell span, not the warning or the post-bell grace.
CLINCH_RANGE_M = 0.85
POCKET_RANGE_M = 1.35
SQUARE_BLADE_DEG = 15.0
ANGLE_CUT_DEG = 20.0
ANGLE_CUT_SEC = 0.75
ANGLE_CUT_RANGE_M = 1.8
COMBO_GAP_SEC = 0.65
COMBO_EXIT_SEC = 0.5
# Counter windows are measured from launch_tick. Throwing wins over recovery.
THROW_WINDOW_SEC = 0.15
RECOVERY_WINDOW_SEC = 0.60
DEPTH_LABELS = ("1", "2", "3", "4", "5+")
# These trajectory names already say which hand threw. The others get a hand prefix.
HAND_NAMED_TRAJECTORIES = frozenset({"jab", "cross", "left_hook", "right_hook"})
VULNERABILITY_WINDOWS = ("while_throwing", "post_punch_recovery", "neutral_guard")
MIN_RANGE_M = 1.0e-3
MIN_LINE_M = 1.0e-4
# Head slip is measured on the same bell span and opponent frame as footwork.
OFF_CENTERLINE_M = 0.10
DUCK_DROP_M = 0.15
DUCK_WINDOW_SEC = 0.8
WEAVE_DROP_M = 0.12
WEAVE_SLIP_M = 0.12
WEAVE_WINDOW_SEC = 1.0

# Event type codes whose counts line up with scorecard totals on schema 15.
SPEED_SMOOTH_TICKS = 3
RESULT_EVENT_TYPE = 6


def build_analytics(session: ParsedSession) -> FightAnalytics:
    notes: list[DecodeNote] = []
    session = _validated_punches(session)
    rounds = _rounds(session)
    totals = _score_totals(rounds)
    fighters = [_fighter(track, notes) for track in _ordered(session)]
    labels = {corner: _hand_labels(track, notes, session.fixed_timestep) for corner, track in session.tracks.items()}
    windows = _round_windows(session)
    active = _within_windows(session, windows)
    pace = sum(window.duration_sec for window in windows) if windows else None
    offense, defense, moments, series = _measure(
        active,
        labels,
        totals,
        notes,
        pace_sec=pace,
        clock_ticks=_clock_ticks(windows),
        windows=windows,
    )
    _attach_rounds(session, rounds, labels, windows)
    notes.extend(_static_notes())
    return FightAnalytics(
        session=_session_facts(session, totals),
        fighters=fighters,
        rounds=rounds,
        offense=offense,
        defense=defense,
        key_moments=moments,
        series=series,
        decode_status=notes,
    )


def _measure(
    session: ParsedSession,
    labels: dict[int, dict[int, str]],
    totals: dict[int, dict],
    notes: list[DecodeNote],
    pace_sec: float | None = None,
    clock_ticks: set[int] | None = None,
    windows: list[_RoundWindow] | None = None,
) -> tuple[list[OffenseStats], list[DefenseStats], list[KeyMoment], list[Series]]:
    bodies = {corner: _body(track) for corner, track in session.tracks.items()}
    landed_events = {
        corner: [event for event in track.events if event.landed_hit]
        for corner, track in session.tracks.items()
    }
    _note_scored_hits(landed_events, totals, notes)
    matches: dict[int, dict[int, EventRecord]] = {}
    for corner, track in session.tracks.items():
        defender = _opponent(session, corner)
        matches[corner] = _match_punches(track.punches, landed_events[defender])
    punch_guards = {
        corner: _punch_guard(track, session.tracks[_opponent(session, corner)], session.fixed_timestep)
        for corner, track in session.tracks.items()
    }
    offense = [
        _offense(
            session,
            track,
            labels[track.corner],
            matches[track.corner],
            landed_events,
            totals,
            notes,
            punch_guards[track.corner],
            pace_sec=pace_sec,
        )
        for track in _ordered(session)
    ]
    spans = _bell_spans(windows or [])
    footwork: dict[int, tuple[FootworkStats, list[_AngleCut]]] = {
        track.corner: _footwork(track, session.tracks[_opponent(session, track.corner)], spans, session.fixed_timestep)
        for track in _ordered(session)
    }
    movement: dict[int, tuple[HeadMovementStats, list[_HeadEvent], list[_HeadEvent]]] = {
        track.corner: _head_movement(
            session,
            track,
            session.tracks[_opponent(session, track.corner)],
            spans,
            session.fixed_timestep,
        )
        for track in _ordered(session)
    }
    defense = [
        _defense(
            session,
            track,
            bodies[track.corner],
            totals,
            notes,
            punch_guards[track.corner],
            footwork[track.corner][0],
            movement[track.corner][0],
        )
        for track in _ordered(session)
    ]
    moments = _key_moments(session, matches, bodies, totals, notes, clock_ticks)
    moments.extend(_angle_cut_moments(session, {corner: cuts for corner, (_stats, cuts) in footwork.items()}))
    moments.extend(_head_event_moments(session, {corner: ducks for corner, (_stats, ducks, _weaves) in movement.items()}, "duck"))
    moments.extend(
        _head_event_moments(
            session,
            {corner: weaves for corner, (_stats, _ducks, weaves) in movement.items()},
            "bob_and_weave",
        )
    )
    moments.sort(key=lambda item: (item.t_sec, item.type))
    _attach_combinations(session, offense, defense, landed_events, matches, windows or [])
    return (
        offense,
        defense,
        moments,
        _series(session, bodies),
    )


def _ordered(session: ParsedSession) -> list[TrackData]:
    return [session.tracks[corner] for corner in sorted(session.tracks)]


def _opponent(session: ParsedSession, corner: int) -> int:
    others = [item for item in session.tracks if item != corner]
    if len(others) != 1:
        raise ValueError("analytics expects exactly two fighters")
    return others[0]


def _sec(session: ParsedSession, tick: int) -> float:
    return round((tick - session.start_tick) * session.fixed_timestep, 4)


def _finite(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _ratio(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return num / den


def _fighter(track: TrackData, notes: list[DecodeNote]) -> Fighter:
    if track.stance and not track.stance_confirmed:
        notes.append(
            DecodeNote(
                field=f"fighter.{track.corner}.stance",
                confidence="inferred",
                note="Body-stance code 1 is orthodox on the AI track that publishes the stance name.",
            )
        )
    return Fighter(
        corner=track.corner,
        color=track.color,
        name=track.name,
        track_folder=track.folder,
        is_local_player=track.is_local_player,
        stance=track.stance,
        height_m=track.height_m,
        ai_archetype=track.ai_archetype,
        ai_difficulty=track.ai_difficulty,
    )


def _session_facts(session: ParsedSession, totals: dict[int, dict]) -> SessionFacts:
    meta = session.metadata
    venue = meta.get("m_venue") or {}
    scoring = meta.get("m_scoring") or {}
    method, winner = _result(totals)
    return SessionFacts(
        name=str(meta.get("m_name") or session.path.stem),
        source=session.path.name,
        fight_id=meta.get("m_fightId"),
        created_utc=meta.get("m_createdUtc"),
        app_version=meta.get("m_appVersion"),
        venue=venue.get("m_venueName"),
        rounds_scheduled=int(venue.get("m_rounds") or len(session.metadata["m_scoring"]["m_rounds"])),
        round_duration_sec=float(venue.get("m_roundDurationSeconds") or 0),
        break_duration_sec=float(venue.get("m_roundBreakDurationSeconds") or 0),
        ring_size_x_m=_finite(float(venue["m_ringBoundsSizeX"])) if venue.get("m_ringBoundsSizeX") else None,
        ring_size_z_m=_finite(float(venue["m_ringBoundsSizeZ"])) if venue.get("m_ringBoundsSizeZ") else None,
        duration_sec=round(session.duration_sec, 4),
        fixed_timestep=session.fixed_timestep,
        start_tick=session.start_tick,
        end_tick=session.end_tick,
        method=method,
        winner_corner=winner,
        winner_color=CORNER_COLOR.get(winner) if winner is not None else None,
        red_total_score=scoring.get("m_redTotalScore"),
        blue_total_score=scoring.get("m_blueTotalScore"),
    )


def _result(totals: dict[int, dict]) -> tuple[str, int | None]:
    knocked = [corner for corner, row in totals.items() if row["knocked_out"]]
    technical = [corner for corner, row in totals.items() if row["technically_knocked_out"]]
    if len(knocked) == 1:
        return "knockout", _other_corner(knocked[0], totals)
    if len(technical) == 1:
        return "technical_knockout", _other_corner(technical[0], totals)
    red = totals.get(COLOR_CORNER["red"], {}).get("score", 0)
    blue = totals.get(COLOR_CORNER["blue"], {}).get("score", 0)
    if red == blue:
        return "decision", None
    return "decision", COLOR_CORNER["red"] if red > blue else COLOR_CORNER["blue"]


def _other_corner(corner: int, totals: dict[int, dict]) -> int | None:
    others = [item for item in totals if item != corner]
    return others[0] if len(others) == 1 else None


def _foul_count(fouls: object) -> int:
    if isinstance(fouls, dict):
        return int(sum(value for value in fouls.values() if isinstance(value, (int, float))))
    return 0


def _corner_round(raw: dict) -> CornerRound:
    return CornerRound(
        score=int(raw.get("m_score") or 0),
        hits=int(raw.get("m_hits") or 0),
        received_damage=float(raw.get("m_receivedDamage") or 0),
        stuns=int(raw.get("m_stuns") or 0),
        punishment_stuns=int(raw.get("m_punishmentStuns") or 0),
        knockdowns=int(raw.get("m_knockedDowns") or 0),
        punishment_knockdowns=int(raw.get("m_punishmentKnockdowns") or 0),
        all_knockdowns=int(raw.get("m_allKnockedDown") or 0),
        knocked_out=bool(raw.get("m_knockedOut")),
        technically_knocked_out=bool(raw.get("m_technicallyKnockedOut")),
        fouls=_foul_count(raw.get("m_fouls")),
    )


def _rounds(session: ParsedSession) -> list[RoundScore]:
    scoring = session.metadata.get("m_scoring") or {}
    completed = int(scoring.get("m_completedRoundIndex") or 0)
    rows = []
    for index, raw in enumerate(scoring.get("m_rounds") or []):
        rows.append(
            RoundScore(
                index=index,
                completed=index <= completed,
                red=_corner_round(raw.get("m_red") or {}),
                blue=_corner_round(raw.get("m_blue") or {}),
            )
        )
    return rows


@dataclass(frozen=True)
class _RoundWindow:
    index: int
    warning_tick: int
    bell_tick: int
    end_bell_tick: int | None
    stats_end: int
    bell_sec: float
    end_sec: float
    duration_sec: float
    # Last tick of the round's fighting: the end bell, or the tick the fight was stopped.
    end_tick: int = 0
    # Knockdown counts inside the round, as (first tick, last tick). No fighting happens in them.
    pauses: tuple[tuple[int, int], ...] = ()


def _round_windows(session: ParsedSession) -> list[_RoundWindow]:
    """Bell-to-bell windows. Breaks between rounds are left out."""
    venue = session.metadata.get("m_venue") or {}
    round_sec = float(venue.get("m_roundDurationSeconds") or 0)
    if round_sec <= 0 or session.fixed_timestep <= 0:
        return []
    duration_ticks = int(round(round_sec / session.fixed_timestep))
    ticks = sorted(
        {
            event.tick
            for track in session.tracks.values()
            for event in track.events
            if event.type_code == 5
        }
    )
    bells = [tick for prev, tick in zip(ticks, ticks[1:]) if tick - prev == ROUND_START_GAP]
    phases = sorted(
        {
            (event.tick, event.phase)
            for track in session.tracks.values()
            for event in track.events
            if event.type_code == PHASE_EVENT_TYPE and event.phase is not None
        }
    )
    windows: list[_RoundWindow] = []
    for position, bell in enumerate(bells):
        expected = bell + duration_ticks
        later_bells = [tick for tick in bells[position + 1 :] if tick > bell]
        limit = min(later_bells) if later_bells else session.end_tick + 1
        stops = [
            tick
            for tick, phase in phases
            if bell < tick < limit and phase in (PHASE_ROUND_END, PHASE_FIGHT_OVER)
        ]
        stopped = min(stops) if stops else None
        near = [tick for tick in ticks if abs(tick - expected) <= END_BELL_TOLERANCE]
        end_bell = min(near, key=lambda tick: abs(tick - expected)) if near else None
        if stopped is not None and (end_bell is None or stopped < end_bell):
            # The phase marker says the round ended here: a stoppage, or a bell off the nominal time.
            official_end = stopped
            stats_end = min(session.end_tick, stopped + BELL_GRACE_TICKS)
            end_bell = None
        elif end_bell is not None:
            official_end = end_bell
            stats_end = min(session.end_tick, end_bell + BELL_GRACE_TICKS)
        elif session.end_tick <= expected + BELL_GRACE_TICKS:
            official_end = session.end_tick
            stats_end = session.end_tick
            end_bell = None
        else:
            official_end = expected
            stats_end = min(session.end_tick, expected + BELL_GRACE_TICKS)
            end_bell = None
        if windows and bell <= windows[-1].stats_end:
            continue
        bell_sec = _sec(session, bell)
        end_sec = _sec(session, official_end)
        pauses = _knockdown_counts(phases, bell, official_end)
        paused = sum(last - first for first, last in pauses)
        windows.append(
            _RoundWindow(
                index=len(windows),
                warning_tick=bell - ROUND_START_GAP,
                bell_tick=bell,
                end_bell_tick=end_bell,
                stats_end=stats_end,
                bell_sec=bell_sec,
                end_sec=end_sec,
                duration_sec=round((official_end - bell - paused) * session.fixed_timestep, 4),
                end_tick=official_end,
                pauses=pauses,
            )
        )
    return windows


def _knockdown_counts(phases: list[tuple[int, int]], bell: int, end: int) -> tuple[tuple[int, int], ...]:
    """Spans from a knockdown phase marker to the next fight marker, or to the end of the round."""
    pauses: list[tuple[int, int]] = []
    start: int | None = None
    for tick, phase in phases:
        if tick <= bell or tick >= end:
            continue
        if phase in (PHASE_KNOCKDOWN, PHASE_KNOCKDOWN_FINAL):
            if start is None:
                start = tick
        elif phase == PHASE_FIGHT and start is not None:
            pauses.append((start, tick))
            start = None
    if start is not None:
        pauses.append((start, end))
    return tuple(pauses)


def _fighting(ticks: np.ndarray, pauses: tuple[tuple[int, int], ...]) -> np.ndarray:
    """True on ticks that are not strictly inside a knockdown count."""
    values = ticks.astype(np.int64, copy=False)
    mask = np.ones(len(values), dtype=bool)
    for first, last in pauses:
        mask &= ~((values > first) & (values < last))
    return mask


def _clip_track(
    track: TrackData, start: int, end: int, pauses: tuple[tuple[int, int], ...] = ()
) -> TrackData:
    def take(ticks: np.ndarray) -> np.ndarray:
        return (ticks >= start) & (ticks <= end) & _fighting(ticks, pauses)

    skeleton = take(track.skeleton_ticks)
    punishment = take(track.punishment_ticks)
    stiffness = take(track.stiffness_ticks)
    guard = take(track.guard_ticks)
    return TrackData(
        folder=track.folder,
        corner=track.corner,
        color=track.color,
        name=track.name,
        is_local_player=track.is_local_player,
        stance=track.stance,
        stance_confirmed=track.stance_confirmed,
        height_m=track.height_m,
        hand_length_m=track.hand_length_m,
        ai_archetype=track.ai_archetype,
        ai_difficulty=track.ai_difficulty,
        start_tick=start,
        end_tick=end,
        punches=[punch for punch in track.punches if start <= punch.tick <= end],
        rejected_punches=[punch for punch in track.rejected_punches if start <= punch.tick <= end],
        events=[event for event in track.events if start <= event.tick <= end],
        punishment_ticks=track.punishment_ticks[punishment],
        punishment=track.punishment[punishment],
        stiffness_ticks=track.stiffness_ticks[stiffness],
        stiffness=track.stiffness[stiffness],
        guard_ticks=track.guard_ticks[guard],
        guard_primary=track.guard_primary[guard],
        skeleton_ticks=track.skeleton_ticks[skeleton],
        skeleton_pos=track.skeleton_pos[skeleton],
    )


def _window_mask(ticks: np.ndarray, windows: list[_RoundWindow]) -> np.ndarray:
    if len(ticks) == 0:
        return np.zeros(0, dtype=bool)
    values = ticks.astype(np.int64, copy=False)
    mask = np.zeros(len(values), dtype=bool)
    for window in windows:
        mask |= (values >= window.warning_tick) & (values <= window.stats_end) & _fighting(values, window.pauses)
    return mask


def _filter_track(track: TrackData, windows: list[_RoundWindow]) -> TrackData:
    skeleton = _window_mask(track.skeleton_ticks, windows)
    punishment = _window_mask(track.punishment_ticks, windows)
    stiffness = _window_mask(track.stiffness_ticks, windows)
    guard = _window_mask(track.guard_ticks, windows)

    def inside(tick: int) -> bool:
        return any(window.warning_tick <= tick <= window.stats_end for window in windows)

    return TrackData(
        folder=track.folder,
        corner=track.corner,
        color=track.color,
        name=track.name,
        is_local_player=track.is_local_player,
        stance=track.stance,
        stance_confirmed=track.stance_confirmed,
        height_m=track.height_m,
        hand_length_m=track.hand_length_m,
        ai_archetype=track.ai_archetype,
        ai_difficulty=track.ai_difficulty,
        start_tick=track.start_tick,
        end_tick=track.end_tick,
        punches=[punch for punch in track.punches if inside(punch.tick)],
        rejected_punches=[punch for punch in track.rejected_punches if inside(punch.tick)],
        events=[event for event in track.events if inside(event.tick)],
        punishment_ticks=track.punishment_ticks[punishment],
        punishment=track.punishment[punishment],
        stiffness_ticks=track.stiffness_ticks[stiffness],
        stiffness=track.stiffness[stiffness],
        guard_ticks=track.guard_ticks[guard],
        guard_primary=track.guard_primary[guard],
        skeleton_ticks=track.skeleton_ticks[skeleton],
        skeleton_pos=track.skeleton_pos[skeleton],
    )


def _within_windows(session: ParsedSession, windows: list[_RoundWindow]) -> ParsedSession:
    """Keep bell-to-bell samples. The fight clock (start_tick) stays where it is."""
    if not windows:
        return session
    return ParsedSession(
        path=session.path,
        metadata=session.metadata,
        fixed_timestep=session.fixed_timestep,
        start_tick=session.start_tick,
        end_tick=session.end_tick,
        tracks={corner: _filter_track(track, windows) for corner, track in session.tracks.items()},
    )


def _clock_ticks(windows: list[_RoundWindow]) -> set[int]:
    """Type-5 ticks that mark the warning, the bell, and the end bell."""
    ticks: set[int] = set()
    for window in windows:
        ticks.add(window.warning_tick)
        ticks.add(window.bell_tick)
        if window.end_bell_tick is not None:
            ticks.add(window.end_bell_tick)
    return ticks


def _drop_clock_events(track: TrackData, clock: set[int]) -> TrackData:
    if not clock:
        return track
    return TrackData(
        folder=track.folder,
        corner=track.corner,
        color=track.color,
        name=track.name,
        is_local_player=track.is_local_player,
        stance=track.stance,
        stance_confirmed=track.stance_confirmed,
        height_m=track.height_m,
        hand_length_m=track.hand_length_m,
        ai_archetype=track.ai_archetype,
        ai_difficulty=track.ai_difficulty,
        start_tick=track.start_tick,
        end_tick=track.end_tick,
        punches=track.punches,
        rejected_punches=track.rejected_punches,
        events=[event for event in track.events if not (event.type_code == 5 and event.tick in clock)],
        punishment_ticks=track.punishment_ticks,
        punishment=track.punishment,
        stiffness_ticks=track.stiffness_ticks,
        stiffness=track.stiffness,
        guard_ticks=track.guard_ticks,
        guard_primary=track.guard_primary,
        skeleton_ticks=track.skeleton_ticks,
        skeleton_pos=track.skeleton_pos,
    )


def _clip_session(session: ParsedSession, window: _RoundWindow) -> ParsedSession:
    clock = _clock_ticks([window])
    return ParsedSession(
        path=session.path,
        metadata=session.metadata,
        fixed_timestep=session.fixed_timestep,
        start_tick=window.bell_tick,
        end_tick=window.stats_end,
        tracks={
            corner: _drop_clock_events(_clip_track(track, window.warning_tick, window.stats_end, window.pauses), clock)
            for corner, track in session.tracks.items()
        },
    )


def _attach_rounds(
    session: ParsedSession,
    rounds: list[RoundScore],
    labels: dict[int, dict[int, str]],
    windows: list[_RoundWindow],
) -> None:
    windows = {window.index: window for window in windows}
    for rnd in rounds:
        if not rnd.completed:
            continue
        window = windows.get(rnd.index)
        if window is None:
            continue
        offense, defense, moments, series = _measure(
            _clip_session(session, window),
            labels,
            _score_totals([rnd]),
            [],
            pace_sec=window.duration_sec,
            windows=[window],
        )
        rnd.bell_sec = window.bell_sec
        rnd.end_sec = window.end_sec
        rnd.duration_sec = window.duration_sec
        rnd.offense = offense
        rnd.defense = defense
        rnd.key_moments = moments
        rnd.series = series


def _score_totals(rounds: list[RoundScore]) -> dict[int, dict]:
    totals = {
        corner: defaultdict(float)
        for corner in (COLOR_CORNER["red"], COLOR_CORNER["blue"])
    }
    flags = ("knocked_out", "technically_knocked_out")
    numbers = (
        "score",
        "hits",
        "received_damage",
        "stuns",
        "punishment_stuns",
        "knockdowns",
        "punishment_knockdowns",
        "all_knockdowns",
        "fouls",
    )
    for rnd in rounds:
        if not rnd.completed:
            continue
        for corner, block in ((COLOR_CORNER["red"], rnd.red), (COLOR_CORNER["blue"], rnd.blue)):
            for name in numbers:
                totals[corner][name] += getattr(block, name)
            for name in flags:
                totals[corner][name] = bool(totals[corner][name] or getattr(block, name))
    for row in totals.values():
        for name in flags:
            row[name] = bool(row[name])
        row["score"] = int(row["score"])
        row["hits"] = int(row["hits"])
        row["stuns"] = int(row["stuns"])
        row["punishment_stuns"] = int(row["punishment_stuns"])
        row["all_knockdowns"] = int(row["all_knockdowns"])
    return totals


def _extend_past_wrist(wrist: np.ndarray, elbow: np.ndarray, reach: float) -> np.ndarray:
    direction = wrist.astype(np.float64) - elbow.astype(np.float64)
    length = np.linalg.norm(direction, axis=1, keepdims=True)
    unit = np.divide(direction, length, out=np.zeros_like(direction), where=length > 1.0e-6)
    return wrist.astype(np.float64) + unit * reach


def _glove_centers(track: TrackData) -> tuple[np.ndarray, np.ndarray]:
    """Wrist extended half a hand length along the forearm, per hand."""
    pos = track.skeleton_pos
    reach = 0.5 * float(track.hand_length_m)
    left = _extend_past_wrist(pos[:, L_WRIST], pos[:, L_ELBOW], reach)
    right = _extend_past_wrist(pos[:, R_WRIST], pos[:, R_ELBOW], reach)
    return left, right


def _body(track: TrackData) -> dict:
    ticks = track.skeleton_ticks.astype(np.int64)
    pos = track.skeleton_pos
    empty = np.zeros(0, dtype=bool)
    if len(pos) == 0:
        return {
            "head": HEAD,
            "left": None,
            "right": None,
            "ticks": ticks,
            "guard": empty,
            "left_guard": empty,
            "right_guard": empty,
            "head_xyz": np.zeros((0, 3), dtype=np.float64),
        }
    left_glove, right_glove = _glove_centers(track)
    head_xyz = pos[:, HEAD, :].astype(np.float64)
    dy_l = head_xyz[:, 1] - left_glove[:, 1]
    dy_r = head_xyz[:, 1] - right_glove[:, 1]
    horiz_l = np.linalg.norm(left_glove[:, [0, 2]] - head_xyz[:, [0, 2]], axis=1)
    horiz_r = np.linalg.norm(right_glove[:, [0, 2]] - head_xyz[:, [0, 2]], axis=1)
    left_guard = (dy_l < GUARD_DY_MAX) & (horiz_l < GUARD_HORIZ_MAX)
    right_guard = (dy_r < GUARD_DY_MAX) & (horiz_r < GUARD_HORIZ_MAX)
    return {
        "head": HEAD,
        "left": L_WRIST,
        "right": R_WRIST,
        "ticks": ticks,
        "guard": left_guard & right_guard,
        "left_guard": left_guard,
        "right_guard": right_guard,
        "head_xyz": head_xyz,
    }


def _nearest_index(source_ticks: np.ndarray, query_ticks: np.ndarray) -> np.ndarray:
    nearest = np.clip(np.searchsorted(source_ticks, query_ticks, side="left"), 0, len(source_ticks) - 1)
    previous = np.clip(nearest - 1, 0, len(source_ticks) - 1)
    nearer_previous = np.abs(source_ticks[previous] - query_ticks) < np.abs(source_ticks[nearest] - query_ticks)
    return np.where(nearer_previous, previous, nearest)


def _local_axes(track: TrackData, opponent: TrackData) -> tuple[np.ndarray, np.ndarray]:
    """Per skeleton frame: horizontal forward toward the opponent, and the fighter's right."""
    ticks = track.skeleton_ticks.astype(np.int64)
    count = len(ticks)
    if count == 0 or len(opponent.skeleton_ticks) == 0:
        forward = np.zeros((count, 3), dtype=np.float64)
        forward[:, 2] = 1.0
        right = np.stack([forward[:, 2], np.zeros(count), -forward[:, 0]], axis=1)
        return forward, right
    nearest = _nearest_index(opponent.skeleton_ticks.astype(np.int64), ticks)
    opp = opponent.skeleton_pos[nearest].astype(np.float64)
    mine = track.skeleton_pos.astype(np.float64)
    delta = opp[:, HIPS] - mine[:, HIPS]
    delta[:, 1] = 0.0
    length = np.linalg.norm(delta, axis=1)
    weak = length < 1.0e-3
    if np.any(weak):
        head_delta = opp[weak, HEAD] - mine[weak, HEAD]
        head_delta[:, 1] = 0.0
        delta[weak] = head_delta
        length = np.linalg.norm(delta, axis=1)
    good = length >= 1.0e-3
    unit = np.zeros_like(delta)
    unit[good] = delta[good] / length[good, None]
    last = np.array([0.0, 0.0, 1.0])
    for index in range(count):
        if good[index]:
            last = unit[index].copy()
        else:
            unit[index] = last
    right = np.stack([unit[:, 2], np.zeros(count), -unit[:, 0]], axis=1)
    return unit, right


def _motion_ticks(punch: PunchRecord, timestep: float) -> tuple[int, int]:
    """Ticks that hold the swing. A contact record's launch tick is the contact, so its swing is before it."""
    if punch.kinematics:
        return punch.launch_tick, punch.tick
    return (
        punch.launch_tick - _tick_radius(CONTACT_LOOKBACK_SEC, timestep),
        punch.launch_tick + _tick_radius(CONTACT_LOOKAHEAD_SEC, timestep),
    )


def _closing_speeds(track: TrackData, opponent: TrackData, timestep: float) -> list[float | None]:
    """Per punch record: peak speed (m/s) at which that glove closed on the opponent's head or trunk.

    The distance is from the glove center to the nearest of the opponent's head, chest, spine, and hips.
    The peak is over a 3-tick mean, from 0.15 s before the record's launch tick to 0.033 s after it.
    """
    ticks = track.skeleton_ticks.astype(np.int64)
    other_ticks = opponent.skeleton_ticks.astype(np.int64)
    if len(ticks) == 0 or len(other_ticks) == 0 or timestep <= 0:
        return [None for _ in track.punches]
    left, right = _glove_centers(track)
    targets = opponent.skeleton_pos[_nearest_index(other_ticks, ticks)][:, list(TARGET_JOINTS)].astype(np.float64)
    before = _tick_radius(CONTACT_LOOKBACK_SEC, timestep)
    after = _tick_radius(CONTACT_LOOKAHEAD_SEC, timestep)
    kernel = np.ones(CONTACT_SMOOTH_TICKS) / CONTACT_SMOOTH_TICKS
    out: list[float | None] = []
    for punch in track.punches:
        if punch.hand_index not in HAND_LABEL:
            out.append(None)
            continue
        glove = left if punch.hand_index == 1 else right
        lo = int(np.searchsorted(ticks, punch.launch_tick - before, side="left"))
        hi = int(np.searchsorted(ticks, punch.launch_tick + after, side="right"))
        if hi - lo < CONTACT_SMOOTH_TICKS + 1:
            out.append(None)
            continue
        distance = np.linalg.norm(glove[lo:hi, None, :] - targets[lo:hi], axis=2).min(axis=1)
        step_sec = np.diff(ticks[lo:hi]) * timestep
        closing = -np.diff(distance) / np.where(step_sec > 0, step_sec, timestep)
        out.append(float(np.convolve(closing, kernel, mode="valid").max()))
    return out


def _glove_peak_speeds(track: TrackData, timestep: float) -> list[float | None]:
    """Per punch record: peak speed (m/s) of that glove center over the swing, as a 3-tick mean.

    The swing is launch to end for a kinematic record and the 0.15 s before the contact for a contact record.
    """
    ticks = track.skeleton_ticks.astype(np.int64)
    if len(ticks) == 0 or timestep <= 0:
        return [None for _ in track.punches]
    left, right = _glove_centers(track)
    kernel = np.ones(SPEED_SMOOTH_TICKS) / SPEED_SMOOTH_TICKS
    out: list[float | None] = []
    for punch in track.punches:
        if punch.hand_index not in HAND_LABEL or punch.launch_tick > punch.tick:
            out.append(None)
            continue
        glove = left if punch.hand_index == 1 else right
        start, end = _motion_ticks(punch, timestep)
        lo = int(np.searchsorted(ticks, start, side="left"))
        hi = int(np.searchsorted(ticks, end, side="right"))
        if hi - lo < SPEED_SMOOTH_TICKS + 1:
            out.append(None)
            continue
        step_sec = np.diff(ticks[lo:hi]) * timestep
        speed = np.linalg.norm(np.diff(glove[lo:hi], axis=0), axis=1) / np.where(step_sec > 0, step_sec, timestep)
        out.append(float(np.convolve(speed, kernel, mode="valid").max()))
    return out


def _validated_punches(session: ParsedSession) -> ParsedSession:
    """Keep the punch records that are punches. The rest move to ``rejected_punches``.

    Kinematic records (byte 9 is 0) are the game's own detected swings and are kept.
    A contact record is dropped when it is another contact of a swing already kept on that hand
    (inside it, just after it, or just before a kinematic launch),
    or when its glove was not closing on the opponent fast enough to be a strike
    (a block, a glove clash, a push, or a parry). Without skeleton frames it is kept.
    A slow contact record is kept after all when a hit event stores its contact point, or when a hit
    that no kept punch explains sits on its contact tick: the game scored that contact.
    Every record also gets its peak glove speed from the skeleton.
    """
    timestep = session.fixed_timestep
    grace = _tick_radius(SAME_SWING_GRACE_SEC, timestep)
    tracks: dict[int, TrackData] = {}
    for corner, track in session.tracks.items():
        opponent = session.tracks.get(_opponent(session, corner))
        speeds = (
            _closing_speeds(track, opponent, timestep)
            if opponent is not None and opponent is not track
            else [None for _ in track.punches]
        )
        swings: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for punch in track.punches:
            if punch.kinematics:
                # A stamp just before the launch tick is the same swing: the game can set launch after first contact.
                swings[punch.hand_index].append((punch.launch_tick - grace, punch.tick + grace))
        keep = [punch.kinematics for punch in track.punches]
        slow: list[int] = []
        order = sorted(range(len(track.punches)), key=lambda index: (track.punches[index].launch_tick, index))
        for index in order:
            punch = track.punches[index]
            if punch.kinematics:
                continue
            if any(start <= punch.launch_tick <= end for start, end in swings[punch.hand_index]):
                continue
            speed = speeds[index]
            if speed is not None and speed < CONTACT_CLOSING_MIN:
                slow.append(index)
                continue
            keep[index] = True
            swings[punch.hand_index].append((punch.launch_tick, punch.tick + grace))
        if slow and opponent is not None and opponent is not track:
            hit_keys = {event.contact_key for event in opponent.events if event.landed_hit and event.contact_key}
            for index in slow:
                if track.punches[index].contact_key in hit_keys:
                    keep[index] = True
            slow = [index for index in slow if not keep[index]]
            for index in _scored_contacts(track.punches, keep, slow, opponent.events, timestep):
                keep[index] = True
        peaks = _glove_peak_speeds(track, timestep)
        measured = [dataclass_replace(punch, speed=peak) for punch, peak in zip(track.punches, peaks)]
        tracks[corner] = dataclass_replace(
            track,
            punches=[punch for punch, kept in zip(measured, keep) if kept],
            rejected_punches=[punch for punch, kept in zip(measured, keep) if not kept],
        )
    return dataclass_replace(session, tracks=tracks)


def _scored_contacts(
    punches: list[PunchRecord],
    keep: list[bool],
    slow: list[int],
    opponent_events: list[EventRecord],
    timestep: float,
) -> list[int]:
    """Slow contact records that sit on a scored hit no kept punch accounts for. One record per hit."""
    hits = [event for event in opponent_events if event.landed_hit]
    kept = [punch for punch, flag in zip(punches, keep) if flag]
    explained = {id(event) for event in _match_punches(kept, hits).values()}
    free = [event for event in hits if id(event) not in explained]
    before = _tick_radius(SCORED_CONTACT_BEFORE_SEC, timestep)
    after = _tick_radius(SCORED_CONTACT_AFTER_SEC, timestep)
    pairs = sorted(
        (abs(event.tick - punches[index].launch_tick), index, position)
        for position, event in enumerate(free)
        for index in slow
        if -before <= event.tick - punches[index].launch_tick <= after
    )
    used: set[int] = set()
    rescued: list[int] = []
    for _delta, index, position in pairs:
        if position in used or index in rescued:
            continue
        used.add(position)
        rescued.append(index)
    return rescued


def _wrist_index(hand_index: int) -> int | None:
    if hand_index == 1:
        return L_WRIST
    if hand_index == 0:
        return R_WRIST
    return None


def _label_displacement(hand: str, displacement: np.ndarray) -> str:
    magnitude = float(np.linalg.norm(displacement))
    if magnitude < MIN_EXTENSION_M:
        return "unknown"
    forward, up, lateral = (float(component) / magnitude for component in displacement)
    if up >= UPPERCUT_UP and up >= abs(forward) and up >= abs(lateral):
        return "uppercut"
    if up <= OVERHAND_DOWN and forward >= abs(lateral):
        return "overhand"
    if abs(lateral) >= HOOK_LATERAL and abs(lateral) >= forward:
        return "left_hook" if hand == "left" else "right_hook"
    if forward > STRAIGHT_FORWARD:
        return "jab" if hand == "left" else "cross"
    return "unknown"


def _trajectory_family(label: str) -> str | None:
    if label in {"jab", "cross"}:
        return "straight"
    if label in {"left_hook", "right_hook"}:
        return "hook"
    if label in {"uppercut", "overhand"}:
        return label
    return None


def _skeleton_trajectory(
    track: TrackData,
    punch: PunchRecord,
    forward: np.ndarray,
    right: np.ndarray,
    timestep: float,
) -> str:
    wrist = _wrist_index(punch.hand_index)
    hand = HAND_LABEL.get(punch.hand_index)
    ticks = track.skeleton_ticks
    if wrist is None or hand is None or len(ticks) == 0 or punch.launch_tick > punch.tick:
        return "unknown"
    start, end = _motion_ticks(punch, timestep)
    lo = int(np.searchsorted(ticks, start, side="left"))
    hi = int(np.searchsorted(ticks, end, side="right"))
    if hi - lo < MIN_SKELETON_FRAMES:
        return "unknown"
    points = track.skeleton_pos[lo:hi, wrist].astype(np.float64)
    delta = points - points[0]
    up = np.array([0.0, 1.0, 0.0])
    local = np.column_stack((delta @ forward[lo], delta @ up, delta @ right[lo]))
    peak = int(np.argmax(np.linalg.norm(local, axis=1)))
    if peak == 0:
        return "unknown"
    return _label_displacement(hand, local[peak])


def _punch_trajectories(
    track: TrackData, opponent: TrackData, notes: list[DecodeNote], timestep: float
) -> list[str]:
    """Game class when byte 32 is set; otherwise the skeleton displacement label."""
    forward, right = _local_axes(track, opponent)
    labels: list[str] = []
    game_count = 0
    compared = 0
    agreed = 0
    for punch in track.punches:
        game = PUNCH_CLASS_LABEL.get(punch.punch_class)
        skeleton = _skeleton_trajectory(track, punch, forward, right, timestep)
        if game:
            game_count += 1
            game_family = _trajectory_family(game)
            skeleton_family = _trajectory_family(skeleton)
            if game_family is not None and skeleton_family is not None:
                compared += 1
                if game_family == skeleton_family:
                    agreed += 1
            labels.append(game)
        else:
            labels.append(skeleton)
    if game_count and compared and agreed * 2 > compared:
        confidence = "confirmed"
        note = (
            "Byte 32 is the punch class (1 jab, 2 cross, 3 left hook, 4 right hook, 6 uppercut). "
            "The skeleton wrist family agreed on a majority of those punches."
        )
    elif game_count == 0:
        confidence = "inferred"
        note = (
            "This track has no game punch class. Trajectory is the wrist displacement from launch "
            "to peak extension in the opponent frame (forward, up, right)."
        )
    else:
        confidence = "inferred"
        note = (
            "Byte 32 is the stored punch class. The skeleton cross-check did not agree "
            "on a majority of classified punches."
        )
    notes.append(DecodeNote(field=f"offense.{track.corner}.trajectory", confidence=confidence, note=note))
    return labels


def _hand_labels(track: TrackData, notes: list[DecodeNote], timestep: float) -> dict[int, str]:
    """Byte 10 is authoritative: 0 right, 1 left. Skeleton motion only sets confidence."""
    labels = dict(HAND_LABEL)
    agreed = 0
    voted = 0
    ticks = track.skeleton_ticks
    pos = track.skeleton_pos
    if len(pos):
        for punch in track.punches:
            if punch.hand_index not in labels or punch.launch_tick > punch.tick:
                continue
            start, end = _motion_ticks(punch, timestep)
            lo = int(np.searchsorted(ticks, start, side="left"))
            hi = int(np.searchsorted(ticks, end, side="right"))
            if hi - lo < 2:
                continue
            window = pos[lo:hi]
            left_motion = float(np.linalg.norm(np.diff(window[:, L_WRIST], axis=0), axis=1).sum())
            right_motion = float(np.linalg.norm(np.diff(window[:, R_WRIST], axis=0), axis=1).sum())
            if left_motion == right_motion:
                continue
            voted += 1
            side = "left" if left_motion > right_motion else "right"
            if side == labels[punch.hand_index]:
                agreed += 1
    if voted and agreed * 2 > voted:
        confidence = "confirmed"
        note = (
            "Byte 10 is the hand: 0 is right and 1 is left. "
            "From launch to end, that wrist moved more than the other on a majority of punches."
        )
    else:
        confidence = "inferred"
        note = (
            "Byte 10 is the hand: 0 is right and 1 is left. "
            "Skeleton wrist motion did not agree on a majority of punches, so the record label is kept."
        )
    notes.append(DecodeNote(field=f"offense.{track.corner}.hand", confidence=confidence, note=note))
    return labels


def _note_scored_hits(landed_events: dict[int, list[EventRecord]], totals: dict[int, dict], notes: list[DecodeNote]) -> None:
    matched = True
    for corner, events in landed_events.items():
        taken = int(totals.get(corner, {}).get("hits", -1))
        if sum(1 for event in events if event.scored_hit) != taken:
            matched = False
    notes.append(
        DecodeNote(
            field="offense.landed",
            confidence="confirmed" if matched else "inferred",
            note=(
                "A type-1 event is a hit taken by the fighter whose track holds it, so it is the opponent's landed punch. "
                "Byte 8 is the kind of hit: 1 an ordinary hit, 6 a stun, 7 a punishment stun, 2 and 5 a blow that starts a knockdown count. "
                "landed counts every kind. official_hits is the scorecard's m_hits, which counts kind 1 only, "
                "so landed is higher than official_hits by the stuns and knockdown blows. "
                + (
                    "The kind-1 count matches m_hits for both fighters."
                    if matched
                    else "The kind-1 count did not match m_hits, so landed is an estimate."
                )
            ),
        )
    )


def _match_punches(punches: list[PunchRecord], received: list[EventRecord]) -> dict[int, EventRecord]:
    """Pair each hit with the punch that made it.

    A hit event and its punch record store the same contact point, byte for byte, so that pairing
    is exact. A hit with no such record goes to the closest free punch whose launch-to-end window holds it.
    """
    matched: dict[int, EventRecord] = {}
    used_events: set[int] = set()
    by_key: dict[bytes, list[int]] = defaultdict(list)
    for punch_index, punch in enumerate(punches):
        if punch.contact_key:
            by_key[punch.contact_key].append(punch_index)
    for event_index, event in enumerate(received):
        owners = by_key.get(event.contact_key) if event.contact_key else None
        if owners and len(owners) == 1 and owners[0] not in matched:
            matched[owners[0]] = event
            used_events.add(event_index)
    pairs: list[tuple[int, int, int]] = []
    for event_index, event in enumerate(received):
        if event_index in used_events:
            continue
        for punch_index, punch in enumerate(punches):
            if punch_index in matched:
                continue
            if punch.launch_tick - HIT_LAUNCH_LEAD <= event.tick <= punch.tick + HIT_END_LAG:
                delta = abs(event.tick - punch.launch_tick)
                pairs.append((delta, event_index, punch_index))
    pairs.sort()
    for _delta, event_index, punch_index in pairs:
        if event_index in used_events or punch_index in matched:
            continue
        used_events.add(event_index)
        matched[punch_index] = received[event_index]
    return matched


@dataclass
class _PunchGuard:
    hand: str | None = None
    offhand_role: str | None = None
    offhand_in_guard: bool | None = None
    offhand_drop_m: float | None = None
    offhand_flare_m: float | None = None
    # True returned, False missed the window, None excluded or no apex.
    returned: bool | None = None
    # Kinematic punches (byte 9 == 0) are the only ones in the aggregate rates.
    rated: bool = False
    retraction_ms: float | None = None
    retraction_droop_m: float | None = None
    retraction_directness: float | None = None


def _lead_hand(stance: str | None) -> str | None:
    if stance is None:
        return None
    name = stance.strip().lower()
    if name == "orthodox":
        return "left"
    if name in {"southpaw", "south paw"}:
        return "right"
    return None


def _offhand_role(punching_hand: str, stance: str | None) -> str | None:
    lead = _lead_hand(stance)
    if lead is None:
        return None
    offhand = "right" if punching_hand == "left" else "left"
    return "lead" if offhand == lead else "rear"


def _glove_pair(hand: str, left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if hand == "left":
        return left, right
    return right, left


def _head_drop(head: np.ndarray, glove: np.ndarray) -> tuple[float, float, bool]:
    drop = max(0.0, float(head[1] - glove[1]))
    flare = float(np.linalg.norm(glove[[0, 2]] - head[[0, 2]]))
    kept = drop < OFFHAND_DY_MAX and flare < OFFHAND_HORIZ_MAX
    return drop, flare, kept


def _in_return_box(head: np.ndarray, glove: np.ndarray) -> bool:
    """Tight head-relative box shared with off-hand kept."""
    drop = float(head[1] - glove[1])
    flare = float(np.linalg.norm(glove[[0, 2]] - head[[0, 2]]))
    return drop < OFFHAND_DY_MAX and flare < OFFHAND_HORIZ_MAX


def _extension_peak(
    glove: np.ndarray,
    forward: np.ndarray,
    right: np.ndarray,
    lo: int,
    hi: int,
) -> int | None:
    if hi - lo < MIN_SKELETON_FRAMES:
        return None
    delta = glove[lo:hi] - glove[lo]
    up = np.array([0.0, 1.0, 0.0])
    local = np.column_stack((delta @ forward[lo], delta @ up, delta @ right[lo]))
    peak = int(np.argmax(np.linalg.norm(local, axis=1)))
    if peak == 0:
        return None
    return lo + peak


def _return_shape(relative: np.ndarray) -> tuple[float, float]:
    count = len(relative)
    if count <= 1:
        return 0.0, 1.0
    start = relative[0]
    end = relative[-1]
    chord = float(np.linalg.norm(end - start))
    arc = float(np.linalg.norm(np.diff(relative, axis=0), axis=1).sum())
    directness = 1.0 if arc <= 1.0e-9 else min(1.0, chord / arc)
    weights = np.linspace(0.0, 1.0, count)
    chord_y = start[1] + weights * (end[1] - start[1])
    droop = float(max(0.0, float((chord_y - relative[:, 1]).max())))
    return droop, directness


def _retraction(
    ticks: np.ndarray,
    head: np.ndarray,
    glove: np.ndarray,
    apex: int,
    next_launch: int | None,
    timestep: float,
) -> tuple[bool | None, float | None, float | None, float | None]:
    """Walk from the apex until the glove re-enters the tight box, the next same-hand launch, or 800 ms.

    A glove already inside the box at the apex never left, so that punch is excluded.
    """
    if _in_return_box(head[apex], glove[apex]):
        return None, None, None, None
    apex_tick = int(ticks[apex])
    returned_at: int | None = None
    excluded = False
    for index in range(apex, len(ticks)):
        tick = int(ticks[index])
        if (tick - apex_tick) * timestep > RETRACTION_WINDOW_SEC + 1.0e-9:
            break
        if next_launch is not None and tick >= next_launch:
            excluded = True
            break
        if _in_return_box(head[index], glove[index]):
            returned_at = index
            break
    if excluded and returned_at is None:
        return None, None, None, None
    if returned_at is None:
        return False, None, None, None
    relative = glove[apex : returned_at + 1] - head[apex : returned_at + 1]
    droop, directness = _return_shape(relative)
    elapsed = (int(ticks[returned_at]) - apex_tick) * timestep * 1000.0
    return True, elapsed, droop, directness


def _punch_guard(track: TrackData, opponent: TrackData, timestep: float) -> list[_PunchGuard]:
    punches = track.punches
    if not punches:
        return []
    ticks = track.skeleton_ticks.astype(np.int64)
    if len(ticks) == 0:
        return [_PunchGuard() for _ in punches]
    forward, right = _local_axes(track, opponent)
    left_glove, right_glove = _glove_centers(track)
    head = track.skeleton_pos[:, HEAD, :].astype(np.float64)
    rows: list[_PunchGuard] = []
    for punch in punches:
        hand = HAND_LABEL.get(punch.hand_index)
        if hand is None or punch.launch_tick > punch.tick:
            rows.append(_PunchGuard())
            continue
        start, end = _motion_ticks(punch, timestep)
        lo = int(np.searchsorted(ticks, start, side="left"))
        hi = int(np.searchsorted(ticks, end, side="right"))
        punching, offhand = _glove_pair(hand, left_glove, right_glove)
        apex = _extension_peak(punching, forward, right, lo, hi)
        if apex is None:
            rows.append(_PunchGuard(hand=hand, offhand_role=_offhand_role(hand, track.stance)))
            continue
        drop, flare, kept = _head_drop(head[apex], offhand[apex])
        later = [
            other.launch_tick
            for other in punches
            if other is not punch and other.hand_index == punch.hand_index and other.launch_tick > int(ticks[apex])
        ]
        next_launch = min(later) if later else None
        returned, elapsed, droop, directness = _retraction(
            ticks, head, punching, apex, next_launch, timestep
        )
        rows.append(
            _PunchGuard(
                hand=hand,
                offhand_role=_offhand_role(hand, track.stance),
                offhand_in_guard=kept,
                offhand_drop_m=drop,
                offhand_flare_m=flare,
                returned=returned,
                retraction_ms=elapsed,
                retraction_droop_m=droop,
                retraction_directness=directness,
                rated=punch.kinematics,
            )
        )
    return rows


def _launch_slips(track: TrackData, opponent: TrackData) -> list[float | None]:
    punches = track.punches
    if not punches:
        return []
    ticks = track.skeleton_ticks.astype(np.int64)
    if len(ticks) == 0 or len(opponent.skeleton_ticks) == 0:
        return [None for _ in punches]
    right = _local_axes(track, opponent)[1]
    pos = track.skeleton_pos.astype(np.float64)
    slip_lat = np.sum((pos[:, HEAD] - pos[:, HIPS]) * right, axis=1)
    by_tick = {int(tick): float(slip_lat[index]) for index, tick in enumerate(ticks)}
    nearest = _nearest_index(ticks, np.array([punch.launch_tick for punch in punches], dtype=np.int64))
    out: list[float | None] = []
    for index, punch in enumerate(punches):
        exact = by_tick.get(punch.launch_tick)
        if exact is not None:
            out.append(round(exact, 4))
            continue
        near_idx = int(nearest[index])
        if abs(int(ticks[near_idx]) - punch.launch_tick) <= 1:
            out.append(round(float(slip_lat[near_idx]), 4))
        else:
            out.append(None)
    return out


def _offense(
    session: ParsedSession,
    track: TrackData,
    labels: dict[int, str],
    matched: dict[int, EventRecord],
    landed_events: dict[int, list[EventRecord]],
    totals: dict[int, dict],
    notes: list[DecodeNote],
    punch_guards: list[_PunchGuard],
    pace_sec: float | None = None,
) -> OffenseStats:
    defender = session.tracks[_opponent(session, track.corner)]
    trajectories = _punch_trajectories(track, defender, notes, session.fixed_timestep)
    launch_slips = _launch_slips(track, defender)
    received = landed_events[defender.corner]
    # m_hits on a corner is hits that fighter took. The punch that landed is on the defender's card.
    official = int(totals.get(defender.corner, {}).get("hits", 0))
    rows: list[PunchRow] = []
    hand_buckets: dict[str, list[PunchRow]] = defaultdict(list)
    traj_buckets: dict[str, list[PunchRow]] = defaultdict(list)
    speeds: list[float] = []
    landed_speeds: list[float] = []
    landed_deltas: list[float] = []
    corr_speed: list[float] = []
    corr_delta: list[float] = []
    for index, punch in enumerate(track.punches):
        hit_event = matched.get(index)
        landed = hit_event is not None
        delta = hit_event.damage if hit_event is not None else None
        hand = labels.get(punch.hand_index, f"hand_{punch.hand_index}")
        trajectory = trajectories[index]
        guard = punch_guards[index]
        row = PunchRow(
            t_sec=_sec(session, punch.tick),
            launch_sec=_sec(session, punch.launch_tick),
            impact_sec=_sec(session, hit_event.tick) if hit_event is not None else None,
            tick=punch.tick,
            hand=hand,
            hand_index=punch.hand_index,
            trajectory=trajectory,
            speed=_finite(punch.speed),
            landed=landed,
            damage=_finite(delta),
            head_slip_m=_finite(launch_slips[index]),
            offhand_in_guard=guard.offhand_in_guard,
            offhand_drop_m=_finite(guard.offhand_drop_m),
            offhand_flare_m=_finite(guard.offhand_flare_m),
            retraction_ms=_finite(guard.retraction_ms),
            retraction_droop_m=_finite(guard.retraction_droop_m),
            retraction_directness=_finite(guard.retraction_directness),
        )
        rows.append(row)
        hand_buckets[hand].append(row)
        traj_buckets[trajectory].append(row)
        if row.speed is not None:
            speeds.append(row.speed)
            if landed:
                landed_speeds.append(row.speed)
                if row.damage is not None:
                    landed_deltas.append(row.damage)
                    corr_speed.append(row.speed)
                    corr_delta.append(row.damage)
    unmatched = len(received) - len(matched)
    if unmatched > 0:
        hand_buckets["unmatched"].extend(
            PunchRow(
                t_sec=0,
                tick=0,
                hand="unmatched",
                hand_index=-1,
                trajectory="unknown",
                speed=None,
                landed=True,
                damage=None,
            )
            for _ in range(unmatched)
        )
    if not any(punch.speed is not None for punch in track.punches):
        notes.append(
            DecodeNote(
                field=f"offense.{track.corner}.speed",
                confidence="unavailable",
                note="No skeleton frames cover this track's punches, so no glove speed could be measured.",
            )
        )
    pace = session.duration_sec if pace_sec is None else pace_sec
    minutes = pace / 60.0 if pace else 0.0
    landed_total = len(received)
    return OffenseStats(
        corner=track.corner,
        thrown=len(track.punches),
        kinematic_thrown=sum(1 for punch in track.punches if punch.kinematics),
        contact_thrown=sum(1 for punch in track.punches if not punch.kinematics),
        discarded_records=len(track.rejected_punches),
        landed=landed_total,
        official_hits=official,
        accuracy=_ratio(landed_total, len(track.punches)),
        punches_per_minute=(len(track.punches) / minutes) if minutes else 0.0,
        hands=[_hand_stats(name, bucket) for name, bucket in _sorted_hands(hand_buckets)],
        trajectories=[_traj_stats(name, bucket) for name, bucket in sorted(traj_buckets.items())],
        velocity=_velocity(speeds, landed_speeds, landed_deltas, corr_speed, corr_delta),
        punches=rows,
    )


def _sorted_hands(buckets: dict[str, list[PunchRow]]) -> list[tuple[str, list[PunchRow]]]:
    order = {"left": 0, "right": 1, "hand_0": 2, "hand_1": 3, "unmatched": 9}
    return sorted(buckets.items(), key=lambda item: (order.get(item[0], 5), item[0]))


def _hand_stats(name: str, rows: list[PunchRow]) -> HandStats:
    thrown = sum(1 for row in rows if row.hand != "unmatched")
    landed = sum(1 for row in rows if row.landed)
    speeds = [row.speed for row in rows if row.speed is not None]
    index = next((row.hand_index for row in rows if row.hand_index >= 0), None)
    return HandStats(
        hand=name,
        hand_index=index,
        thrown=thrown,
        landed=landed,
        accuracy=_ratio(landed, thrown) if name != "unmatched" else None,
        mean_speed=_mean(speeds),
    )


def _traj_stats(name: str, rows: list[PunchRow]) -> TrajectoryStats:
    thrown = len(rows)
    landed = sum(1 for row in rows if row.landed)
    speeds = [row.speed for row in rows if row.speed is not None]
    return TrajectoryStats(
        trajectory=name,
        thrown=thrown,
        landed=landed,
        accuracy=_ratio(landed, thrown),
        mean_speed=_mean(speeds),
    )


def _velocity(
    speeds: list[float],
    landed_speeds: list[float],
    landed_deltas: list[float],
    corr_speed: list[float],
    corr_delta: list[float],
) -> VelocityStats:
    histogram: list[HistogramBin] = []
    for lo, hi in zip(SPEED_BINS[:-1], SPEED_BINS[1:], strict=True):
        histogram.append(HistogramBin(lo=lo, hi=hi, count=sum(1 for speed in speeds if lo <= speed < hi)))
    return VelocityStats(
        samples=len(speeds),
        mean_thrown=_mean(speeds),
        mean_landed=_mean(landed_speeds),
        max_speed=max(speeds) if speeds else None,
        mean_damage_landed=_mean(landed_deltas),
        speed_damage_correlation=_pearson(corr_speed, corr_delta),
        histogram=histogram,
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 8 or len(xs) != len(ys):
        return None
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return None
    value = float(np.corrcoef(x, y)[0, 1])
    return value if math.isfinite(value) else None


def _under_fire_mask(session: ParsedSession, track: TrackData, body: dict) -> np.ndarray:
    attacker = session.tracks[_opponent(session, track.corner)]
    ticks = body["ticks"]
    mask = np.zeros(len(ticks), dtype=bool)
    if len(ticks) == 0:
        return mask
    for punch in attacker.punches:
        center = int(np.searchsorted(ticks, punch.tick))
        lo = max(0, center - UNDER_FIRE_BEFORE)
        hi = min(len(mask), center + UNDER_FIRE_AFTER + 1)
        if lo < hi:
            mask[lo:hi] = True
    return mask


def _mask_percent(mask: np.ndarray) -> float | None:
    if len(mask) == 0:
        return None
    return float(mask.mean() * 100.0)


def _share(hits: int, total: int) -> float | None:
    if total == 0:
        return None
    return 100.0 * hits / total


def _median_p90(values: list[float]) -> MedianP90:
    if not values:
        return MedianP90()
    samples = np.asarray(values, dtype=np.float64)
    return MedianP90(
        median=_finite(float(np.percentile(samples, 50))),
        p90=_finite(float(np.percentile(samples, 90))),
    )


def _guard_discipline(
    body: dict,
    under_fire: np.ndarray,
    punch_guards: list[_PunchGuard],
    stance: str | None,
    corner: int,
    notes: list[DecodeNote],
) -> GuardDisciplineStats:
    left = body["left_guard"]
    right = body["right_guard"]
    both = body["guard"]
    either = left | right if len(left) else left
    fired = under_fire if len(under_fire) == len(both) else np.zeros(len(both), dtype=bool)
    usable = [row for row in punch_guards if row.rated and row.offhand_in_guard is not None]
    throwing_left = [row for row in usable if row.hand == "left"]
    throwing_right = [row for row in usable if row.hand == "right"]
    lead = [row for row in usable if row.offhand_role == "lead"]
    rear = [row for row in usable if row.offhand_role == "rear"]
    returned = [row for row in punch_guards if row.rated and row.returned is True]
    missed = [row for row in punch_guards if row.rated and row.returned is False]
    times = [float(row.retraction_ms) for row in returned if row.retraction_ms is not None]
    droops = [float(row.retraction_droop_m) for row in returned if row.retraction_droop_m is not None]
    direct = [float(row.retraction_directness) for row in returned if row.retraction_directness is not None]
    lead_field = f"defense.{corner}.guard_discipline.lead_rear"
    if _lead_hand(stance) is None and usable and not any(note.field == lead_field for note in notes):
        notes.append(
            DecodeNote(
                field=lead_field,
                confidence="unavailable",
                note="Lead and rear splits need an orthodox or southpaw stance, and this track has neither.",
            )
        )
    sag = _share(sum(1 for value in droops if value > SAG_DROOP_M), len(droops))
    droop_spread = _median_p90(droops)
    time_samples = np.asarray(times, dtype=np.float64) if times else None
    direct_samples = np.asarray(direct, dtype=np.float64) if direct else None
    return GuardDisciplineStats(
        left_guard_up_percent=_finite(_mask_percent(left)),
        right_guard_up_percent=_finite(_mask_percent(right)),
        both_guard_up_percent=_finite(_mask_percent(both)),
        either_guard_up_percent=_finite(_mask_percent(either)),
        left_guard_up_percent_under_fire=_finite(_mask_percent(left[fired])) if fired.any() else None,
        right_guard_up_percent_under_fire=_finite(_mask_percent(right[fired])) if fired.any() else None,
        both_guard_up_percent_under_fire=_finite(_mask_percent(both[fired])) if fired.any() else None,
        either_guard_up_percent_under_fire=_finite(_mask_percent(either[fired])) if fired.any() else None,
        offhand_guard_kept_percent=_share(sum(1 for row in usable if row.offhand_in_guard), len(usable)),
        offhand_guard_kept_percent_throwing_left=_share(
            sum(1 for row in throwing_left if row.offhand_in_guard), len(throwing_left)
        ),
        offhand_guard_kept_percent_throwing_right=_share(
            sum(1 for row in throwing_right if row.offhand_in_guard), len(throwing_right)
        ),
        offhand_drop_below_head_m_lead=_median_p90([float(row.offhand_drop_m) for row in lead if row.offhand_drop_m is not None]),
        offhand_drop_below_head_m_rear=_median_p90([float(row.offhand_drop_m) for row in rear if row.offhand_drop_m is not None]),
        offhand_lateral_flare_m_lead=_median_p90([float(row.offhand_flare_m) for row in lead if row.offhand_flare_m is not None]),
        offhand_lateral_flare_m_rear=_median_p90([float(row.offhand_flare_m) for row in rear if row.offhand_flare_m is not None]),
        retraction_returned_percent=_share(len(returned), len(returned) + len(missed)),
        retraction_time_ms=RetractionTime(
            median=_finite(float(np.percentile(time_samples, 50))) if time_samples is not None else None,
            mean=_finite(float(time_samples.mean())) if time_samples is not None else None,
            p90=_finite(float(np.percentile(time_samples, 90))) if time_samples is not None else None,
        ),
        retraction_droop_m=RetractionDroop(
            median=droop_spread.median,
            p90=droop_spread.p90,
            sag_over_10cm_percent=sag,
        ),
        retraction_directness_ratio=DirectnessRatio(
            median=_finite(float(np.percentile(direct_samples, 50))) if direct_samples is not None else None,
            mean=_finite(float(direct_samples.mean())) if direct_samples is not None else None,
        ),
    )


@dataclass(frozen=True)
class _AngleCut:
    tick: int
    delta_deg: float
    duration_sec: float
    direction: str


def _bell_spans(windows: list[_RoundWindow]) -> list[tuple[int, int]]:
    """Spans of fighting: bell to the end of the round, with knockdown counts cut out."""
    spans: list[tuple[int, int]] = []
    for window in windows:
        end = window.end_tick or (window.end_bell_tick if window.end_bell_tick is not None else window.stats_end)
        start = window.bell_tick
        for first, last in window.pauses:
            if first > start:
                spans.append((start, min(first, end)))
            start = max(start, last)
        if end >= start:
            spans.append((start, end))
    return spans


def _empty_footwork() -> FootworkStats:
    return FootworkStats()


def _rolling_sum(values: np.ndarray, width: int) -> np.ndarray:
    if width <= 0 or len(values) < width:
        return np.zeros(0, dtype=np.float64)
    cumulative = np.cumsum(values)
    total = cumulative[width - 1 :].copy()
    total[1:] -= cumulative[: len(total) - 1]
    return total


def _fold_blade(forward_comp: np.ndarray, tangent_comp: np.ndarray) -> np.ndarray:
    """Signed angle of a joint line against the fighter's right, folded into [-90, 90]."""
    angle = np.degrees(np.arctan2(forward_comp, -tangent_comp))
    angle = np.where(angle > 90.0, angle - 180.0, angle)
    return np.where(angle < -90.0, angle + 180.0, angle)


def _line_angle(pos: np.ndarray, left: int, right: int, forward: np.ndarray, sideways: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    line = pos[:, left] - pos[:, right]
    line[:, 1] = 0.0
    length = np.linalg.norm(line, axis=1)
    signed = _fold_blade(np.sum(line * forward, axis=1), np.sum(line * sideways, axis=1))
    return signed, length >= MIN_LINE_M


def _sum_sweep(ticks: np.ndarray, sweep: np.ndarray, valid: np.ndarray, start: int, stop: int) -> float:
    if stop <= start or len(sweep) == 0:
        return 0.0
    origins = ticks[:-1]
    selected = valid & (origins >= start) & (origins < stop)
    if not np.any(selected):
        return 0.0
    return float(sweep[selected].sum())


def _angle_cuts(
    ticks: np.ndarray,
    distance: np.ndarray,
    sweep: np.ndarray,
    in_bell: np.ndarray,
    step_valid: np.ndarray,
    timestep: float,
) -> list[_AngleCut]:
    span = int(round(ANGLE_CUT_SEC / timestep))
    count = len(ticks)
    if span <= 0 or count <= span:
        return []
    frame_ok = _rolling_sum(in_bell.astype(np.float64), span + 1) == span + 1
    steps_ok = _rolling_sum(step_valid.astype(np.float64), span) == span
    window = np.lib.stride_tricks.sliding_window_view(distance, span + 1)
    near = window.max(axis=1) < ANGLE_CUT_RANGE_M
    turned = _rolling_sum(sweep, span)
    width = min(len(frame_ok), len(steps_ok), len(near), len(turned))
    if width <= 0:
        return []
    qualifying = np.flatnonzero(frame_ok[:width] & steps_ok[:width] & near[:width] & (np.abs(turned[:width]) >= ANGLE_CUT_DEG))
    if len(qualifying) == 0:
        return []
    groups: list[list[int]] = [[int(qualifying[0])]]
    for start in qualifying[1:]:
        if int(start) <= groups[-1][-1] + span:
            groups[-1].append(int(start))
        else:
            groups.append([int(start)])
    cuts: list[_AngleCut] = []
    for group in groups:
        last = group[-1] + span
        delta = float(sweep[group[0] : last].sum())
        peak = group[int(np.argmax(np.abs(turned[group])))]
        cuts.append(
            _AngleCut(
                tick=int(ticks[peak]),
                delta_deg=delta,
                duration_sec=(last - group[0]) * timestep,
                direction="counterclockwise" if delta >= 0.0 else "clockwise",
            )
        )
    return cuts


@dataclass(frozen=True)
class _GroupedPunch:
    punch: PunchRecord
    span: tuple[int, int] | None = None
    index: int = 0


def _combo_groups(members: list[_GroupedPunch], timestep: float) -> list[list[_GroupedPunch]]:
    """Split on a launch gap past COMBO_GAP_SEC, and when the round span changes."""
    ordered = sorted(members, key=lambda item: (item.punch.launch_tick, item.punch.tick, item.index))
    groups: list[list[_GroupedPunch]] = []
    for item in ordered:
        if not groups:
            groups.append([item])
            continue
        previous = groups[-1][-1]
        gap = (item.punch.launch_tick - previous.punch.launch_tick) * timestep if timestep > 0 else COMBO_GAP_SEC + 1
        crossed = item.span is not None and previous.span is not None and item.span != previous.span
        if gap > COMBO_GAP_SEC or crossed:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def _round_span(punch: PunchRecord, windows: list[_RoundWindow]) -> tuple[int, int] | None:
    for window in windows:
        if window.warning_tick <= punch.tick <= window.stats_end:
            return (window.warning_tick, window.stats_end)
    return None


def _pattern_token(hand: str, trajectory: str) -> str:
    if trajectory in HAND_NAMED_TRAJECTORIES:
        return trajectory
    if hand in {"left", "right"}:
        return f"{hand}_{trajectory}"
    return trajectory


def _hands_alternate(group: list[_GroupedPunch]) -> bool:
    hands = [item.punch.hand_index for item in group]
    return all(left != right for left, right in zip(hands, hands[1:]))


def _tick_radius(seconds: float, timestep: float) -> int:
    if timestep <= 0:
        return 0
    return int(round(seconds / timestep))


def _classify_tick(
    tick: int,
    launches: list[int],
    throw_ticks: int,
    recovery_ticks: int,
) -> tuple[str, int | None]:
    """Return the window name and the launch index the tick belongs to."""
    throwing: tuple[int, int, int] | None = None
    recovery: tuple[int, int, int] | None = None
    for index, launch in enumerate(launches):
        delta = tick - launch
        if abs(delta) <= throw_ticks:
            candidate = (abs(delta), launch, index)
            if throwing is None or candidate < throwing:
                throwing = candidate
        elif throw_ticks < delta <= recovery_ticks:
            candidate = (delta, launch, index)
            if recovery is None or candidate < recovery:
                recovery = candidate
    if throwing is not None:
        return "while_throwing", throwing[2]
    if recovery is not None:
        return "post_punch_recovery", recovery[2]
    return "neutral_guard", None


def _bell_state_counts(
    spans: list[tuple[int, int]],
    launches: list[int],
    throw_ticks: int,
    recovery_ticks: int,
) -> dict[str, int]:
    counts = {name: 0 for name in VULNERABILITY_WINDOWS}
    for start, stop in spans:
        length = stop - start + 1
        if length <= 0:
            continue
        # 0 neutral, 1 recovery, 2 throwing. Throwing is painted last so it wins.
        state = np.zeros(length, dtype=np.int8)
        for launch in launches:
            rel = launch - start
            rec_lo = max(0, rel + throw_ticks + 1)
            rec_hi = min(length - 1, rel + recovery_ticks)
            if rec_lo <= rec_hi:
                state[rec_lo : rec_hi + 1] = np.maximum(state[rec_lo : rec_hi + 1], 1)
            thr_lo = max(0, rel - throw_ticks)
            thr_hi = min(length - 1, rel + throw_ticks)
            if thr_lo <= thr_hi:
                state[thr_lo : thr_hi + 1] = 2
        counts["neutral_guard"] += int(np.count_nonzero(state == 0))
        counts["post_punch_recovery"] += int(np.count_nonzero(state == 1))
        counts["while_throwing"] += int(np.count_nonzero(state == 2))
    return counts


def _combination_stats(
    track: TrackData,
    rows: list[PunchRow],
    timestep: float,
    windows: list[_RoundWindow],
    countered: set[int],
) -> CombinationStats:
    members = [
        _GroupedPunch(punch, _round_span(punch, windows), index) for index, punch in enumerate(track.punches)
    ]
    groups = _combo_groups(members, timestep)
    lengths = [len(group) for group in groups]
    multi = [group for group in groups if len(group) >= 2]
    alternating = sum(1 for group in multi if _hands_alternate(group))
    depth_thrown = {label: 0 for label in DEPTH_LABELS}
    depth_landed = {label: 0 for label in DEPTH_LABELS}
    depth_speeds: dict[str, list[float]] = {label: [] for label in DEPTH_LABELS}
    depth_countered = {label: 0 for label in DEPTH_LABELS}
    patterns: dict[str, list[list[_GroupedPunch]]] = defaultdict(list)
    for combo_id, group in enumerate(groups, start=1):
        tokens: list[str] = []
        for place, member in enumerate(group, start=1):
            row = rows[member.index]
            label = "5+" if place >= 5 else str(place)
            row.combo_id = combo_id
            row.combo_depth = label
            row.countered = member.index in countered
            depth_thrown[label] += 1
            if row.landed:
                depth_landed[label] += 1
            if row.speed is not None:
                depth_speeds[label].append(row.speed)
            if member.index in countered:
                depth_countered[label] += 1
            tokens.append(_pattern_token(row.hand, row.trajectory))
        patterns["-".join(tokens)].append(group)
    pattern_rows: list[ComboPatternStats] = []
    for pattern, instances in patterns.items():
        thrown = 0
        landed = 0
        speeds: list[float] = []
        instance_damage: list[float] = []
        landed_deltas: list[float] = []
        for group in instances:
            damage = 0.0
            for member in group:
                row = rows[member.index]
                thrown += 1
                if row.speed is not None:
                    speeds.append(row.speed)
                if row.landed:
                    landed += 1
                    if row.damage is not None:
                        damage += row.damage
                        landed_deltas.append(row.damage)
            instance_damage.append(damage)
        pattern_rows.append(
            ComboPatternStats(
                pattern=pattern,
                count=len(instances),
                length=len(instances[0]),
                thrown=thrown,
                landed=landed,
                accuracy=_ratio(landed, thrown),
                mean_speed=_mean(speeds),
                mean_damage=_mean(instance_damage),
                mean_damage_landed=_mean(landed_deltas),
            )
        )
    pattern_rows.sort(key=lambda item: (-item.count, item.pattern))
    return CombinationStats(
        combo_count=len(groups),
        mean_combo_length=_mean([float(length) for length in lengths]),
        max_combo_length=max(lengths) if lengths else 0,
        single_shot_percent=_finite(100.0 * sum(1 for length in lengths if length == 1) / len(lengths)) if lengths else None,
        alternating_hand_percent=_finite(100.0 * alternating / len(multi)) if multi else None,
        by_depth=[
            DepthStats(
                depth=label,
                thrown=depth_thrown[label],
                landed=depth_landed[label],
                accuracy=_ratio(depth_landed[label], depth_thrown[label]),
                mean_speed=_mean(depth_speeds[label]),
                countered_count=depth_countered[label],
                countered_rate=_ratio(depth_countered[label], depth_thrown[label]),
            )
            for label in DEPTH_LABELS
        ],
        patterns=pattern_rows,
    )


def _vulnerability_window(
    hits: int,
    hit_total: int,
    ticks: int,
    tick_total: int,
    opponent_thrown: int,
    opponent_landed: int,
) -> VulnerabilityWindow:
    hit_share = _share(hits, hit_total)
    time_share = _share(ticks, tick_total)
    risk = None
    if hit_share is not None and time_share is not None and time_share > 0:
        risk = hit_share / time_share
    return VulnerabilityWindow(
        hits=hits,
        hit_share=_finite(hit_share),
        time_share=_finite(time_share),
        risk_ratio=_finite(risk),
        opponent_thrown=opponent_thrown,
        opponent_landed=opponent_landed,
        opponent_accuracy=_ratio(opponent_landed, opponent_thrown),
    )


def _vulnerability_stats(
    launches: list[int],
    hit_ticks: list[int],
    opponent_punches: list[PunchRecord],
    opponent_landed: set[int],
    spans: list[tuple[int, int]],
    timestep: float,
) -> tuple[VulnerabilityStats, set[int]]:
    throw_ticks = _tick_radius(THROW_WINDOW_SEC, timestep)
    recovery_ticks = _tick_radius(RECOVERY_WINDOW_SEC, timestep)
    hit_counts = {name: 0 for name in VULNERABILITY_WINDOWS}
    countered: set[int] = set()
    for tick in hit_ticks:
        window, index = _classify_tick(tick, launches, throw_ticks, recovery_ticks)
        hit_counts[window] += 1
        if index is not None:
            countered.add(index)
    time_counts = _bell_state_counts(spans, launches, throw_ticks, recovery_ticks)
    tick_total = sum(time_counts.values())
    thrown = {name: 0 for name in VULNERABILITY_WINDOWS}
    landed = {name: 0 for name in VULNERABILITY_WINDOWS}
    for index, punch in enumerate(opponent_punches):
        window, _ignored = _classify_tick(punch.launch_tick, launches, throw_ticks, recovery_ticks)
        thrown[window] += 1
        if index in opponent_landed:
            landed[window] += 1
    hit_total = len(hit_ticks)
    windows = {
        name: _vulnerability_window(
            hit_counts[name],
            hit_total,
            time_counts[name],
            tick_total,
            thrown[name],
            landed[name],
        )
        for name in VULNERABILITY_WINDOWS
    }
    return (
        VulnerabilityStats(
            while_throwing=windows["while_throwing"],
            post_punch_recovery=windows["post_punch_recovery"],
            neutral_guard=windows["neutral_guard"],
        ),
        countered,
    )


def _attach_combinations(
    session: ParsedSession,
    offense: list[OffenseStats],
    defense: list[DefenseStats],
    landed_events: dict[int, list[EventRecord]],
    matches: dict[int, dict[int, EventRecord]],
    windows: list[_RoundWindow],
) -> None:
    """Combination tables and the counter windows that mark a punch as countered."""
    spans = _bell_spans(windows)
    offense_by = {item.corner: item for item in offense}
    defense_by = {item.corner: item for item in defense}
    for track in _ordered(session):
        opponent = _opponent(session, track.corner)
        launches = [punch.launch_tick for punch in track.punches]
        hits = [event.tick for event in landed_events[track.corner]]
        vulnerability, countered = _vulnerability_stats(
            launches,
            hits,
            session.tracks[opponent].punches,
            set(matches[opponent]),
            spans,
            session.fixed_timestep,
        )
        defense_block = defense_by.get(track.corner)
        if defense_block is not None:
            defense_block.vulnerability = vulnerability
        offense_block = offense_by.get(track.corner)
        if offense_block is not None:
            offense_block.combinations = _combination_stats(
                track,
                offense_block.punches,
                session.fixed_timestep,
                windows,
                countered,
            )


def _combo_angles(
    track: TrackData,
    ticks: np.ndarray,
    sweep: np.ndarray,
    valid: np.ndarray,
    spans: list[tuple[int, int]],
    timestep: float,
    covered: bool,
) -> tuple[float | None, float | None]:
    exit_ticks = int(round(COMBO_EXIT_SEC / timestep))
    members: list[_GroupedPunch] = []
    for punch in track.punches:
        span = next((item for item in spans if item[0] <= punch.launch_tick <= item[1]), None)
        if span is not None:
            members.append(_GroupedPunch(punch, span))
    groups = _combo_groups(members, timestep)
    if not groups or not covered:
        return None, None
    entries: list[float] = []
    exits: list[float] = []
    for group in groups:
        first = group[0]
        last = group[-1]
        span = first.span or (first.punch.launch_tick, last.punch.tick)
        entries.append(_sum_sweep(ticks, sweep, valid, first.punch.launch_tick, min(last.punch.tick, span[1])))
        exits.append(_sum_sweep(ticks, sweep, valid, last.punch.tick, min(last.punch.tick + exit_ticks, span[1])))
    return float(np.mean(entries)), float(np.mean(exits))


def _footwork(
    track: TrackData,
    opponent: TrackData,
    spans: list[tuple[int, int]],
    timestep: float,
) -> tuple[FootworkStats, list[_AngleCut]]:
    """Hips path, range, stance, and angle cuts on bell-to-end-bell frames."""
    ticks = track.skeleton_ticks.astype(np.int64)
    if len(ticks) == 0 or not spans or len(opponent.skeleton_ticks) == 0 or timestep <= 0:
        return _empty_footwork(), []
    forward, right = _local_axes(track, opponent)
    pos = track.skeleton_pos.astype(np.float64)
    nearest = _nearest_index(opponent.skeleton_ticks.astype(np.int64), ticks)
    delta = opponent.skeleton_pos[nearest, HIPS].astype(np.float64) - pos[:, HIPS]
    delta[:, 1] = 0.0
    distance = np.linalg.norm(delta, axis=1)
    in_bell = np.zeros(len(ticks), dtype=bool)
    for start, stop in spans:
        in_bell |= (ticks >= start) & (ticks <= stop)
    step = np.diff(pos[:, HIPS], axis=0)
    step[:, 1] = 0.0
    step_valid = np.diff(ticks) == 1
    radial_step = np.sum(step * forward[:-1], axis=1)
    tangent_step = np.sum(step * right[:-1], axis=1)
    distance_at_start = distance[:-1]
    sweep = np.zeros(len(tangent_step), dtype=np.float64)
    measurable = step_valid & (distance_at_start >= MIN_RANGE_M)
    sweep[measurable] = np.degrees(tangent_step[measurable] / distance_at_start[measurable])
    counted = step_valid & in_bell[:-1]
    radial = float(np.abs(radial_step[counted]).sum()) if np.any(counted) else 0.0
    clockwise = float(np.abs(tangent_step[counted & (tangent_step < 0.0)]).sum()) if np.any(counted) else 0.0
    counterclockwise = float(tangent_step[counted & (tangent_step > 0.0)].sum()) if np.any(counted) else 0.0
    tangential = clockwise + counterclockwise
    total = radial + tangential
    samples = distance[in_bell]
    shoulder, shoulder_ok = _line_angle(pos, L_SHOULDER, R_SHOULDER, forward, right)
    foot_line, foot_ok = _line_angle(pos, L_ANKLE, R_ANKLE, forward, right)
    shoulder_samples = shoulder[in_bell & shoulder_ok]
    foot_samples = foot_line[in_bell & foot_ok]
    launch_angles: list[float] = []
    bell_index = {int(tick): index for index, tick in enumerate(ticks) if in_bell[index]}
    for punch in track.punches:
        if not any(start <= punch.launch_tick <= stop for start, stop in spans):
            continue
        index = bell_index.get(punch.launch_tick)
        if index is None or not shoulder_ok[index]:
            continue
        launch_angles.append(float(shoulder[index]))
    cuts = _angle_cuts(ticks, distance, sweep, in_bell, step_valid, timestep)
    entry, exit_angle = _combo_angles(track, ticks, sweep, measurable & in_bell[:-1], spans, timestep, bool(np.any(in_bell)))
    square_while = None
    if launch_angles:
        square_while = 100.0 * sum(abs(angle) < SQUARE_BLADE_DEG for angle in launch_angles) / len(launch_angles)
    stats = FootworkStats(
        total_distance_m=_finite(total) if len(samples) else None,
        radial_distance_m=_finite(radial) if len(samples) else None,
        tangential_distance_m=_finite(tangential) if len(samples) else None,
        tangential_share=_finite(tangential / total) if total > 0.0 else None,
        clockwise_distance_m=_finite(clockwise) if len(samples) else None,
        counterclockwise_distance_m=_finite(counterclockwise) if len(samples) else None,
        angle_cut_count=len(cuts),
        attack_entry_angle_deg=_finite(entry),
        post_combo_exit_angle_deg=_finite(exit_angle),
        fighter_distance_m=_distance_spread(samples),
        clinch_range_percent=_finite(float(np.mean(samples < CLINCH_RANGE_M) * 100.0)) if len(samples) else None,
        pocket_range_percent=_finite(float(np.mean((samples >= CLINCH_RANGE_M) & (samples <= POCKET_RANGE_M)) * 100.0))
        if len(samples)
        else None,
        outside_range_percent=_finite(float(np.mean(samples > POCKET_RANGE_M) * 100.0)) if len(samples) else None,
        shoulder_blade_angle_deg=_finite(float(np.percentile(np.abs(shoulder_samples), 50))) if len(shoulder_samples) else None,
        foot_blade_angle_deg=_finite(float(np.percentile(np.abs(foot_samples), 50))) if len(foot_samples) else None,
        square_stance_percent=_finite(float(np.mean(np.abs(shoulder_samples) < SQUARE_BLADE_DEG) * 100.0))
        if len(shoulder_samples)
        else None,
        lead_left_percent=_finite(float(np.mean(shoulder_samples >= SQUARE_BLADE_DEG) * 100.0))
        if len(shoulder_samples)
        else None,
        square_while_punching_percent=_finite(square_while),
    )
    return stats, cuts


def _distance_spread(samples: np.ndarray) -> DistanceSpread:
    if len(samples) == 0:
        return DistanceSpread()
    return DistanceSpread(
        mean=_finite(float(samples.mean())),
        p10=_finite(float(np.percentile(samples, 10))),
        median=_finite(float(np.percentile(samples, 50))),
        p90=_finite(float(np.percentile(samples, 90))),
    )


def _angle_cut_moments(session: ParsedSession, cuts: dict[int, list[_AngleCut]]) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    for corner, bursts in cuts.items():
        for burst in bursts:
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, burst.tick),
                    tick=burst.tick,
                    type="angle_cut",
                    corners=[corner],
                    detail={
                        "delta_deg": round(burst.delta_deg, 4),
                        "duration_sec": round(burst.duration_sec, 4),
                        "direction": burst.direction,
                    },
                )
            )
    return moments


@dataclass(frozen=True)
class _HeadEvent:
    tick: int
    drop_m: float
    duration_sec: float
    slip_delta_m: float | None = None


def _empty_head_movement() -> HeadMovementStats:
    return HeadMovementStats()


def _iqr(samples: np.ndarray) -> float:
    return float(np.percentile(samples, 75) - np.percentile(samples, 25))


def _punching_mask(ticks: np.ndarray, in_bell: np.ndarray, punches: list[PunchRecord]) -> np.ndarray:
    mask = np.zeros(len(ticks), dtype=bool)
    for punch in punches:
        if punch.tick < punch.launch_tick:
            continue
        mask |= in_bell & (ticks >= punch.launch_tick) & (ticks <= punch.tick)
    return mask


def _off_center_percent(abs_slip: np.ndarray, mask: np.ndarray) -> float | None:
    selected = abs_slip[mask]
    if len(selected) == 0:
        return None
    return float(np.mean(selected >= OFF_CENTERLINE_M) * 100.0)


def _slip_spread(samples: np.ndarray, under_fire: np.ndarray) -> SlipSpread:
    if len(samples) == 0:
        return SlipSpread()
    fired = samples[under_fire] if len(under_fire) == len(samples) else samples[:0]
    return SlipSpread(
        median=_finite(float(np.percentile(samples, 50))),
        p90=_finite(float(np.percentile(samples, 90))),
        under_fire_p90=_finite(float(np.percentile(fired, 90))) if len(fired) else None,
    )


def _u_shapes(
    ticks: np.ndarray,
    height: np.ndarray,
    in_bell: np.ndarray,
    slip: np.ndarray | None,
    timestep: float,
    window_sec: float,
    drop_m: float,
    slip_m: float | None,
) -> list[_HeadEvent]:
    """Merged U-shaped head drops on consecutive bell-span frames."""
    span = int(round(window_sec / timestep))
    count = len(ticks)
    if span <= 1 or count <= span or timestep <= 0:
        return []
    step_valid = np.diff(ticks) == 1
    steps_ok = _rolling_sum(step_valid.astype(np.float64), span) == span
    frame_ok = _rolling_sum(in_bell.astype(np.float64), span + 1) == span + 1
    windows = np.lib.stride_tricks.sliding_window_view(height, span + 1)
    width = min(len(frame_ok), len(steps_ok), len(windows))
    if width <= 0:
        return []
    windows = windows[:width]
    trough = windows.argmin(axis=1)
    inside = (trough > 0) & (trough < span)
    trough_y = windows[np.arange(width), trough]
    fall = windows[:, 0] - trough_y
    rise = windows[:, -1] - trough_y
    qualifying_mask = frame_ok[:width] & steps_ok[:width] & inside & (fall >= drop_m) & (rise >= drop_m)
    slip_range = None
    if slip_m is not None and slip is not None:
        slip_windows = np.lib.stride_tricks.sliding_window_view(slip, span + 1)[:width]
        slip_range = slip_windows.max(axis=1) - slip_windows.min(axis=1)
        qualifying_mask = qualifying_mask & (slip_range >= slip_m)
    qualifying = np.flatnonzero(qualifying_mask)
    if len(qualifying) == 0:
        return []
    groups: list[list[int]] = [[int(qualifying[0])]]
    for start in qualifying[1:]:
        if int(start) <= groups[-1][-1] + span:
            groups[-1].append(int(start))
        else:
            groups.append([int(start)])
    events: list[_HeadEvent] = []
    for group in groups:
        best = max(group, key=lambda start: float(fall[start]))
        events.append(
            _HeadEvent(
                tick=int(ticks[best + int(trough[best])]),
                drop_m=float(fall[best]),
                duration_sec=(group[-1] + span - group[0]) * timestep,
                slip_delta_m=None if slip_range is None else float(slip_range[best]),
            )
        )
    return events


def _head_movement(
    session: ParsedSession,
    track: TrackData,
    opponent: TrackData,
    spans: list[tuple[int, int]],
    timestep: float,
) -> tuple[HeadMovementStats, list[_HeadEvent], list[_HeadEvent]]:
    """Bell-span slip, level change, ducks, and bob-and-weave on the opponent frame."""
    ticks = track.skeleton_ticks.astype(np.int64)
    if len(ticks) == 0 or not spans or len(opponent.skeleton_ticks) == 0 or timestep <= 0:
        return _empty_head_movement(), [], []
    right = _local_axes(track, opponent)[1]
    pos = track.skeleton_pos.astype(np.float64)
    offset = pos[:, HEAD] - pos[:, HIPS]
    slip_lat = np.sum(offset * right, axis=1)
    in_bell = np.zeros(len(ticks), dtype=bool)
    for start, stop in spans:
        in_bell |= (ticks >= start) & (ticks <= stop)
    if not np.any(in_bell):
        return _empty_head_movement(), [], []
    under_fire = _under_fire_mask(session, track, {"ticks": ticks}) & in_bell
    punching = _punching_mask(ticks, in_bell, track.punches)
    abs_slip = np.abs(slip_lat)
    head_y = pos[in_bell, HEAD, 1]
    hips_y = pos[in_bell, HIPS, 1]
    pelvis_drop = float(np.percentile(hips_y, 90)) - hips_y
    ducks = _u_shapes(ticks, pos[:, HEAD, 1], in_bell, None, timestep, DUCK_WINDOW_SEC, DUCK_DROP_M, None)
    weaves = _u_shapes(
        ticks,
        pos[:, HEAD, 1],
        in_bell,
        slip_lat,
        timestep,
        WEAVE_WINDOW_SEC,
        WEAVE_DROP_M,
        WEAVE_SLIP_M,
    )
    stats = HeadMovementStats(
        head_lateral_slip_m=_slip_spread(abs_slip[in_bell], under_fire[in_bell]),
        off_centerline_percent=_finite(_off_center_percent(abs_slip, in_bell)),
        off_centerline_under_fire_percent=_finite(_off_center_percent(abs_slip, under_fire)),
        off_centerline_while_punching_percent=_finite(_off_center_percent(abs_slip, punching)),
        head_height_iqr_m=_finite(_iqr(head_y)),
        p05_p95_span_m=_finite(float(np.percentile(head_y, 95) - np.percentile(head_y, 5))),
        pelvis_drop_iqr_m=_finite(_iqr(pelvis_drop)),
        trunk_bend_iqr_m=_finite(_iqr(head_y - hips_y)),
        duck_count=len(ducks),
        bob_and_weave_count=len(weaves),
    )
    return stats, ducks, weaves


def _head_event_moments(session: ParsedSession, events: dict[int, list[_HeadEvent]], type_name: str) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    for corner, rows in events.items():
        for event in rows:
            detail = {
                "drop_m": round(event.drop_m, 4),
                "duration_sec": round(event.duration_sec, 4),
            }
            if event.slip_delta_m is not None:
                detail["slip_delta_m"] = round(event.slip_delta_m, 4)
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, event.tick),
                    tick=event.tick,
                    type=type_name,
                    corners=[corner],
                    detail=detail,
                )
            )
    return moments


def _defense(
    session: ParsedSession,
    track: TrackData,
    body: dict,
    totals: dict[int, dict],
    notes: list[DecodeNote],
    punch_guards: list[_PunchGuard],
    footwork: FootworkStats,
    head_movement: HeadMovementStats,
) -> DefenseStats:
    mask = _under_fire_mask(session, track, body)
    guard = body["guard"]
    guard_pct = float(guard.mean() * 100.0) if len(guard) else None
    under = guard[mask]
    under_pct = float(under.mean() * 100.0) if mask.any() else None
    head = body["head_xyz"]
    step = _head_speed(head, session.fixed_timestep)
    speed_mask = mask[1:] if len(mask) == len(step) + 1 else mask[: len(step)]
    mean_speed = float(step.mean()) if len(step) else None
    under_speed = float(step[speed_mask].mean()) if speed_mask.any() else None
    quiet = ~speed_mask
    quiet_speed = float(step[quiet].mean()) if quiet.any() else None
    if len(head):
        vertical = float(head[:, 1].max() - head[:, 1].min())
        lateral = math.hypot(
            float(head[:, 0].max() - head[:, 0].min()),
            float(head[:, 2].max() - head[:, 2].min()),
        )
    else:
        vertical = None
        lateral = None
    if body["left"] is None or body["right"] is None:
        notes.append(
            DecodeNote(
                field=f"defense.{track.corner}.guard_up_percent",
                confidence="unavailable",
                note="Guard-up needs skeleton frames for both wrists, and this slice has none.",
            )
        )
        guard_pct = None
        under_pct = None
    if track.punishment.size:
        peaks = [float(np.max(track.punishment[:, channel])) for channel in range(track.punishment.shape[1])]
    else:
        peaks = []
    dt = session.fixed_timestep
    return DefenseStats(
        corner=track.corner,
        guard_up_percent=_finite(guard_pct),
        guard_up_percent_under_fire=_finite(under_pct),
        under_fire_seconds=round(float(mask.sum()) * dt, 4),
        head_mean_speed=_finite(mean_speed),
        head_mean_speed_under_fire=_finite(under_speed),
        head_mean_speed_not_under_fire=_finite(quiet_speed),
        head_vertical_range=_finite(vertical),
        head_lateral_range=_finite(lateral),
        head_joint_index=int(body["head"]),
        punishment_peak=peaks,
        received_damage_official=float(totals.get(track.corner, {}).get("received_damage", 0.0)),
        guard_discipline=_guard_discipline(body, mask, punch_guards, track.stance, track.corner, notes),
        footwork=footwork,
        head_movement=head_movement,
    )


def _key_moments(
    session: ParsedSession,
    matches: dict[int, dict[int, EventRecord]],
    bodies: dict[int, dict],
    totals: dict[int, dict],
    notes: list[DecodeNote],
    clock_ticks: set[int] | None = None,
) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    moments.extend(_outcome_moments(session, totals, notes, clock_ticks or set()))
    moments.extend(_exchange_moments(session))
    moments.extend(_punishment_spikes(session))
    moments.extend(_fast_lands(session, matches))
    moments.extend(_head_drops(session, bodies))
    moments.sort(key=lambda item: (item.t_sec, item.type))
    return moments


def _outcome_moments(
    session: ParsedSession,
    totals: dict[int, dict],
    notes: list[DecodeNote],
    clock_ticks: set[int],
) -> list[KeyMoment]:
    """Stuns and knockdowns from the kind of each hit taken, and the stoppage from the phase markers."""
    moments: list[KeyMoment] = []
    kinds = {
        HIT_KIND_STUN: "stun",
        HIT_KIND_PUNISHMENT_STUN: "punishment_stun",
        HIT_KIND_PUNISHMENT_KNOCKDOWN: "knockdown",
        HIT_KIND_KNOCKDOWN: "knockdown",
    }
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for track in session.tracks.values():
        for event in track.events:
            label = kinds.get(event.hit_kind) if event.landed_hit else None
            if label is None:
                continue
            counts[(track.corner, label)] += 1
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, event.tick),
                    tick=event.tick,
                    type=label,
                    corners=[track.corner],
                    detail={
                        "hit_kind": HIT_KIND_LABEL.get(event.hit_kind, str(event.hit_kind)),
                        "damage": round(float(event.damage), 4) if event.damage is not None else None,
                    },
                )
            )
    for label, field, kind_note in (
        ("stun", "stuns", "A stun is a hit taken whose byte 8 is 6."),
        ("punishment_stun", "punishment_stuns", "A punishment stun is a hit taken whose byte 8 is 7."),
        (
            "knockdown",
            "all_knockdowns",
            "A knockdown is timed at the blow that starts the count: a hit taken whose byte 8 is 2 or 5.",
        ),
    ):
        expected = {corner: int(row.get(field, 0)) for corner, row in totals.items()}
        if not any(expected.values()) and not any(key[1] == label for key in counts):
            continue
        agrees = all(counts.get((corner, label), 0) == value for corner, value in expected.items())
        notes.append(
            DecodeNote(
                field=f"timeline.{label}",
                confidence="confirmed" if agrees else "inferred",
                note=kind_note
                + (
                    f" The count matches the scorecard's {field} for both fighters."
                    if agrees
                    else f" The count did not match the scorecard's {field}."
                ),
            )
        )
    ko_corners = [corner for corner, row in totals.items() if row.get("knocked_out")]
    if len(ko_corners) == 1:
        stops = sorted(
            {
                event.tick
                for track in session.tracks.values()
                for event in track.events
                if event.type_code == PHASE_EVENT_TYPE and event.phase == PHASE_FIGHT_OVER
            }
        )
        results = sorted(
            {
                event.tick
                for track in session.tracks.values()
                for event in track.events
                if event.type_code == RESULT_EVENT_TYPE
            }
        )
        tick = stops[0] if stops else (results[0] if results else None)
        if tick is not None:
            notes.append(
                DecodeNote(
                    field="timeline.knockout",
                    confidence="inferred",
                    note=(
                        "The knockout is timed at the type-5 phase marker whose byte 9 is 9 (fight over), "
                        "on the corner the scorecard flags knocked out. "
                        "The type-6 event is the result announcement a few seconds later."
                        if stops
                        else "No fight-over phase marker was found, so the knockout is timed at the type-6 result event."
                    ),
                )
            )
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, tick),
                    tick=tick,
                    type="knockout",
                    corners=[ko_corners[0]],
                    detail={"marker": "fight_over_phase" if stops else "result_event"},
                )
            )
    return moments


def _exchange_moments(session: ParsedSession) -> list[KeyMoment]:
    duration = session.duration_sec
    if duration <= 0:
        return []
    edges = np.arange(0.0, duration + 1.0, 1.0)
    counts = {}
    for corner, track in session.tracks.items():
        times = np.array([_sec(session, punch.tick) for punch in track.punches], dtype=np.float64)
        counts[corner] = np.histogram(times, bins=edges)[0]
    moments: list[KeyMoment] = []
    active: list[int] = []
    corners = sorted(session.tracks)
    for index in range(len(edges) - 1):
        hot = all(int(counts[corner][index]) >= EXCHANGE_MIN_EACH for corner in corners)
        if hot:
            active.append(index)
            continue
        if active:
            moments.append(_exchange(session, edges, counts, corners, active))
            active = []
    if active:
        moments.append(_exchange(session, edges, counts, corners, active))
    return moments


def _exchange(session, edges, counts, corners, indexes: list[int]) -> KeyMoment:
    start = float(edges[indexes[0]])
    end = float(edges[indexes[-1] + 1])
    detail = {"window_sec": round(end - start, 3)}
    for corner in corners:
        thrown = int(sum(int(counts[corner][index]) for index in indexes))
        detail[f"corner_{corner}_punches"] = thrown
    mid = (start + end) / 2.0
    tick = session.start_tick + int(round(mid / session.fixed_timestep))
    return KeyMoment(
        t_sec=round(mid, 4),
        tick=tick,
        type="exchange",
        corners=list(corners),
        detail=detail,
    )


def _punishment_spikes(session: ParsedSession) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    for track in session.tracks.values():
        score = track.punishment[:, 0] + track.punishment[:, 1]
        last_tick = -10_000
        for index in range(1, len(score)):
            step = float(score[index] - score[index - 1])
            tick = int(track.punishment_ticks[index])
            if step < 8.0 or tick - last_tick < 48:
                if step >= 8.0:
                    last_tick = tick
                continue
            last_tick = tick
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, tick),
                    tick=tick,
                    type="punishment_spike",
                    corners=[track.corner],
                    detail={"punishment_step": round(step, 4)},
                )
            )
    return moments


def _fast_lands(session: ParsedSession, matches: dict[int, dict[int, EventRecord]]) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    for track in session.tracks.values():
        landed = [
            punch
            for index, punch in enumerate(track.punches)
            if index in matches.get(track.corner, {}) and punch.speed is not None
        ]
        if not landed:
            continue
        cutoff = float(np.percentile([punch.speed for punch in landed], 75))
        chosen = sorted(
            (punch for punch in landed if punch.speed is not None and punch.speed >= cutoff),
            key=lambda punch: punch.speed or 0.0,
            reverse=True,
        )[:8]
        for punch in chosen:
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, punch.tick),
                    tick=punch.tick,
                    type="high_velocity_landed",
                    corners=[track.corner],
                    detail={"speed": round(float(punch.speed or 0.0), 4), "percentile_cutoff": round(cutoff, 4)},
                )
            )
    return moments


def _head_drops(session: ParsedSession, bodies: dict[int, dict]) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    for corner, body in bodies.items():
        height = body["head_xyz"][:, 1]
        ticks = body["ticks"]
        last = -10_000
        span = HEAD_DROP_TICKS
        for index in range(0, len(height) - span, 6):
            drop = float(height[index] - height[index + span])
            tick = int(ticks[index + span])
            if drop < HEAD_DROP_METERS or tick - last < 120:
                continue
            last = tick
            moments.append(
                KeyMoment(
                    t_sec=_sec(session, tick),
                    tick=tick,
                    type="head_drop",
                    corners=[corner],
                    detail={"drop_m": round(drop, 4), "window_sec": round(span * session.fixed_timestep, 4)},
                )
            )
    return moments


def _head_speed(head: np.ndarray, dt: float) -> np.ndarray:
    step = np.linalg.norm(np.diff(head, axis=0), axis=1) / dt
    # Single-frame jumps above this are skeleton glitches, not head movement.
    return np.minimum(step, HEAD_SPEED_CAP)


def _bucket(times: np.ndarray, values: np.ndarray, step: float) -> tuple[list[float], list[float]]:
    if len(times) == 0:
        return [], []
    start = float(times[0])
    end = float(times[-1])
    edges = np.arange(start, end + step, step)
    if len(edges) < 2:
        return [round(start, 4)], [float(values.mean())]
    out_t: list[float] = []
    out_y: list[float] = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        selected = (times >= lo) & (times < hi)
        if not np.any(selected):
            continue
        out_t.append(round(float((lo + hi) / 2.0), 4))
        out_y.append(round(float(values[selected].mean()), 4))
    return out_t, out_y


def _series(session: ParsedSession, bodies: dict[int, dict]) -> list[Series]:
    series: list[Series] = []
    for track in _ordered(session):
        t_pun = np.array([_sec(session, int(tick)) for tick in track.punishment_ticks])
        for channel in range(track.punishment.shape[1]):
            ts, ys = _bucket(t_pun, track.punishment[:, channel], SERIES_STEP_SEC)
            series.append(Series(name=f"punishment_{channel}", corner=track.corner, t=ts, y=ys))
        t_guard = np.array([_sec(session, int(tick)) for tick in track.guard_ticks])
        names = ("guard_brace", "guard_friction", "guard_mass", "guard_ladder")
        for channel, name in enumerate(names):
            ts, ys = _bucket(t_guard, track.guard_primary[:, channel], SERIES_STEP_SEC)
            series.append(Series(name=name, corner=track.corner, t=ts, y=ys))
        body = bodies[track.corner]
        t_body = np.array([_sec(session, int(tick)) for tick in body["ticks"]])
        ts, ys = _bucket(t_body, body["guard"].astype(np.float32), 1.0)
        series.append(Series(name="guard_up", corner=track.corner, t=ts, y=ys))
        ts, ys = _bucket(t_body, body["left_guard"].astype(np.float32), 1.0)
        series.append(Series(name="left_guard_up", corner=track.corner, t=ts, y=ys))
        ts, ys = _bucket(t_body, body["right_guard"].astype(np.float32), 1.0)
        series.append(Series(name="right_guard_up", corner=track.corner, t=ts, y=ys))
        head = body["head_xyz"]
        if len(head) > 1:
            speed = _head_speed(head, session.fixed_timestep)
            ts, ys = _bucket(t_body[1:], speed.astype(np.float32), SERIES_STEP_SEC)
            series.append(Series(name="head_speed", corner=track.corner, t=ts, y=ys))
            ts, ys = _bucket(t_body, head[:, 1], SERIES_STEP_SEC)
            series.append(Series(name="head_height", corner=track.corner, t=ts, y=ys))
        ticks = track.skeleton_ticks.astype(np.int64)
        if len(ticks):
            hips = track.skeleton_pos[:, HIPS, :].astype(np.float64)
            ts_x, ys_x = _bucket(t_body, hips[:, 0], SERIES_STEP_SEC)
            ts_z, ys_z = _bucket(t_body, hips[:, 2], SERIES_STEP_SEC)
            series.append(Series(name="hips_x", corner=track.corner, t=ts_x, y=ys_x))
            series.append(Series(name="hips_z", corner=track.corner, t=ts_z, y=ys_z))
        else:
            series.append(Series(name="hips_x", corner=track.corner, t=[], y=[]))
            series.append(Series(name="hips_z", corner=track.corner, t=[], y=[]))
        opponent = session.tracks[_opponent(session, track.corner)]
        if len(ticks) and len(opponent.skeleton_ticks) and session.fixed_timestep > 0:
            forward, right = _local_axes(track, opponent)
            pos = track.skeleton_pos.astype(np.float64)
            slip_lat = np.sum((pos[:, HEAD] - pos[:, HIPS]) * right, axis=1)
            ts, ys = _bucket(t_body, slip_lat, SERIES_STEP_SEC)
            series.append(Series(name="head_slip_lateral", corner=track.corner, t=ts, y=ys))
            nearest = _nearest_index(opponent.skeleton_ticks.astype(np.int64), ticks)
            delta = opponent.skeleton_pos[nearest, HIPS].astype(np.float64) - pos[:, HIPS]
            delta[:, 1] = 0.0
            distance = np.linalg.norm(delta, axis=1)
            ts, ys = _bucket(t_body, distance, SERIES_STEP_SEC)
            series.append(Series(name="fighter_distance", corner=track.corner, t=ts, y=ys))
            shoulder, shoulder_ok = _line_angle(pos, L_SHOULDER, R_SHOULDER, forward, right)
            ts, ys = _bucket(t_body[shoulder_ok], shoulder[shoulder_ok], SERIES_STEP_SEC)
            series.append(Series(name="blade_angle", corner=track.corner, t=ts, y=ys))
            if len(ticks) > 1:
                step = np.diff(pos[:, HIPS], axis=0)
                step[:, 1] = 0.0
                step_valid = np.diff(ticks) == 1
                tangent_speed = np.sum(step * right[:-1], axis=1) / session.fixed_timestep
                ts, ys = _bucket(t_body[1:][step_valid], tangent_speed[step_valid], SERIES_STEP_SEC)
                series.append(Series(name="tangential_speed", corner=track.corner, t=ts, y=ys))
        else:
            for name in ("head_slip_lateral", "fighter_distance", "blade_angle", "tangential_speed"):
                series.append(Series(name=name, corner=track.corner, t=[], y=[]))
        t_stiff = np.array([_sec(session, int(tick)) for tick in track.stiffness_ticks])
        stiff = np.max(track.stiffness, axis=1)
        ts, ys = _bucket(t_stiff, stiff, SERIES_STEP_SEC)
        series.append(Series(name="stiffness_max", corner=track.corner, t=ts, y=ys))
        duration = session.duration_sec
        times = np.array([_sec(session, punch.tick) for punch in track.punches], dtype=np.float64)
        origin = min(0.0, float(np.floor(times.min()))) if len(times) else 0.0
        edges = np.arange(origin, max(duration, origin + 0.01) + 1.0, 1.0)
        hist, _edges = np.histogram(times, bins=edges)
        centers = [round(float((lo + hi) / 2.0), 4) for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
        series.append(
            Series(name="punch_density", corner=track.corner, t=centers, y=[int(value) for value in hist])
        )
    return series


def _static_notes() -> list[DecodeNote]:
    return [
        DecodeNote(
            field="time",
            confidence="confirmed",
            note="Seconds are (tick - startTick) × fixedTimestep from metadata.",
        ),
        DecodeNote(
            field="rounds",
            confidence="inferred",
            note=(
                "A type-5 event marks a change of match phase, and byte 9 is the phase: 2 warning, 4 fight, 3 round end, "
                "5 and 6 a knockdown count, 9 fight over, 10 end of recording. "
                "A completed round runs from the warning to just after the round ends. "
                "The warning and the bell are 735 ticks apart. The round ends at the first round-end or fight-over marker, "
                "so a stoppage ends the round there and not at the end of the recording. "
                "Skeleton, guard, and meter samples inside a knockdown count are left out, "
                "and a round's duration_sec is its fighting time: bell to end, less the counts. "
                "Round stats, charts, and punch times are seconds after that round's bell. "
                "Fight-level offense and defense use those same windows, so breaks are not included."
            ),
        ),
        DecodeNote(
            field="corner_color",
            confidence="confirmed",
            note="Corner 1 is blue and corner 2 is red. Round points, hits taken, stuns, knockdowns, and knockouts belong to that corner.",
        ),
        DecodeNote(
            field="offense.thrown",
            confidence="inferred",
            note=(
                "Thrown is kinematic_thrown plus contact_thrown. "
                "kinematic_thrown counts punch records whose byte 9 is 0: swings the game detected, with a punch class. "
                "Every other record is a fixed 12-tick glove-contact stamp with no class, "
                "and the game writes one for blocks, glove clashes, and pushes as well as for strikes. "
                f"contact_thrown counts the contact records whose glove closed on the opponent's head or trunk at "
                f"{CONTACT_CLOSING_MIN:.1f} m/s or more (3-tick mean) in the {CONTACT_LOOKBACK_SEC:.2f} s before the contact, "
                f"and that do not fall inside a swing already counted on that hand, within {SAME_SWING_GRACE_SEC:.2f} s of its end, "
                f"or within {SAME_SWING_GRACE_SEC:.2f} s before a kinematic launch on that hand. "
                "A slower contact record also counts when a hit event stores its contact point, "
                "or when a hit that no counted punch explains falls "
                f"from {SCORED_CONTACT_BEFORE_SEC:.3f} s before to {SCORED_CONTACT_AFTER_SEC:.2f} s after its contact tick. "
                "discarded_records counts the contact records left out. "
                "A track with no kinematic records (an AI opponent) only has contact records, "
                "so a punch that touched nothing is not recorded and thrown undercounts its misses."
            ),
        ),
        DecodeNote(
            field="offense.accuracy",
            confidence="confirmed",
            note="Accuracy is landed divided by thrown. Landed is every hit the defender took: ordinary hits, stuns, and knockdown blows.",
        ),
        DecodeNote(
            field="offense.trajectory",
            confidence="confirmed",
            note=(
                "Byte 32 is the game punch class: 1 jab, 2 cross, 3 left_hook, 4 right_hook, 6 uppercut. "
                "Class 0 is the wrist's launch-to-peak displacement in the opponent frame "
                "(forward, up, right), labeled jab, cross, left_hook, right_hook, uppercut, overhand, or unknown."
            ),
        ),
        DecodeNote(
            field="offense.speed",
            confidence="inferred",
            note=(
                "Speed is the peak speed of the punching glove center in m/s, measured from skeleton.bin as a 3-tick mean. "
                "It runs from launch to end for a kinematic record and over the 0.15 s before the contact for a contact record. "
                "The glove center is the wrist extended along the forearm by half of m_scaledHandLength. "
                "The punch record has no speed field: the float at offset 80 does not follow wrist speed."
            ),
        ),
        DecodeNote(
            field="offense.combinations",
            confidence="inferred",
            note=(
                f"A new combination starts when launch ticks are more than {COMBO_GAP_SEC:.2f} s apart, "
                "or the punches fall in different rounds. "
                "single_shot_percent is the share of combinations with one punch. "
                "alternating_hand_percent is the share of multi-punch combinations whose hands strictly alternate. "
                "Depth is the punch's place in the combination: 1, 2, 3, 4, and 5+. "
                "Accuracy at a depth is landed divided by thrown. "
                "A punch is countered when a hit by the opponent falls in that punch's throwing or recovery window. "
                "A pattern is the trajectory sequence. uppercut, overhand, and unknown are prefixed with the hand. "
                "mean_damage is the mean, over instances, of the summed damage of the instance's landed punches. "
                "A miss counts as 0. "
                "mean_damage_landed is the mean damage of punches in the pattern that landed. "
                "Damage is the float at byte 13 of the hit event the punch is paired with. "
                "Per round those floats sum to the defender's m_receivedDamage."
            ),
        ),
        DecodeNote(
            field="defense.vulnerability",
            confidence="inferred",
            note=(
                "Windows are measured from each of this fighter's launch ticks. "
                f"while_throwing is within {THROW_WINDOW_SEC:.2f} s before or after a launch. "
                f"post_punch_recovery is more than {THROW_WINDOW_SEC:.2f} s and at most {RECOVERY_WINDOW_SEC:.2f} s after a launch, "
                "and not inside a throwing window. "
                "neutral_guard is every other bell-to-bell tick. "
                "Each hit taken goes to one window. A throwing window wins over recovery, and overlaps go to the closest launch. "
                "hit_share and time_share are percents of hits taken and of bell-to-bell time. "
                "risk_ratio is hit_share divided by time_share. "
                "Opponent accuracy uses the opponent's punch launches that fall in each state."
            ),
        ),
        DecodeNote(
            field="defense.guard_up_percent",
            confidence="inferred",
            note=(
                "A frame is guard-up when both glove centers sit at most "
                f"{GUARD_DY_MAX:.2f} m below head joint {HEAD} and within {GUARD_HORIZ_MAX:.2f} m horizontally. "
                "A glove center is the wrist extended along the forearm by half of m_scaledHandLength "
                "(0.095 m when the snapshot omits it). "
                "Under fire is the 0.05 s before through 0.30 s after each opponent punch record. "
                "Fight-level guard uses bell-to-bell ticks only."
            ),
        ),
        DecodeNote(
            field="defense.guard_discipline",
            confidence="inferred",
            note=(
                "left, right, both, and either guard use the same head-relative box as guard_up_percent. "
                f"both_guard_up_percent is that both-hands share. "
                f"At each punch's peak glove extension, the other glove is kept when its drop below the head "
                f"is under {OFFHAND_DY_MAX:.2f} m and its horizontal distance is under {OFFHAND_HORIZ_MAX:.2f} m. "
                "A glove above the head has drop 0. "
                "Off-hand and retraction rates use kinematic punch records only (byte 9 is 0). "
                f"Return-to-guard runs from that peak until the punching glove re-enters the same "
                f"{OFFHAND_DY_MAX:.2f} / {OFFHAND_HORIZ_MAX:.2f} m box, the next same-hand launch, or "
                f"{RETRACTION_WINDOW_SEC * 1000:.0f} ms. "
                "A glove already inside that box at the peak, or a next same-hand launch before re-entry, is excluded, not a miss. "
                "Droop is the largest drop of head-relative glove height below the straight chord from peak to re-entry. "
                "Directness is that chord length divided by the path length. "
                "Lead is the left hand for orthodox and the right hand for southpaw. "
                "Drop and flare medians use linear percentiles."
            ),
        ),
        DecodeNote(
            field="defense.footwork",
            confidence="inferred",
            note=(
                "Footwork uses hips joint 0 from each round's bell through the end bell. "
                "The warning and the time after the end bell are left out, and steps are not taken across the break. "
                "Forward is the horizontal unit from this fighter's hips to the opponent's hips. "
                "Right is (forward_z, 0, -forward_x), the fighter's right. "
                "Radial and tangential distances sum the absolute hips steps on those axes. "
                "total_distance_m is that sum, not the Euclidean path, and tangential_share is tangential divided by it. "
                "A positive tangential step is counterclockwise around the opponent when viewed from above. "
                f"Clinch is under {CLINCH_RANGE_M:.2f} m, pocket is {CLINCH_RANGE_M:.2f} m through {POCKET_RANGE_M:.2f} m, "
                f"and outside is beyond {POCKET_RANGE_M:.2f} m. "
                "Shoulder blade uses joints 6 and 10. Foot blade uses joints 15 and 19. "
                "Each reported angle is the median absolute angle of that horizontal line against the fighter's right, "
                "from 0 (square to the opponent) to 90 (the line points at the opponent). "
                f"Square stance is a signed shoulder angle under {SQUARE_BLADE_DEG:.0f} degrees. "
                f"Lead left is a signed shoulder angle of at least {SQUARE_BLADE_DEG:.0f} degrees, left shoulder closer to the opponent. "
                "Square while punching applies that shoulder test at the launch tick of each punch inside the bell span. "
                f"An angle cut merges overlapping {ANGLE_CUT_SEC:.2f} s windows in which this fighter's own hips "
                f"sweep at least {ANGLE_CUT_DEG:.0f} degrees around the opponent while hips distance stays under {ANGLE_CUT_RANGE_M:.1f} m. "
                "Opponent motion is not added. "
                f"Entry and exit use the same sweep. Punches whose launch ticks fall more than {COMBO_GAP_SEC:.2f} s apart "
                f"start a new group. Entry runs from the first launch to the last punch's end tick. "
                f"Exit is the next {COMBO_EXIT_SEC:.1f} s, stopping at the end bell."
            ),
        ),
        DecodeNote(
            field="defense.footwork.foot_blade_angle_deg",
            confidence="inferred",
            note="Ankle joints are IK-estimated on Quest, so the foot blade angle is not an optical measurement.",
        ),
        DecodeNote(
            field="defense.head",
            confidence="confirmed",
            note=(
                f"The head is skeleton joint {HEAD}. Position samples are uint16 values scaled across [-10, 10] m. "
                "head_lateral_range is the horizontal extent, hypot(max(x) - min(x), max(z) - min(z)). "
                f"Instantaneous speed above {HEAD_SPEED_CAP:.0f} m/s is clipped as a tracking spike."
            ),
        ),
        DecodeNote(
            field="defense.head_movement",
            confidence="inferred",
            note=(
                f"Head movement uses head joint {HEAD} and hips joint {HIPS} from each round's bell through the end bell. "
                "The warning and the time after the end bell are left out, and a window never crosses a gap in skeleton ticks. "
                "Lateral slip is the absolute projection of (head - hips) onto the fighter's right, the same tangential axis as footwork. "
                f"Off centerline is a slip of at least {OFF_CENTERLINE_M:.2f} m. "
                "Under fire is the 0.05 s before through 0.30 s after each opponent punch record, inside the bell span. "
                "While punching is a bell-span frame whose tick lies inside this fighter's own launch-to-end punch interval. "
                "head_height_iqr_m is the interquartile range of head height. "
                "p05_p95_span_m is the 95th percentile of head height minus the 5th. "
                "pelvis_drop_iqr_m is the interquartile range of hips height below its 90th percentile. "
                "trunk_bend_iqr_m is the interquartile range of head height minus hips height. "
                f"A duck is a merged run of {DUCK_WINDOW_SEC:.1f} s windows in which head height falls and rises "
                f"at least {DUCK_DROP_M:.2f} m around an interior trough. "
                f"A bob-and-weave is a merged run of {WEAVE_WINDOW_SEC:.1f} s windows with that U-shape at "
                f"{WEAVE_DROP_M:.2f} m and a lateral-slip range of at least {WEAVE_SLIP_M:.2f} m. "
                "The two counts are independent. Quest hips are the recorded root joint, not an optical foot measurement."
            ),
        ),
        DecodeNote(
            field="defense.punishment",
            confidence="inferred",
            note="punishment_0/1/2 are the three float meters in punishment.bin. They are not the official received-damage total.",
        ),
        DecodeNote(
            field="offense.punches",
            confidence="inferred",
            note=(
                "launch_sec is the punch record's launch_tick (offset 12) and t_sec is its end tick (offset 0). "
                "impact_sec is the tick of the hit event paired with the punch, and damage is that event's damage. "
                "A hit event and its punch record store the same contact point, which pairs them exactly. "
                "A hit with no such record goes to the closest free punch whose launch-to-end window holds it. "
                "combo_id (1-based within the offense block), combo_depth (1..4, 5+), and countered "
                "use the same launch-gap groups and counter windows as offense.combinations. "
                "head_slip_m is the signed projection of (head - hips) onto the fighter's right at launch_tick."
            ),
        ),
        DecodeNote(
            field="series.guard_brace",
            confidence="unavailable",
            note=(
                "guard_brace, guard_friction, guard_mass, and guard_ladder are not decoded. "
                "The series read the 48-byte guard payload as four channels of six uint16 samples and keep the first of each, "
                "scaled by the header min and max. The payload does not have that layout: "
                "it repeats on a 17-byte period, and most brace and mass samples have an empty low byte. "
                "Treat these four series as raw bytes, not as guard levels."
            ),
        ),
        DecodeNote(
            field="series.biomechanics",
            confidence="inferred",
            note=(
                "left_guard_up and right_guard_up are 1.0 s bucket shares in [0, 1] using the same head-relative box as guard_up. "
                "hips_x and hips_z are 0.25 s bucket means of world horizontal hip coordinates in meters. "
                "head_slip_lateral, fighter_distance, blade_angle, and tangential_speed are 0.25 s bucket means on the opponent frame. "
                "head_slip_lateral is signed (head - hips) on the fighter's right. "
                "fighter_distance is horizontal hip-to-hip distance. "
                "blade_angle is the signed shoulder line angle (0 square, positive lead-left). "
                "tangential_speed is signed hips speed along the fighter's right on consecutive ticks (positive counterclockwise)."
            ),
        ),
        DecodeNote(
            field="timeline.angle_cut",
            confidence="inferred",
            note=(
                f"An angle cut is a merged run of {ANGLE_CUT_SEC:.2f} s windows in which this fighter's hips "
                f"sweep at least {ANGLE_CUT_DEG:.0f} degrees around the opponent while the hips stay under {ANGLE_CUT_RANGE_M:.1f} m apart. "
                "The timestamp is the start of the window with the largest sweep. "
                "delta_deg is the signed sweep of the whole run, positive counterclockwise."
            ),
        ),
        DecodeNote(
            field="timeline.duck",
            confidence="inferred",
            note=(
                f"A duck is a merged run of {DUCK_WINDOW_SEC:.1f} s windows on consecutive bell-span frames "
                f"in which head height falls and rises at least {DUCK_DROP_M:.2f} m around an interior trough. "
                "The timestamp is the trough of the window with the largest fall. drop_m is that fall."
            ),
        ),
        DecodeNote(
            field="timeline.bob_and_weave",
            confidence="inferred",
            note=(
                f"A bob-and-weave is a merged run of {WEAVE_WINDOW_SEC:.1f} s windows on consecutive bell-span frames "
                f"in which head height falls and rises at least {WEAVE_DROP_M:.2f} m and lateral slip ranges "
                f"at least {WEAVE_SLIP_M:.2f} m. "
                "The timestamp is the trough of the window with the largest fall. slip_delta_m is that window's slip range."
            ),
        ),
        DecodeNote(
            field="timeline.exchange",
            confidence="inferred",
            note=f"An exchange is a run of 1-second bins in which each fighter has at least {EXCHANGE_MIN_EACH} punch records.",
        ),
        DecodeNote(
            field="timeline.punishment_spike",
            confidence="inferred",
            note="A punishment spike is a step of at least 8 on punishment channels 0+1, with repeats inside 0.4 s collapsed.",
        ),
        DecodeNote(
            field="timeline.head_drop",
            confidence="inferred",
            note=f"A head drop is a loss of at least {HEAD_DROP_METERS:.2f} m of head height inside {HEAD_DROP_TICKS / 120:.2f} s.",
        ),
    ]
