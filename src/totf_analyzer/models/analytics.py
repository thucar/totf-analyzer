"""JSON schema for a fight's factual analytics. No coaching narrative."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["confirmed", "inferred", "unavailable"]


class DecodeNote(BaseModel):
    field: str
    confidence: Confidence
    note: str


class Fighter(BaseModel):
    corner: int
    color: str
    name: str
    track_folder: str
    is_local_player: bool
    stance: str | None = None
    height_m: float | None = None
    ai_archetype: str | None = None
    ai_difficulty: str | None = None


class CornerRound(BaseModel):
    score: int
    hits: int
    received_damage: float
    stuns: int
    punishment_stuns: int
    knockdowns: int
    punishment_knockdowns: int
    all_knockdowns: int
    knocked_out: bool
    technically_knocked_out: bool
    fouls: int


class RoundScore(BaseModel):
    index: int
    completed: bool
    red: CornerRound
    blue: CornerRound
    # Fight-clock seconds of the bell and the end of the round. Series, moments,
    # and punch times inside the round are seconds after the bell.
    bell_sec: float | None = None
    end_sec: float | None = None
    duration_sec: float | None = None
    offense: list[OffenseStats] = Field(default_factory=list)
    defense: list[DefenseStats] = Field(default_factory=list)
    key_moments: list[KeyMoment] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)


class SessionFacts(BaseModel):
    name: str
    source: str
    fight_id: str | None = None
    created_utc: str | None = None
    app_version: str | None = None
    venue: str | None = None
    rounds_scheduled: int
    round_duration_sec: float
    break_duration_sec: float
    ring_size_x_m: float | None = None
    ring_size_z_m: float | None = None
    duration_sec: float
    fixed_timestep: float
    start_tick: int
    end_tick: int
    method: str
    winner_corner: int | None = None
    winner_color: str | None = None
    red_total_score: int | None = None
    blue_total_score: int | None = None


class HandStats(BaseModel):
    hand: str
    hand_index: int | None = None
    thrown: int
    landed: int
    accuracy: float | None = None
    mean_speed: float | None = None


class TrajectoryStats(BaseModel):
    trajectory: str
    thrown: int
    landed: int
    accuracy: float | None = None
    mean_speed: float | None = None


class HistogramBin(BaseModel):
    lo: float
    hi: float
    count: int


class VelocityStats(BaseModel):
    samples: int
    mean_thrown: float | None = None
    mean_landed: float | None = None
    max_speed: float | None = None
    mean_damage_landed: float | None = None
    speed_damage_correlation: float | None = None
    histogram: list[HistogramBin] = Field(default_factory=list)


class PunchRow(BaseModel):
    t_sec: float
    launch_sec: float | None = None
    impact_sec: float | None = None
    tick: int
    hand: str
    hand_index: int
    trajectory: str
    speed: float | None = None
    landed: bool
    damage: float | None = None
    combo_id: int | None = None
    combo_depth: str | None = None
    countered: bool = False
    head_slip_m: float | None = None
    # Off-hand fields are null without a peak-extension frame. Retraction fields
    # are also null for a same-hand double-up or a miss inside 800 ms.
    offhand_in_guard: bool | None = None
    offhand_drop_m: float | None = None
    offhand_flare_m: float | None = None
    retraction_ms: float | None = None
    retraction_droop_m: float | None = None
    retraction_directness: float | None = None


class MedianP90(BaseModel):
    median: float | None = None
    p90: float | None = None


class RetractionTime(BaseModel):
    median: float | None = None
    mean: float | None = None
    p90: float | None = None


class RetractionDroop(BaseModel):
    median: float | None = None
    p90: float | None = None
    sag_over_10cm_percent: float | None = None


class DirectnessRatio(BaseModel):
    median: float | None = None
    mean: float | None = None


class DistanceSpread(BaseModel):
    mean: float | None = None
    p10: float | None = None
    median: float | None = None
    p90: float | None = None


class SlipSpread(BaseModel):
    median: float | None = None
    p90: float | None = None
    under_fire_p90: float | None = None


class HeadMovementStats(BaseModel):
    head_lateral_slip_m: SlipSpread = Field(default_factory=SlipSpread)
    off_centerline_percent: float | None = None
    off_centerline_under_fire_percent: float | None = None
    off_centerline_while_punching_percent: float | None = None
    head_height_iqr_m: float | None = None
    p05_p95_span_m: float | None = None
    pelvis_drop_iqr_m: float | None = None
    trunk_bend_iqr_m: float | None = None
    duck_count: int = 0
    bob_and_weave_count: int = 0


class FootworkStats(BaseModel):
    total_distance_m: float | None = None
    radial_distance_m: float | None = None
    tangential_distance_m: float | None = None
    tangential_share: float | None = None
    clockwise_distance_m: float | None = None
    counterclockwise_distance_m: float | None = None
    angle_cut_count: int = 0
    attack_entry_angle_deg: float | None = None
    post_combo_exit_angle_deg: float | None = None
    fighter_distance_m: DistanceSpread = Field(default_factory=DistanceSpread)
    clinch_range_percent: float | None = None
    pocket_range_percent: float | None = None
    outside_range_percent: float | None = None
    shoulder_blade_angle_deg: float | None = None
    foot_blade_angle_deg: float | None = None
    square_stance_percent: float | None = None
    lead_left_percent: float | None = None
    square_while_punching_percent: float | None = None


class DepthStats(BaseModel):
    depth: str
    thrown: int
    landed: int
    accuracy: float | None = None
    mean_speed: float | None = None
    countered_count: int = 0
    countered_rate: float | None = None


class ComboPatternStats(BaseModel):
    pattern: str
    count: int
    length: int
    thrown: int
    landed: int
    accuracy: float | None = None
    mean_speed: float | None = None
    mean_damage: float | None = None
    mean_damage_landed: float | None = None


class CombinationStats(BaseModel):
    combo_count: int = 0
    mean_combo_length: float | None = None
    max_combo_length: int = 0
    single_shot_percent: float | None = None
    alternating_hand_percent: float | None = None
    by_depth: list[DepthStats] = Field(default_factory=list)
    patterns: list[ComboPatternStats] = Field(default_factory=list)


class VulnerabilityWindow(BaseModel):
    hits: int = 0
    hit_share: float | None = None
    time_share: float | None = None
    risk_ratio: float | None = None
    opponent_thrown: int = 0
    opponent_landed: int = 0
    opponent_accuracy: float | None = None


class VulnerabilityStats(BaseModel):
    while_throwing: VulnerabilityWindow = Field(default_factory=VulnerabilityWindow)
    post_punch_recovery: VulnerabilityWindow = Field(default_factory=VulnerabilityWindow)
    neutral_guard: VulnerabilityWindow = Field(default_factory=VulnerabilityWindow)


class GuardDisciplineStats(BaseModel):
    left_guard_up_percent: float | None = None
    right_guard_up_percent: float | None = None
    both_guard_up_percent: float | None = None
    either_guard_up_percent: float | None = None
    left_guard_up_percent_under_fire: float | None = None
    right_guard_up_percent_under_fire: float | None = None
    both_guard_up_percent_under_fire: float | None = None
    either_guard_up_percent_under_fire: float | None = None
    offhand_guard_kept_percent: float | None = None
    offhand_guard_kept_percent_throwing_left: float | None = None
    offhand_guard_kept_percent_throwing_right: float | None = None
    offhand_drop_below_head_m_lead: MedianP90 = Field(default_factory=MedianP90)
    offhand_drop_below_head_m_rear: MedianP90 = Field(default_factory=MedianP90)
    offhand_lateral_flare_m_lead: MedianP90 = Field(default_factory=MedianP90)
    offhand_lateral_flare_m_rear: MedianP90 = Field(default_factory=MedianP90)
    retraction_returned_percent: float | None = None
    retraction_time_ms: RetractionTime = Field(default_factory=RetractionTime)
    retraction_droop_m: RetractionDroop = Field(default_factory=RetractionDroop)
    retraction_directness_ratio: DirectnessRatio = Field(default_factory=DirectnessRatio)


class OffenseStats(BaseModel):
    corner: int
    thrown: int
    kinematic_thrown: int
    contact_thrown: int = 0
    discarded_records: int = 0
    landed: int
    official_hits: int
    accuracy: float | None = None
    punches_per_minute: float
    hands: list[HandStats]
    trajectories: list[TrajectoryStats]
    velocity: VelocityStats
    punches: list[PunchRow]
    combinations: CombinationStats = Field(default_factory=CombinationStats)


class DefenseStats(BaseModel):
    corner: int
    guard_up_percent: float | None = None
    guard_up_percent_under_fire: float | None = None
    under_fire_seconds: float
    head_mean_speed: float | None = None
    head_mean_speed_under_fire: float | None = None
    head_mean_speed_not_under_fire: float | None = None
    head_vertical_range: float | None = None
    head_lateral_range: float | None = None
    head_joint_index: int | None = None
    punishment_peak: list[float] = Field(default_factory=list)
    received_damage_official: float
    guard_discipline: GuardDisciplineStats = Field(default_factory=GuardDisciplineStats)
    footwork: FootworkStats = Field(default_factory=FootworkStats)
    head_movement: HeadMovementStats = Field(default_factory=HeadMovementStats)
    vulnerability: VulnerabilityStats = Field(default_factory=VulnerabilityStats)


class KeyMoment(BaseModel):
    t_sec: float
    tick: int
    type: str
    corners: list[int]
    detail: dict


class Series(BaseModel):
    name: str
    corner: int | None = None
    t: list[float]
    y: list[float]


class FightAnalytics(BaseModel):
    session: SessionFacts
    fighters: list[Fighter]
    rounds: list[RoundScore]
    offense: list[OffenseStats]
    defense: list[DefenseStats]
    key_moments: list[KeyMoment]
    series: list[Series]
    decode_status: list[DecodeNote]


RoundScore.model_rebuild()
