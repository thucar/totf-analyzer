export type CornerRound = {
  score: number;
  hits: number;
  received_damage: number;
  stuns: number;
  punishment_stuns: number;
  knockdowns: number;
  punishment_knockdowns: number;
  all_knockdowns: number;
  knocked_out: boolean;
  technically_knocked_out: boolean;
  fouls: number;
};

export type VulnerabilityWindow = {
  hits: number;
  hit_share: number | null;
  time_share: number | null;
  risk_ratio: number | null;
  opponent_thrown: number;
  opponent_landed: number;
  opponent_accuracy: number | null;
};

export type FightAnalytics = {
  session: {
    name: string;
    source: string;
    venue: string | null;
    duration_sec: number;
    method: string;
    winner_corner: number | null;
    winner_color: string | null;
    red_total_score: number | null;
    blue_total_score: number | null;
    rounds_scheduled: number;
    round_duration_sec: number;
    break_duration_sec?: number;
    ring_size_x_m?: number | null;
    ring_size_z_m?: number | null;
    fixed_timestep?: number;
    start_tick?: number;
    end_tick?: number;
    created_utc?: string | null;
  };
  fighters: {
    corner: number;
    color: string;
    name: string;
    is_local_player: boolean;
    stance: string | null;
    height_m: number | null;
    ai_archetype: string | null;
    ai_difficulty: string | null;
  }[];
  rounds: {
    index: number;
    completed: boolean;
    red: CornerRound;
    blue: CornerRound;
    bell_sec: number | null;
    end_sec: number | null;
    duration_sec: number | null;
    offense: FightAnalytics["offense"];
    defense: FightAnalytics["defense"];
    key_moments: FightAnalytics["key_moments"];
    series: FightAnalytics["series"];
  }[];
  offense: {
    corner: number;
    thrown: number;
    kinematic_thrown: number;
    contact_thrown: number;
    discarded_records: number;
    landed: number;
    official_hits: number;
    accuracy: number | null;
    punches_per_minute: number;
    hands: { hand: string; thrown: number; landed: number; accuracy: number | null; mean_speed: number | null }[];
    trajectories: {
      trajectory: string;
      thrown: number;
      landed: number;
      accuracy: number | null;
      mean_speed: number | null;
    }[];
    velocity: {
      samples: number;
      mean_thrown: number | null;
      mean_landed: number | null;
      max_speed: number | null;
      mean_punishment_delta_landed: number | null;
      speed_punishment_correlation: number | null;
      histogram: { lo: number; hi: number; count: number }[];
    };
    combinations: {
      combo_count: number;
      mean_combo_length: number | null;
      max_combo_length: number;
      single_shot_percent: number | null;
      alternating_hand_percent: number | null;
      by_depth: {
        depth: string;
        thrown: number;
        landed: number;
        accuracy: number | null;
        mean_speed: number | null;
        countered_count: number;
        countered_rate: number | null;
      }[];
      patterns: {
        pattern: string;
        count: number;
        length: number;
        thrown: number;
        landed: number;
        accuracy: number | null;
        mean_speed: number | null;
        mean_punishment_delta: number | null;
        mean_punishment_delta_landed: number | null;
      }[];
    };
    punches: {
      t_sec: number;
      launch_sec?: number | null;
      impact_sec?: number | null;
      hand: string;
      trajectory: string;
      speed: number | null;
      landed: boolean;
      punishment_delta: number | null;
      combo_id?: number | null;
      combo_depth?: string | null;
      countered?: boolean;
      head_slip_m?: number | null;
      offhand_in_guard: boolean | null;
      offhand_drop_m: number | null;
      offhand_flare_m: number | null;
      retraction_ms: number | null;
      retraction_droop_m: number | null;
      retraction_directness: number | null;
    }[];
  }[];
  defense: {
    corner: number;
    guard_up_percent: number | null;
    guard_up_percent_under_fire: number | null;
    under_fire_seconds: number;
    head_mean_speed: number | null;
    head_mean_speed_under_fire: number | null;
    head_mean_speed_not_under_fire: number | null;
    head_vertical_range: number | null;
    head_lateral_range: number | null;
    punishment_peak: number[];
    received_damage_official: number;
    guard_discipline: {
      left_guard_up_percent: number | null;
      right_guard_up_percent: number | null;
      both_guard_up_percent: number | null;
      either_guard_up_percent: number | null;
      left_guard_up_percent_under_fire: number | null;
      right_guard_up_percent_under_fire: number | null;
      both_guard_up_percent_under_fire: number | null;
      either_guard_up_percent_under_fire: number | null;
      offhand_guard_kept_percent: number | null;
      offhand_guard_kept_percent_throwing_left: number | null;
      offhand_guard_kept_percent_throwing_right: number | null;
      offhand_drop_below_head_m_lead: { median: number | null; p90: number | null };
      offhand_drop_below_head_m_rear: { median: number | null; p90: number | null };
      offhand_lateral_flare_m_lead: { median: number | null; p90: number | null };
      offhand_lateral_flare_m_rear: { median: number | null; p90: number | null };
      retraction_returned_percent: number | null;
      retraction_time_ms: { median: number | null; mean: number | null; p90: number | null };
      retraction_droop_m: { median: number | null; p90: number | null; sag_over_10cm_percent: number | null };
      retraction_directness_ratio: { median: number | null; mean: number | null };
    };
    footwork: {
      total_distance_m: number | null;
      radial_distance_m: number | null;
      tangential_distance_m: number | null;
      tangential_share: number | null;
      clockwise_distance_m: number | null;
      counterclockwise_distance_m: number | null;
      angle_cut_count: number;
      attack_entry_angle_deg: number | null;
      post_combo_exit_angle_deg: number | null;
      fighter_distance_m: { mean: number | null; p10: number | null; median: number | null; p90: number | null };
      clinch_range_percent: number | null;
      pocket_range_percent: number | null;
      outside_range_percent: number | null;
      shoulder_blade_angle_deg: number | null;
      foot_blade_angle_deg: number | null;
      square_stance_percent: number | null;
      lead_left_percent: number | null;
      square_while_punching_percent: number | null;
    };
    head_movement: {
      head_lateral_slip_m: { median: number | null; p90: number | null; under_fire_p90: number | null };
      off_centerline_percent: number | null;
      off_centerline_under_fire_percent: number | null;
      off_centerline_while_punching_percent: number | null;
      head_height_iqr_m: number | null;
      p05_p95_span_m: number | null;
      pelvis_drop_iqr_m: number | null;
      trunk_bend_iqr_m: number | null;
      duck_count: number;
      bob_and_weave_count: number;
    };
    vulnerability: {
      while_throwing: VulnerabilityWindow;
      post_punch_recovery: VulnerabilityWindow;
      neutral_guard: VulnerabilityWindow;
    };
  }[];
  key_moments: {
    t_sec: number;
    tick: number;
    type: string;
    corners: number[];
    detail: Record<string, string | number | null>;
  }[];
  series: { name: string; corner: number | null; t: number[]; y: number[] }[];
  decode_status: { field: string; confidence: string; note: string }[];
};

export type SessionRow = {
  name: string;
  size: number;
  modified: number;
  bout: string | null;
  created: string | null;
  red: string | null;
  blue: string | null;
  winner: "red" | "blue" | null;
  method: "KO" | "TKO" | "UD" | "draw" | null;
  local: "red" | "blue" | null;
  result: string | null;
};

export type GameRecording = SessionRow & { imported: boolean };

export type GameListing = {
  directory: string;
  available: boolean;
  recordings: GameRecording[];
};
