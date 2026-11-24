import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { FightAnalytics } from "../types";
import {
  BLUE_CONTAINER_HEX,
  BLUE_HEX,
  GRID_HEX,
  MUTED_HEX,
  RED_HEX,
  RED_SOFT_HEX,
  type CornerColor,
  clampPct,
  clockWhole,
  cornerColor,
  formatTrajectoryLabel,
  getFighter,
  getFighterRoles,
  getFocalColor,
  num,
  pct,
  pctPts,
} from "../utils";

const DEPTHS = ["1", "2", "3", "4", "5+"] as const;

type CurveRow = {
  t: number;
  redBase: number | null;
  redLate: number | null;
  blueBase: number | null;
  blueLate: number | null;
};

function rollingPunchMetric(
  round: FightAnalytics["rounds"][number] | undefined,
  cornerColorName: "red" | "blue",
  mode: "speed" | "density",
  maxDuration: number,
): number[] {
  const step = 5;
  const binCount = Math.max(1, Math.ceil(maxDuration / step));
  if (!round) return Array(binCount).fill(0);

  if (mode === "density") {
    const dens = round.series.find(
      (s) => s.name === "punch_density" && cornerColor(s.corner ?? 0) === cornerColorName,
    );
    return Array.from({ length: binCount }, (_, b) => {
      const lo = b * step;
      const hi = lo + step;
      let sum = 0;
      let cnt = 0;
      if (dens) {
        dens.t.forEach((t, idx) => {
          if (t >= lo && t < hi) {
            sum += dens.y[idx] ?? 0;
            cnt += 1;
          }
        });
      }
      return cnt > 0 ? Number(((sum / cnt) * 60).toFixed(1)) : 0;
    });
  }

  const off = round.offense.find((o) => cornerColor(o.corner) === cornerColorName);
  const punches = (off?.punches ?? []).filter((p) => p.speed != null);
  return Array.from({ length: binCount }, (_, b) => {
    const center = b * step + step / 2;
    const windowPunches = punches.filter((p) => Math.abs(p.t_sec - center) <= 10);
    if (windowPunches.length === 0) return 0;
    const avg = windowPunches.reduce((acc, p) => acc + (p.speed ?? 0), 0) / windowPunches.length;
    return Number(avg.toFixed(2));
  });
}

function deltaPctText(early: number | null | undefined, late: number | null | undefined): string {
  if (early == null || late == null || early === 0) return "—";
  const d = ((late - early) / early) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(1)}%`;
}

export function ForceDegradationView({ report }: { report: FightAnalytics }) {
  const completed = report.rounds.filter((r) => r.completed);
  const defaultFocal = getFocalColor(report);
  const [focusCorner, setFocusCorner] = useState<CornerColor>(defaultFocal);
  const [baseIdx, setBaseIdx] = useState(0);
  const [lateIdx, setLateIdx] = useState(Math.max(0, completed.length - 1));
  const [showRed, setShowRed] = useState(true);
  const [showBlue, setShowBlue] = useState(true);
  const [curveMetric, setCurveMetric] = useState<"speed" | "density">("speed");

  useEffect(() => {
    setFocusCorner(defaultFocal);
    setBaseIdx(completed[0]?.index ?? 0);
    setLateIdx(completed[completed.length - 1]?.index ?? 0);
  }, [report.session.name, defaultFocal, completed.length]);

  const red = getFighter(report, "red");
  const blue = getFighter(report, "blue");
  const redName = red?.name ?? "Red";
  const blueName = blue?.name ?? "Blue";

  const { primaryColor, primaryName, opponentName } = getFighterRoles(report, focusCorner);
  const isPrimaryRed = primaryColor === "red";
  const primaryTextCls = isPrimaryRed ? "text-primary" : "text-secondary";
  const primaryBadgeCls = isPrimaryRed
    ? "bg-on-primary-container text-primary"
    : "bg-on-secondary-container text-secondary";
  const oppTextCls = isPrimaryRed ? "text-secondary" : "text-primary";

  const safeBaseIdx = completed.some((r) => r.index === baseIdx) ? baseIdx : (completed[0]?.index ?? 0);
  const safeLateIdx = completed.some((r) => r.index === lateIdx)
    ? lateIdx
    : (completed[completed.length - 1]?.index ?? 0);

  const rBase = completed.find((r) => r.index === safeBaseIdx) ?? completed[0];
  const rLate = completed.find((r) => r.index === safeLateIdx) ?? completed[completed.length - 1];

  const redBaseOff = rBase?.offense.find((o) => cornerColor(o.corner) === "red");
  const redLateOff = rLate?.offense.find((o) => cornerColor(o.corner) === "red");
  const blueBaseOff = rBase?.offense.find((o) => cornerColor(o.corner) === "blue");
  const blueLateOff = rLate?.offense.find((o) => cornerColor(o.corner) === "blue");

  const redBaseDef = rBase?.defense.find((d) => cornerColor(d.corner) === "red");
  const redLateDef = rLate?.defense.find((d) => cornerColor(d.corner) === "red");
  const blueBaseDef = rBase?.defense.find((d) => cornerColor(d.corner) === "blue");
  const blueLateDef = rLate?.defense.find((d) => cornerColor(d.corner) === "blue");

  const priBaseOff = isPrimaryRed ? redBaseOff : blueBaseOff;
  const priLateOff = isPrimaryRed ? redLateOff : blueLateOff;
  const oppLateOff = isPrimaryRed ? blueLateOff : redLateOff;
  const priBaseDef = isPrimaryRed ? redBaseDef : blueBaseDef;
  const priLateDef = isPrimaryRed ? redLateDef : blueLateDef;
  const oppLateDef = isPrimaryRed ? blueLateDef : redLateDef;
  const priBaseInflicted = isPrimaryRed ? rBase?.blue.received_damage : rBase?.red.received_damage;
  const priLateInflicted = isPrimaryRed ? rLate?.blue.received_damage : rLate?.red.received_damage;
  const priLateStunsInflicted = isPrimaryRed ? (rLate?.blue.stuns ?? 0) : (rLate?.red.stuns ?? 0);

  const hasBlueSpeed = (blueBaseOff?.velocity.samples ?? 0) > 0 || (blueLateOff?.velocity.samples ?? 0) > 0;
  const hasRedSpeed = (redBaseOff?.velocity.samples ?? 0) > 0 || (redLateOff?.velocity.samples ?? 0) > 0;
  const effectiveCurveMode = curveMetric === "speed" && !hasRedSpeed && !hasBlueSpeed ? "density" : curveMetric;

  const maxRoundSec = Math.max(
    60,
    rBase?.duration_sec ?? report.session.round_duration_sec,
    rLate?.duration_sec ?? report.session.round_duration_sec,
  );

  const curveData: CurveRow[] = useMemo(() => {
    const rb = rollingPunchMetric(rBase, "red", effectiveCurveMode, maxRoundSec);
    const rl = rollingPunchMetric(rLate, "red", effectiveCurveMode, maxRoundSec);
    const bb = rollingPunchMetric(rBase, "blue", effectiveCurveMode, maxRoundSec);
    const bl = rollingPunchMetric(rLate, "blue", effectiveCurveMode, maxRoundSec);
    return rb.map((_, idx) => ({
      t: idx * 5 + 2.5,
      redBase: rb[idx] || null,
      redLate: rl[idx] || null,
      blueBase: bb[idx] || null,
      blueLate: bl[idx] || null,
    }));
  }, [rBase, rLate, effectiveCurveMode, maxRoundSec]);

  // Trajectory comparison ledger
  const trajRows = useMemo(() => {
    const out: {
      key: string;
      color: "red" | "blue";
      fighterName: string;
      trajectory: string;
      baseThrown: number;
      lateThrown: number;
      baseAcc: number | null;
      lateAcc: number | null;
      baseSpeed: number | null;
      lateSpeed: number | null;
    }[] = [];

    const addCorner = (
      color: "red" | "blue",
      fighterName: string,
      bOff: typeof redBaseOff,
      lOff: typeof redLateOff,
    ) => {
      const names = Array.from(
        new Set([
          ...(bOff?.trajectories.map((t) => t.trajectory) ?? []),
          ...(lOff?.trajectories.map((t) => t.trajectory) ?? []),
        ]),
      ).filter((n) => n !== "unknown");

      for (const name of names) {
        const bT = bOff?.trajectories.find((t) => t.trajectory === name);
        const lT = lOff?.trajectories.find((t) => t.trajectory === name);
        if ((bT?.thrown ?? 0) + (lT?.thrown ?? 0) < 2) continue;
        out.push({
          key: `${color}-${name}`,
          color,
          fighterName,
          trajectory: name,
          baseThrown: bT?.thrown ?? 0,
          lateThrown: lT?.thrown ?? 0,
          baseAcc: bT?.accuracy ?? null,
          lateAcc: lT?.accuracy ?? null,
          baseSpeed: bT?.mean_speed ?? null,
          lateSpeed: lT?.mean_speed ?? null,
        });
      }
    };

    addCorner("red", redName, redBaseOff, redLateOff);
    addCorner("blue", blueName, blueBaseOff, blueLateOff);
    return out;
  }, [redName, blueName, redBaseOff, redLateOff, blueBaseOff, blueLateOff]);

  const baseLabel = rBase ? `R${rBase.index + 1}` : "R1";
  const lateLabel = rLate ? `R${rLate.index + 1}` : "R3";

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      {/* Sub-Navigation / Module Context Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md">
        <div className="flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-sm flex-wrap">
            <span className="px-space-xs py-0.5 rounded bg-surface-container-high text-primary font-label-caps text-label-caps tracking-widest uppercase">
              Telemetry Protocol // MODULE 05
            </span>
            <span className="text-outline font-label-data text-label-data">
              SOURCE: {report.session.source}
            </span>
          </div>
          <div className="flex items-baseline gap-space-md flex-wrap">
            <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight uppercase m-0">
              {baseLabel} vs {lateLabel} Degradation &amp; Kinetic Attenuation
            </h1>
            {completed.length < 2 && (
              <span className="font-label-data text-label-data text-tertiary bg-surface-container px-space-sm py-space-xs rounded">
                Single completed round — baseline compared against itself
              </span>
            )}
          </div>
        </div>

        {/* Round Pair Selector + KPI Focus + Chart Trace Toggles */}
        <div className="flex items-center gap-space-sm flex-wrap">
          {completed.length >= 2 && (
            <div className="flex items-center gap-space-xs bg-surface-container-low p-space-xs rounded font-label-data text-label-data">
              <span className="text-outline px-1">Baseline:</span>
              <select
                aria-label="Baseline round"
                value={safeBaseIdx}
                onChange={(e) => setBaseIdx(Number(e.target.value))}
                className="min-h-[32px] bg-surface-container-lowest text-on-surface px-2 py-1 rounded outline-none cursor-pointer"
              >
                {completed.map((r) => (
                  <option key={r.index} value={r.index}>
                    Round {r.index + 1}
                  </option>
                ))}
              </select>
              <span className="text-outline px-1">vs</span>
              <select
                aria-label="Comparison round"
                value={safeLateIdx}
                onChange={(e) => setLateIdx(Number(e.target.value))}
                className="min-h-[32px] bg-surface-container-lowest text-on-surface px-2 py-1 rounded outline-none cursor-pointer"
              >
                {completed.map((r) => (
                  <option key={r.index} value={r.index}>
                    Round {r.index + 1}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="flex items-center bg-surface-container-lowest p-0.5 rounded gap-1">
            <span className="font-label-caps text-label-caps text-outline px-space-xs hidden sm:inline">KPIs:</span>
            <button
              type="button"
              aria-pressed={focusCorner === "red"}
              onClick={() => setFocusCorner("red")}
              className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps font-bold transition-colors ${
                focusCorner === "red"
                  ? "bg-on-primary-container text-primary"
                  : "text-outline hover:text-on-surface"
              }`}
            >
              {redName}
            </button>
            <button
              type="button"
              aria-pressed={focusCorner === "blue"}
              onClick={() => setFocusCorner("blue")}
              className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps font-bold transition-colors ${
                focusCorner === "blue"
                  ? "bg-on-secondary-container text-secondary"
                  : "text-outline hover:text-on-surface"
              }`}
            >
              {blueName}
            </button>
          </div>
        </div>
      </div>

      {/* Executive KPI Telemetry Grid (Delta Strip Base -> Late for Focus Fighter) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-space-md">
        {/* Card 1: Mean Speed Retention */}
        <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm">
          <div className="flex items-start justify-between gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase">Mean Speed Retention</span>
            <span className={`font-label-caps text-label-caps px-1.5 py-0.5 rounded font-bold ${primaryBadgeCls}`}>
              {deltaPctText(priBaseOff?.velocity.mean_thrown, priLateOff?.velocity.mean_thrown)}
            </span>
          </div>
          <div className="my-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className={`font-telemetry-metric-lg font-bold ${primaryTextCls}`}>
                {num(priLateOff?.velocity.mean_thrown, 2)}
              </span>
              <span className="font-label-data text-outline">m/s ({lateLabel})</span>
            </div>
            <div className="flex items-center justify-between text-body-sm text-outline mt-1 font-label-data gap-1">
              <span>
                {baseLabel}: {num(priBaseOff?.velocity.mean_thrown, 2)} m/s
              </span>
              <span className={`${oppTextCls} truncate`}>
                {opponentName}: {oppLateOff?.velocity.mean_thrown != null ? `${num(oppLateOff.velocity.mean_thrown, 2)}` : "—"}
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Accuracy Shift */}
        <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm">
          <div className="flex items-start justify-between gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase">Accuracy Shift</span>
            <span className="font-label-caps text-label-caps text-tertiary bg-on-tertiary-container px-1.5 py-0.5 rounded font-bold">
              {deltaPctText(priBaseOff?.accuracy, priLateOff?.accuracy)}
            </span>
          </div>
          <div className="my-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className={`font-telemetry-metric-lg font-bold ${primaryTextCls}`}>
                {pct(priLateOff?.accuracy)}
              </span>
              <span className="font-label-data text-outline">({lateLabel})</span>
            </div>
            <div className="flex items-center justify-between text-body-sm text-outline mt-1 font-label-data gap-1">
              <span>
                {baseLabel}: {pct(priBaseOff?.accuracy)}
              </span>
              <span className={`${oppTextCls} truncate`}>
                {opponentName}: {pct(oppLateOff?.accuracy)}
              </span>
            </div>
          </div>
        </div>

        {/* Card 3: Punch Frequency */}
        <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm">
          <div className="flex items-start justify-between gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase">Punch Frequency</span>
            <span className={`font-label-caps text-label-caps px-1.5 py-0.5 rounded font-bold ${primaryBadgeCls}`}>
              {deltaPctText(priBaseOff?.punches_per_minute, priLateOff?.punches_per_minute)}
            </span>
          </div>
          <div className="my-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className={`font-telemetry-metric-lg font-bold ${primaryTextCls}`}>
                {num(priLateOff?.punches_per_minute, 1)}
              </span>
              <span className="font-label-data text-outline">PPM</span>
            </div>
            <div className="flex items-center justify-between text-body-sm text-outline mt-1 font-label-data gap-1">
              <span>
                {baseLabel}: {num(priBaseOff?.punches_per_minute, 1)} PPM
              </span>
              <span className={`${oppTextCls} truncate`}>
                {opponentName}: {num(oppLateOff?.punches_per_minute, 1)}
              </span>
            </div>
          </div>
        </div>

        {/* Card 4: Official Damage Inflicted */}
        <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm">
          <div className="flex items-start justify-between gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase truncate">
              Damage Inflicted ({primaryName})
            </span>
            <span className={`font-label-caps text-label-caps px-1.5 py-0.5 rounded font-bold shrink-0 ${primaryBadgeCls}`}>
              {deltaPctText(priBaseInflicted, priLateInflicted)}
            </span>
          </div>
          <div className="my-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className={`font-telemetry-metric-lg font-bold ${primaryTextCls}`}>
                {Math.round(priLateInflicted ?? 0)}
              </span>
              <span className="font-label-data text-outline">PTS ({lateLabel})</span>
            </div>
            <div className="flex items-center justify-between text-body-sm text-outline mt-1 font-label-data">
              <span>
                {baseLabel}: {Math.round(priBaseInflicted ?? 0)} PTS
              </span>
              <span>Stuns: {priLateStunsInflicted}</span>
            </div>
          </div>
        </div>

        {/* Card 5: Retraction Latency */}
        <div className="bg-surface-container-low rounded p-space-md flex flex-col justify-between shadow-sm">
          <div className="flex items-start justify-between gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase">Retraction Median</span>
            <span className="font-label-caps text-label-caps text-on-surface bg-surface-container px-1.5 py-0.5 rounded font-bold">
              {deltaPctText(
                priBaseDef?.guard_discipline.retraction_time_ms.median,
                priLateDef?.guard_discipline.retraction_time_ms.median,
              )}
            </span>
          </div>
          <div className="my-space-sm">
            <div className="flex items-baseline gap-space-xs">
              <span className={`font-telemetry-metric-lg font-bold ${primaryTextCls}`}>
                {num(priLateDef?.guard_discipline.retraction_time_ms.median, 0)}
              </span>
              <span className="font-label-data text-outline">ms ({lateLabel})</span>
            </div>
            <div className="flex items-center justify-between text-body-sm text-outline mt-1 font-label-data gap-1">
              <span>
                {baseLabel}: {num(priBaseDef?.guard_discipline.retraction_time_ms.median, 0)} ms
              </span>
              <span className={`${oppTextCls} truncate`}>
                {opponentName}: {num(oppLateDef?.guard_discipline.retraction_time_ms.median, 0)} ms
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Primary Analytical Modules Grid (8-col Left + 4-col Right) */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        <div className="xl:col-span-8 flex flex-col gap-space-lg">
          {/* Continuous Time-Series Degradation Curve */}
          <div className="bg-surface-container-low rounded p-space-lg flex flex-col shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm mb-space-md">
              <div>
                <h2 className="font-headline-sm text-headline-sm text-on-surface tracking-tight m-0">
                  {baseLabel} vs {lateLabel} Intra-Round Timeline (0:00 – {clockWhole(maxRoundSec)})
                </h2>
                <span className="font-label-data text-label-data text-outline">
                  {effectiveCurveMode === "speed"
                    ? "Rolling mean punch speed (m/s) across 5s intervals"
                    : "Rolling punch cadence (punches/min) across 5s intervals"}
                </span>
              </div>

              <div className="flex items-center gap-space-xs flex-wrap">
                <div className="flex items-center bg-surface-container-lowest p-0.5 rounded gap-1">
                  <button
                    type="button"
                    aria-pressed={showRed}
                    onClick={() => setShowRed((v) => !v)}
                    className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps transition-all flex items-center gap-1.5 ${
                      showRed ? "bg-on-primary-container text-primary" : "text-outline opacity-50"
                    }`}
                  >
                    <span className="w-2 h-2 rounded-full bg-primary-container" aria-hidden="true" />
                    {redName}
                  </button>
                  <button
                    type="button"
                    aria-pressed={showBlue}
                    onClick={() => setShowBlue((v) => !v)}
                    className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps transition-all flex items-center gap-1.5 ${
                      showBlue ? "bg-on-secondary-container text-secondary" : "text-outline opacity-50"
                    }`}
                  >
                    <span className="w-2 h-2 rounded-full bg-secondary" aria-hidden="true" />
                    {blueName}
                  </button>
                </div>

                <div className="flex items-center bg-surface-container-lowest p-0.5 rounded gap-1">
                  <button
                    type="button"
                    aria-pressed={effectiveCurveMode === "speed"}
                    onClick={() => setCurveMetric("speed")}
                    className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps ${
                      effectiveCurveMode === "speed" ? "bg-surface-bright text-on-surface" : "text-outline"
                    }`}
                  >
                    Speed (m/s)
                  </button>
                  <button
                    type="button"
                    aria-pressed={effectiveCurveMode === "density"}
                    onClick={() => setCurveMetric("density")}
                    className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps ${
                      effectiveCurveMode === "density" ? "bg-surface-bright text-on-surface" : "text-outline"
                    }`}
                  >
                    Pace (PPM)
                  </button>
                </div>
              </div>
            </div>

            <div className="w-full h-72 bg-surface-container-lowest rounded p-space-sm">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={curveData}>
                  <CartesianGrid stroke={GRID_HEX} strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="t"
                    stroke={MUTED_HEX}
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => clockWhole(Number(v))}
                  />
                  <YAxis stroke={MUTED_HEX} tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#181c23", border: "1px solid #31353d", fontSize: 12 }}
                    labelFormatter={(v) => `Round clock ${clockWhole(Number(v))}`}
                  />
                  <Legend />
                  {showRed && (
                    <Line
                      type="monotone"
                      dataKey="redBase"
                      name={`${redName} ${baseLabel}`}
                      stroke={RED_SOFT_HEX}
                      strokeWidth={2}
                      dot={false}
                      connectNulls
                    />
                  )}
                  {showRed && (
                    <Line
                      type="monotone"
                      dataKey="redLate"
                      name={`${redName} ${lateLabel}`}
                      stroke={RED_HEX}
                      strokeDasharray="6 3"
                      strokeWidth={2.5}
                      dot={false}
                      connectNulls
                    />
                  )}
                  {showBlue && (effectiveCurveMode === "density" || hasBlueSpeed) && (
                    <Line
                      type="monotone"
                      dataKey="blueBase"
                      name={`${blueName} ${baseLabel}`}
                      stroke={BLUE_HEX}
                      strokeWidth={1.8}
                      dot={false}
                      connectNulls
                    />
                  )}
                  {showBlue && (effectiveCurveMode === "density" || hasBlueSpeed) && (
                    <Line
                      type="monotone"
                      dataKey="blueLate"
                      name={`${blueName} ${lateLabel}`}
                      stroke={BLUE_CONTAINER_HEX}
                      strokeDasharray="4 3"
                      strokeWidth={2}
                      dot={false}
                      connectNulls
                    />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Combination Depth Kinetic Decay Profile */}
          <div className="bg-surface-container-low rounded p-space-lg shadow-sm">
            <div className="mb-space-md">
              <h2 className="font-headline-sm text-headline-sm text-on-surface m-0">
                Combination Depth Attenuation ({baseLabel} → {lateLabel})
              </h2>
              <p className="font-label-data text-label-data text-outline m-0">
                Accuracy and mean speed at each combination depth across the selected round pair
              </p>
            </div>

            <div className="space-y-space-md">
              {DEPTHS.map((d) => {
                const rB = redBaseOff?.combinations.by_depth.find((x) => x.depth === d);
                const rL = redLateOff?.combinations.by_depth.find((x) => x.depth === d);
                const bB = blueBaseOff?.combinations.by_depth.find((x) => x.depth === d);
                const bL = blueLateOff?.combinations.by_depth.find((x) => x.depth === d);
                const redAccW = clampPct((rL?.accuracy ?? 0) * 100);
                const blueAccW = clampPct((bL?.accuracy ?? 0) * 100);
                return (
                  <div key={d} className="flex flex-col gap-1.5">
                    <div className="flex justify-between items-center font-label-data text-body-sm flex-wrap gap-2">
                      <span className="text-on-surface font-medium">Depth {d}</span>
                      <div className="flex items-center gap-space-md flex-wrap">
                        <span className="text-primary font-bold">
                          RED {baseLabel}: {pct(rB?.accuracy)} ({num(rB?.mean_speed, 2)} m/s) → {lateLabel}:{" "}
                          {pct(rL?.accuracy)} ({num(rL?.mean_speed, 2)} m/s)
                        </span>
                        <span className="text-secondary font-bold">
                          BLU {baseLabel}: {pct(bB?.accuracy)} ({num(bB?.mean_speed, 2)} m/s) → {lateLabel}:{" "}
                          {pct(bL?.accuracy)} ({num(bL?.mean_speed, 2)} m/s)
                        </span>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div
                        className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden"
                        title={`${redName} ${lateLabel} accuracy: ${pct(rL?.accuracy)}`}
                      >
                        <div className="bg-primary-container h-full rounded-sm" style={{ width: `${redAccW}%` }} />
                      </div>
                      <div
                        className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden"
                        title={`${blueName} ${lateLabel} accuracy: ${pct(bL?.accuracy)}`}
                      >
                        <div className="bg-secondary h-full rounded-sm" style={{ width: `${blueAccW}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* RIGHT 4 COLS: Biomechanical Drift Audit */}
        <div className="xl:col-span-4 flex flex-col gap-space-lg">
          {/* Red Corner Drift Card */}
          <div className="bg-surface-container-low rounded p-space-md border-l-2 border-primary-container shadow-sm flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-space-sm">
                <div className="flex items-center gap-space-xs">
                  <span className="w-2.5 h-2.5 rounded bg-primary-container" />
                  <span className="font-headline-sm text-headline-sm text-on-surface">{redName} (RED)</span>
                </div>
                <span className="font-label-caps text-label-caps text-primary bg-on-primary-container px-space-xs py-0.5 rounded">
                  {baseLabel} → {lateLabel}
                </span>
              </div>
              <p className="font-label-data text-label-data text-outline mb-space-md m-0">
                Posture, Guard &amp; Footwork Delta
              </p>

              <div className="space-y-space-sm">
                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">GUARD UPTIME</div>
                    <div className="font-label-data text-on-surface">
                      {pctPts(redBaseDef?.guard_up_percent)} → {pctPts(redLateDef?.guard_up_percent)}
                    </div>
                  </div>
                  <span className="font-label-caps text-primary">
                    {deltaPctText(redBaseDef?.guard_up_percent, redLateDef?.guard_up_percent)}
                  </span>
                </div>

                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">OFF-CENTERLINE SHARE</div>
                    <div className="font-label-data text-on-surface">
                      {pctPts(redBaseDef?.head_movement.off_centerline_percent)} →{" "}
                      {pctPts(redLateDef?.head_movement.off_centerline_percent)}
                    </div>
                  </div>
                  <span className="font-label-caps text-secondary">
                    Trunk IQR: {num(redLateDef?.head_movement.trunk_bend_iqr_m, 2)}m
                  </span>
                </div>

                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">RETURN DROOP MEDIAN</div>
                    <div className="font-label-data text-on-surface">
                      {num(redBaseDef?.guard_discipline.retraction_droop_m.median, 2)}m →{" "}
                      {num(redLateDef?.guard_discipline.retraction_droop_m.median, 2)}m
                    </div>
                  </div>
                  <span className="font-label-caps text-primary">
                    Returned: {pctPts(redLateDef?.guard_discipline.retraction_returned_percent)}
                  </span>
                </div>

                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">CANVAS DISTANCE</div>
                    <div className="font-label-data text-on-surface">
                      {num(redBaseDef?.footwork.total_distance_m, 1)}m →{" "}
                      {num(redLateDef?.footwork.total_distance_m, 1)}m
                    </div>
                  </div>
                  <span className="font-label-caps text-primary">
                    Cuts: {redBaseDef?.footwork.angle_cut_count ?? 0} → {redLateDef?.footwork.angle_cut_count ?? 0}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Blue Corner Drift Card */}
          <div className="bg-surface-container-low rounded p-space-md border-l-2 border-secondary shadow-sm flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-space-sm">
                <div className="flex items-center gap-space-xs">
                  <span className="w-2.5 h-2.5 rounded bg-secondary" />
                  <span className="font-headline-sm text-headline-sm text-on-surface">{blueName} (BLUE)</span>
                </div>
                <span className="font-label-caps text-label-caps text-secondary bg-on-secondary-container px-space-xs py-0.5 rounded">
                  {baseLabel} → {lateLabel}
                </span>
              </div>
              <p className="font-label-data text-label-data text-outline mb-space-md m-0">
                Posture, Guard &amp; Footwork Delta
              </p>

              <div className="space-y-space-sm">
                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">GUARD UPTIME</div>
                    <div className="font-label-data text-on-surface">
                      {pctPts(blueBaseDef?.guard_up_percent)} → {pctPts(blueLateDef?.guard_up_percent)}
                    </div>
                  </div>
                  <span className="font-label-caps text-secondary">
                    {deltaPctText(blueBaseDef?.guard_up_percent, blueLateDef?.guard_up_percent)}
                  </span>
                </div>

                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">OFF-CENTERLINE SHARE</div>
                    <div className="font-label-data text-on-surface">
                      {pctPts(blueBaseDef?.head_movement.off_centerline_percent)} →{" "}
                      {pctPts(blueLateDef?.head_movement.off_centerline_percent)}
                    </div>
                  </div>
                  <span className="font-label-caps text-outline">
                    Ducks: {blueBaseDef?.head_movement.duck_count ?? 0} → {blueLateDef?.head_movement.duck_count ?? 0}
                  </span>
                </div>

                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">RETRACTION MEDIAN</div>
                    <div className="font-label-data text-on-surface">
                      {num(blueBaseDef?.guard_discipline.retraction_time_ms.median, 0)}ms →{" "}
                      {num(blueLateDef?.guard_discipline.retraction_time_ms.median, 0)}ms
                    </div>
                  </div>
                  <span className="font-label-caps text-outline">
                    Droop: {num(blueLateDef?.guard_discipline.retraction_droop_m.median, 2)}m
                  </span>
                </div>

                <div className="bg-surface-container p-space-sm rounded flex justify-between items-center">
                  <div>
                    <div className="font-label-caps text-[10px] text-outline">CANVAS DISTANCE</div>
                    <div className="font-label-data text-on-surface">
                      {num(blueBaseDef?.footwork.total_distance_m, 1)}m →{" "}
                      {num(blueLateDef?.footwork.total_distance_m, 1)}m
                    </div>
                  </div>
                  <span className="font-label-caps text-secondary">
                    Cuts: {blueBaseDef?.footwork.angle_cut_count ?? 0} → {blueLateDef?.footwork.angle_cut_count ?? 0}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Comparative Strike Category Ledger */}
      <div className="bg-surface-container-low rounded p-space-lg shadow-sm">
        <div className="mb-space-md">
          <h2 className="font-headline-sm text-headline-sm text-on-surface m-0">
            Kinetic Decay by Strike Category ({baseLabel} vs {lateLabel} Ledger)
          </h2>
          <span className="font-label-data text-label-data text-outline">
            Empirical comparison of volume, accuracy, and mean speed by trajectory class
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container text-outline font-label-caps text-label-caps">
                <th className="p-space-sm">CATEGORY / CORNER</th>
                <th className="p-space-sm">{baseLabel} THROWN</th>
                <th className="p-space-sm">{lateLabel} THROWN</th>
                <th className="p-space-sm">{baseLabel} ACCURACY</th>
                <th className="p-space-sm">{lateLabel} ACCURACY</th>
                <th className="p-space-sm">{baseLabel} SPEED</th>
                <th className="p-space-sm">{lateLabel} SPEED</th>
                <th className="p-space-sm">SPEED Δ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container font-label-data text-label-data">
              {trajRows.map((row) => (
                <tr key={row.key} className="hover:bg-surface-container transition-colors">
                  <td className="p-space-sm flex items-center gap-space-xs">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        row.color === "red" ? "bg-primary-container" : "bg-secondary"
                      }`}
                    />
                    <span className="text-on-surface font-medium">
                      {formatTrajectoryLabel(row.trajectory)} · {row.fighterName}
                    </span>
                  </td>
                  <td className="p-space-sm text-outline">{row.baseThrown}</td>
                  <td className="p-space-sm text-on-surface font-semibold">{row.lateThrown}</td>
                  <td className="p-space-sm text-outline">{pct(row.baseAcc)}</td>
                  <td className="p-space-sm text-on-surface font-semibold">{pct(row.lateAcc)}</td>
                  <td className="p-space-sm text-outline">
                    {row.baseSpeed != null ? `${row.baseSpeed.toFixed(2)} m/s` : "—"}
                  </td>
                  <td className="p-space-sm text-on-surface font-bold">
                    {row.lateSpeed != null ? `${row.lateSpeed.toFixed(2)} m/s` : "—"}
                  </td>
                  <td className="p-space-sm">
                    <span
                      className={
                        row.baseSpeed != null && row.lateSpeed != null
                          ? row.lateSpeed >= row.baseSpeed
                            ? "text-primary font-bold"
                            : "text-tertiary"
                          : "text-outline"
                      }
                    >
                      {deltaPctText(row.baseSpeed, row.lateSpeed)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
