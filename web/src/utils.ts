import type { FightAnalytics, SessionRow } from "./types";

export const RED_HEX = "#ff5451";
export const RED_SOFT_HEX = "#ffb3ad";
export const BLUE_HEX = "#4cd7f6";
export const BLUE_CONTAINER_HEX = "#03b5d3";
export const AMBER_HEX = "#ffb95f";
export const GRID_HEX = "#31353d";
export const MUTED_HEX = "#ab8986";

export type ViewId =
  | "fight-summary"
  | "spatial-heatmaps"
  | "strike-telemetry"
  | "kinetics-force"
  | "force-degradation"
  | "punch-log";

export type ScopeSelection = "all" | number;

export type CornerColor = "red" | "blue";

export function cornerColor(corner: number): CornerColor {
  return corner === 2 ? "red" : "blue";
}

export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const sign = seconds < 0 ? "−" : "";
  const safe = Math.abs(seconds);
  const mins = Math.floor(safe / 60);
  const secs = safe - mins * 60;
  return `${sign}${mins}:${secs.toFixed(1).padStart(4, "0")}`;
}

export function clockWhole(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const safe = Math.max(0, Math.round(seconds));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

export function pct(ratio: number | null | undefined, digits = 1): string {
  return ratio == null || !Number.isFinite(ratio) ? "—" : `${(ratio * 100).toFixed(digits)}%`;
}

export function pctPts(percent: number | null | undefined, digits = 1): string {
  return percent == null || !Number.isFinite(percent) ? "—" : `${percent.toFixed(digits)}%`;
}

export function num(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

export function splitShare(redVal: number | null | undefined, blueVal: number | null | undefined): [number, number] {
  const r = Math.max(0, redVal ?? 0);
  const b = Math.max(0, blueVal ?? 0);
  const total = r + b;
  if (total <= 0) return [50, 50];
  const rPct = Math.min(98, Math.max(2, (r / total) * 100));
  return [rPct, 100 - rPct];
}

export function clampPct(val: number | null | undefined): number {
  if (val == null || !Number.isFinite(val)) return 0;
  return Math.min(100, Math.max(0, val));
}

export function getFighter(report: FightAnalytics, color: CornerColor) {
  return report.fighters.find((f) => f.color === color);
}

export function getFocalColor(report: FightAnalytics): CornerColor {
  const local = report.fighters.find((f) => f.is_local_player);
  if (local?.color === "blue" || local?.color === "red") return local.color;
  return "red";
}

export function getFighterRoles(report: FightAnalytics, focalOverride?: CornerColor) {
  const local = report.fighters.find((f) => f.is_local_player);
  const localColor: CornerColor | null =
    local?.color === "red" || local?.color === "blue" ? local.color : null;
  const primaryColor: CornerColor = focalOverride ?? localColor ?? "red";
  const opponentColor: CornerColor = primaryColor === "red" ? "blue" : "red";
  const primary = getFighter(report, primaryColor);
  const opponent = getFighter(report, opponentColor);
  const primaryName = primary?.name ?? (primaryColor === "red" ? "Red" : "Blue");
  const opponentName = opponent?.name ?? (opponentColor === "red" ? "Red" : "Blue");
  return {
    primary,
    opponent,
    primaryColor,
    opponentColor,
    primaryName,
    opponentName,
    localColor,
    isLocalIdentified: localColor !== null,
    isPrimaryLocal: localColor === primaryColor,
  };
}

export function getScopeData(report: FightAnalytics, scope: ScopeSelection) {
  const completedRounds = report.rounds.filter((r) => r.completed);
  const round = typeof scope === "number" ? completedRounds.find((r) => r.index === scope) : undefined;
  const offense = round ? round.offense : report.offense;
  const defense = round ? round.defense : report.defense;
  const context = round ? (round.context ?? []) : (report.context ?? []);
  const keyMoments = round ? round.key_moments : report.key_moments;
  const series = round ? round.series : report.series;

  const redOff = offense.find((o) => cornerColor(o.corner) === "red");
  const blueOff = offense.find((o) => cornerColor(o.corner) === "blue");
  const redDef = defense.find((d) => cornerColor(d.corner) === "red");
  const blueDef = defense.find((d) => cornerColor(d.corner) === "blue");
  const redCtx = context.find((c) => cornerColor(c.corner) === "red");
  const blueCtx = context.find((c) => cornerColor(c.corner) === "blue");

  const redStuns = round ? round.red.stuns : completedRounds.reduce((acc, r) => acc + r.red.stuns, 0);
  const blueStuns = round ? round.blue.stuns : completedRounds.reduce((acc, r) => acc + r.blue.stuns, 0);
  const redKds = round ? round.red.all_knockdowns : completedRounds.reduce((acc, r) => acc + r.red.all_knockdowns, 0);
  const blueKds = round ? round.blue.all_knockdowns : completedRounds.reduce((acc, r) => acc + r.blue.all_knockdowns, 0);
  const redDamage = round
    ? round.red.received_damage
    : (redDef?.received_damage_official ?? completedRounds.reduce((acc, r) => acc + r.red.received_damage, 0));
  const blueDamage = round
    ? round.blue.received_damage
    : (blueDef?.received_damage_official ?? completedRounds.reduce((acc, r) => acc + r.blue.received_damage, 0));

  const durationSec = round
    ? (round.duration_sec ?? report.session.round_duration_sec)
    : completedRounds.reduce((acc, r) => acc + (r.duration_sec ?? 0), 0) || report.session.duration_sec;

  return {
    round,
    completedRounds,
    offense,
    defense,
    context,
    keyMoments,
    series,
    redOff,
    blueOff,
    redDef,
    blueDef,
    redCtx,
    blueCtx,
    redStuns,
    blueStuns,
    redKds,
    blueKds,
    redDamage,
    blueDamage,
    durationSec,
  };
}

export function seriesPoints(seriesList: FightAnalytics["series"], name: string, scale = 1) {
  const points = new Map<number, { t: number; red: number | null; blue: number | null }>();
  for (const series of seriesList.filter((item) => item.name === name)) {
    const key = cornerColor(series.corner ?? 0);
    series.t.forEach((t, index) => {
      const row = points.get(t) ?? { t, red: null, blue: null };
      const raw = series.y[index];
      row[key] = raw == null ? null : raw * scale;
      points.set(t, row);
    });
  }
  return [...points.values()].sort((a, b) => a.t - b.t);
}

export function combinedPunishmentSeries(seriesList: FightAnalytics["series"]) {
  const points = new Map<number, { t: number; red: number; blue: number }>();
  for (const ch of ["punishment_0", "punishment_1"]) {
    for (const s of seriesList.filter((item) => item.name === ch)) {
      const key = cornerColor(s.corner ?? 0);
      s.t.forEach((t, idx) => {
        const row = points.get(t) ?? { t, red: 0, blue: 0 };
        row[key] = Number((row[key] + (s.y[idx] ?? 0)).toFixed(3));
        points.set(t, row);
      });
    }
  }
  return [...points.values()].sort((a, b) => a.t - b.t);
}

export function seriesMean(seriesList: FightAnalytics["series"], name: string, corner: number): number | null {
  const found = seriesList.find((s) => s.name === name && s.corner === corner);
  if (!found || found.y.length === 0) return null;
  const total = found.y.reduce((acc, v) => acc + v, 0);
  return total / found.y.length;
}

export function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

export function formatTrajectoryLabel(traj: string): string {
  const map: Record<string, string> = {
    jab: "Jab (Lead)",
    cross: "Cross (Straight)",
    left_hook: "Left Hook",
    right_hook: "Right Hook",
    uppercut: "Uppercut",
    left_uppercut: "Left Uppercut",
    right_uppercut: "Right Uppercut",
    overhand: "Overhand",
    left_overhand: "Left Overhand",
    right_overhand: "Right Overhand",
    unknown: "Unclassified",
  };
  return map[traj] ?? traj.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatTokenLabel(token: string): string {
  const map: Record<string, string> = {
    jab: "Jab",
    cross: "Cross",
    left_hook: "Left Hook",
    right_hook: "Right Hook",
    uppercut: "Uppercut",
    left_uppercut: "L-Uppercut",
    right_uppercut: "R-Uppercut",
    overhand: "Overhand",
    left_overhand: "L-Overhand",
    right_overhand: "R-Overhand",
    left_unknown: "L-Unk",
    right_unknown: "R-Unk",
    unknown: "Unk",
  };
  return map[token] ?? token.replaceAll("_", " ");
}

export function verdictBadge(report: FightAnalytics): string {
  const local = report.fighters.find((f) => f.is_local_player);
  const methodMap: Record<string, string> = {
    knockout: "KO",
    technical_knockout: "TKO",
    decision: "UD",
  };
  const m = methodMap[report.session.method] ?? report.session.method.toUpperCase();
  const hasScores =
    report.session.red_total_score != null && report.session.blue_total_score != null;
  const scoreFor = (leadColor: CornerColor) => {
    if (!hasScores) return "";
    const lead =
      leadColor === "blue" ? report.session.blue_total_score : report.session.red_total_score;
    const other =
      leadColor === "blue" ? report.session.red_total_score : report.session.blue_total_score;
    return ` ${lead}–${other}`;
  };
  if (!report.session.winner_color) {
    const leadColor: CornerColor = local?.color === "blue" ? "blue" : "red";
    return `DRAW${scoreFor(leadColor)}`;
  }
  if (local && (local.color === "red" || local.color === "blue")) {
    const won = report.session.winner_color === local.color;
    return `${won ? "W" : "L"}-${m}${scoreFor(local.color)}`;
  }
  const winColor: CornerColor = report.session.winner_color === "blue" ? "blue" : "red";
  return `${winColor.toUpperCase()} ${m}${scoreFor(winColor)}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatWhen(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}, ${hours}:${minutes}`;
}

export function filenameWhen(name: string): string | null {
  const match = name.match(/_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}(?:\.zip)?$/i);
  if (!match) return null;
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return `${day} ${MONTHS[month - 1]} ${match[1]}, ${match[4]}:${match[5]}`;
}

export function isTrainingSession(row: Pick<SessionRow, "is_training" | "session_kind">): boolean {
  return Boolean(row.is_training || row.session_kind === "training");
}

export function formatBytesMb(sizeBytes: number): string {
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function sessionSelectOptionLabel(row: SessionRow): string {
  const subject = row.local ?? row.winner ?? (row.red ? "red" : row.blue ? "blue" : null);
  const lead = subject === "blue" ? row.blue : subject === "red" ? row.red : null;
  const other = subject === "blue" ? row.red : subject === "red" ? row.blue : null;
  const parts: string[] = [];
  if (isTrainingSession(row)) parts.push("[Training]");
  if (lead && other) {
    parts.push(`${lead} vs ${other}`);
  } else if (lead || other) {
    parts.push(lead ?? other ?? row.name);
  } else {
    parts.push(row.name.replace(/^session_/, "").replace(/\.zip$/, ""));
  }
  if (row.result) parts.push(row.result);
  if (row.bout) parts.push(row.bout);
  const when = formatWhen(row.created) || filenameWhen(row.name);
  if (when) parts.push(when);
  return parts.join(" · ");
}

export function roundTimestampLabel(report: FightAnalytics, tSec: number, scope: ScopeSelection): string {
  if (typeof scope === "number") {
    return `R${scope + 1} ${clock(tSec)}`;
  }
  for (const r of report.rounds) {
    if (!r.completed || r.bell_sec == null) continue;
    const end = r.end_sec ?? r.bell_sec + (r.duration_sec ?? report.session.round_duration_sec);
    if (tSec >= r.bell_sec - 8 && tSec <= end + 4) {
      return `R${r.index + 1} ${clock(tSec - r.bell_sec)}`;
    }
  }
  return clock(tSec);
}

export function formatMomentDetail(detail: Record<string, string | number | null>): string {
  return Object.entries(detail)
    .filter(([key, value]) => value != null && value !== "" && key !== "label_confidence" && key !== "event_type")
    .map(([key, value]) => {
      if (typeof value === "number") {
        if (key === "speed") return `${value.toFixed(2)} m/s`;
        if (key === "punishment_step") return `+${value.toFixed(2)} pts`;
        if (key === "delta_deg") return `${value > 0 ? "+" : ""}${value.toFixed(1)}°`;
        if (key === "drop_m" || key === "slip_delta_m") return `${value.toFixed(2)} m`;
        if (key.endsWith("_sec")) return `${value.toFixed(2)} s`;
      }
      return `${key.replaceAll("_", " ")}: ${value}`;
    })
    .join(" · ");
}
