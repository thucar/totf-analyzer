import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
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
  AMBER_HEX,
  BLUE_HEX,
  GRID_HEX,
  MUTED_HEX,
  RED_HEX,
  type CornerColor,
  type ScopeSelection,
  type ViewId,
  clampPct,
  clock,
  combinedPunishmentSeries,
  formatTrajectoryLabel,
  getFighter,
  getFighterRoles,
  getFocalColor,
  getScopeData,
  num,
  pct,
  pctPts,
  percentile,
  roundTimestampLabel,
  seriesMean,
  splitShare,
} from "../utils";

export function KineticsForceView({
  report,
  scope,
  onNavigate,
}: {
  report: FightAnalytics;
  scope: ScopeSelection;
  onNavigate: (view: ViewId) => void;
}) {
  const defaultFocal = getFocalColor(report);
  const [focusCorner, setFocusCorner] = useState<CornerColor>(defaultFocal);

  useEffect(() => {
    setFocusCorner(defaultFocal);
  }, [report.session.name, defaultFocal]);

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
  const primaryBarCls = isPrimaryRed ? "bg-primary-container" : "bg-secondary";
  const oppTextCls = isPrimaryRed ? "text-secondary" : "text-primary";
  const oppBarCls = isPrimaryRed ? "bg-secondary" : "bg-primary-container";

  const {
    redOff,
    blueOff,
    redDef,
    blueDef,
    redStuns,
    blueStuns,
    redDamage,
    blueDamage,
    series,
  } = getScopeData(report, scope);

  const primaryOff = isPrimaryRed ? redOff : blueOff;
  const oppOff = isPrimaryRed ? blueOff : redOff;
  const primaryDef = isPrimaryRed ? redDef : blueDef;
  const oppDef = isPrimaryRed ? blueDef : redDef;
  // Damage inflicted by primary = damage received by opponent
  const primaryInflicted = isPrimaryRed ? blueDamage : redDamage;
  const oppInflicted = isPrimaryRed ? redDamage : blueDamage;
  const primaryStunsInflicted = isPrimaryRed ? blueStuns : redStuns;
  const oppStunsInflicted = isPrimaryRed ? redStuns : blueStuns;

  const redCornerId = red?.corner ?? 2;
  const blueCornerId = blue?.corner ?? 1;

  // Compute real velocity percentiles from punch speeds
  const primarySpeeds = useMemo(
    () => (primaryOff?.punches ?? []).map((p) => p.speed).filter((s): s is number => s != null),
    [primaryOff],
  );
  const oppSpeeds = useMemo(
    () => (oppOff?.punches ?? []).map((p) => p.speed).filter((s): s is number => s != null),
    [oppOff],
  );
  const primaryP90 = percentile(primarySpeeds, 90);
  const oppP90 = percentile(oppSpeeds, 90);

  // Velocity histogram data
  const histogramData = useMemo(() => {
    const rHist = redOff?.velocity.histogram ?? [];
    const bHist = blueOff?.velocity.histogram ?? [];
    const count = Math.max(rHist.length, bHist.length);
    const rows = [];
    for (let i = 0; i < count; i++) {
      const rBin = rHist[i];
      const bBin = bHist[i];
      const lo = rBin?.lo ?? bBin?.lo ?? 0;
      const hi = rBin?.hi ?? bBin?.hi ?? 0;
      rows.push({
        bin: hi >= 25 ? `≥${lo} m/s` : `${lo}–${hi}`,
        red: rBin?.count ?? 0,
        blue: bBin?.count ?? 0,
      });
    }
    return rows;
  }, [redOff, blueOff]);

  // Trajectory velocity cards for focal fighter (top 5 trajectories with speed or volume)
  const trajectoryCards = useMemo(() => {
    return [...(primaryOff?.trajectories ?? [])]
      .filter((t) => t.trajectory !== "unknown" && t.thrown > 0)
      .sort((a, b) => (b.mean_speed ?? 0) - (a.mean_speed ?? 0) || b.thrown - a.thrown)
      .slice(0, 5)
      .map((t) => {
        const matchingPunches = (primaryOff?.punches ?? []).filter(
          (p) => p.trajectory === t.trajectory && p.speed != null,
        );
        const peak = matchingPunches.length
          ? Math.max(...matchingPunches.map((p) => p.speed ?? 0))
          : null;
        return { ...t, peak };
      });
  }, [primaryOff]);

  // Multi-channel punishment series (ch0 + ch1)
  const punishmentTimeline = useMemo(() => combinedPunishmentSeries(series), [series]);
  const redPeakPunish =
    (redDef?.punishment_peak?.[0] ?? 0) + (redDef?.punishment_peak?.[1] ?? 0);
  const bluePeakPunish =
    (blueDef?.punishment_peak?.[0] ?? 0) + (blueDef?.punishment_peak?.[1] ?? 0);

  // Guard channels means (brace [0-8], friction [0-4], mass [0-8], ladder [0-5])
  const redBrace = seriesMean(series, "guard_brace", redCornerId);
  const blueBrace = seriesMean(series, "guard_brace", blueCornerId);
  const redFriction = seriesMean(series, "guard_friction", redCornerId);
  const blueFriction = seriesMean(series, "guard_friction", blueCornerId);
  const redMass = seriesMean(series, "guard_mass", redCornerId);
  const blueMass = seriesMean(series, "guard_mass", blueCornerId);
  const redLadder = seriesMean(series, "guard_ladder", redCornerId);
  const blueLadder = seriesMean(series, "guard_ladder", blueCornerId);
  const redStiffness = seriesMean(series, "stiffness_max", redCornerId);
  const blueStiffness = seriesMean(series, "stiffness_max", blueCornerId);

  // High-velocity impact ledger: top landed punches sorted by glove speed then damage
  const topImpacts = useMemo(() => {
    const merged = [
      ...(redOff?.punches ?? [])
        .filter((p) => p.landed && p.hand !== "unmatched")
        .map((p) => ({ ...p, corner: redCornerId, color: "red" as const, fighterName: redName })),
      ...(blueOff?.punches ?? [])
        .filter((p) => p.landed && p.hand !== "unmatched")
        .map((p) => ({ ...p, corner: blueCornerId, color: "blue" as const, fighterName: blueName })),
    ];
    return merged
      .sort(
        (a, b) =>
          (b.speed ?? -1) - (a.speed ?? -1) ||
          (b.damage ?? 0) - (a.damage ?? 0),
      )
      .slice(0, 10);
  }, [redOff, blueOff, redCornerId, blueCornerId, redName, blueName]);

  const [dmgSharePrimary, dmgShareOpp] = splitShare(primaryInflicted, oppInflicted);
  const primaryStiffness = isPrimaryRed ? redStiffness : blueStiffness;
  const oppStiffness = isPrimaryRed ? blueStiffness : redStiffness;

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      {/* TOP SUB-HEADER & FOCAL CORNER SWITCHER */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md p-space-md bg-surface-container-low rounded shadow-sm">
        <div className="flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-xs flex-wrap">
            <span className="font-label-caps text-label-caps text-primary uppercase">
              MODULE 04
            </span>
            <span className="text-outline font-label-data text-label-data" aria-hidden="true">/</span>
            <h1 className="font-headline-md text-headline-md uppercase text-on-surface m-0">
              Kinetics, Velocity Spectrum &amp; Punishment Meters
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-space-sm font-label-data text-label-data text-outline">
            <span className="flex items-center gap-space-xs bg-surface-container px-space-xs py-0.5 rounded text-secondary">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" aria-hidden="true" />
              Kinematic Records: {redOff?.kinematic_thrown ?? 0}R · {blueOff?.kinematic_thrown ?? 0}B
            </span>
            <span className="text-outline" aria-hidden="true">·</span>
            <span className="text-tertiary">
              Speed↔Damage r = {num(primaryOff?.velocity.speed_damage_correlation, 2)} ({primaryName})
            </span>
          </div>
        </div>

        <div className="flex items-center gap-space-xs flex-wrap">
          <span className="font-label-caps text-label-caps text-outline uppercase">FOCUS FIGHTER:</span>
          <div className="flex items-center bg-surface-container-lowest p-0.5 rounded gap-1">
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
              {redName} (RED)
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
              {blueName} (BLUE)
            </button>
          </div>
        </div>
      </div>

      {/* TOP PRIMARY METRIC CARDS (5 COLUMNS KPI GRID — FOCUSED ON SELECTED FIGHTER) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-space-md">
        {/* CARD 1: Peak Strike Velocity */}
        <div className="flex flex-col justify-between p-space-md bg-surface-container rounded shadow-sm">
          <div className="flex items-center justify-between mb-space-xs gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
              PEAK VELOCITY
            </span>
            {primaryP90 != null && (
              <span className={`font-label-caps text-label-caps px-space-xs py-0.5 rounded font-bold ${primaryBadgeCls}`}>
                p90: {primaryP90.toFixed(2)}
              </span>
            )}
          </div>
          <div className="flex items-baseline gap-space-xs mb-space-sm">
            <span className={`font-telemetry-metric-lg font-bold tracking-tight ${primaryTextCls}`}>
              {num(primaryOff?.velocity.max_speed, 2)}
            </span>
            <span className="font-label-data text-outline">m/s</span>
            <span className={`ml-auto font-label-caps font-bold ${oppTextCls}`}>
              vs {num(oppOff?.velocity.max_speed, 2)}
            </span>
          </div>
          <div className="flex justify-between text-[11px] font-label-data text-outline">
            <span>Mean: {num(primaryOff?.velocity.mean_thrown, 2)} m/s</span>
            <span>{opponentName} p90: {num(oppP90, 2)}</span>
          </div>
        </div>

        {/* CARD 2: Mean Landed Velocity */}
        <div className="flex flex-col justify-between p-space-md bg-surface-container rounded shadow-sm">
          <div className="flex items-center justify-between mb-space-xs gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
              MEAN LANDED SPEED
            </span>
            <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container-highest text-tertiary font-bold">
              GLOVE SPEED
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs mb-space-sm">
            <span className={`font-telemetry-metric-lg font-bold tracking-tight ${primaryTextCls}`}>
              {num(primaryOff?.velocity.mean_landed, 2)}
            </span>
            <span className="font-label-data text-outline">m/s</span>
            <span className={`ml-auto font-label-caps font-bold ${oppTextCls}`}>
              vs {num(oppOff?.velocity.mean_landed, 2)}
            </span>
          </div>
          <div className="flex justify-between text-[11px] font-label-data text-outline">
            <span>{primaryName}: {primaryOff?.velocity.samples ?? 0}</span>
            <span>{opponentName}: {oppOff?.velocity.samples ?? 0}</span>
          </div>
        </div>

        {/* CARD 3: Official Damage & Stuns Inflicted */}
        <div className="flex flex-col justify-between p-space-md bg-surface-container rounded shadow-sm">
          <div className="flex items-center justify-between mb-space-xs gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
              DAMAGE INFLICTED
            </span>
            <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-error-container text-on-error-container font-bold">
              {primaryStunsInflicted} STUNS
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs mb-space-sm">
            <span className={`font-telemetry-metric-lg font-bold tracking-tight ${primaryTextCls}`}>
              {Math.round(primaryInflicted).toLocaleString()}
            </span>
            <span className="font-label-data text-outline truncate">on {opponentName}</span>
          </div>
          <div className="w-full bg-surface-container-lowest h-1.5 rounded overflow-hidden flex mb-1">
            <div className={`${primaryBarCls} h-full`} style={{ width: `${dmgSharePrimary}%` }} />
            <div className={`${oppBarCls} h-full`} style={{ width: `${dmgShareOpp}%` }} />
          </div>
          <div className="flex justify-between text-[11px] font-label-data text-outline">
            <span>Taken: {Math.round(oppInflicted)}</span>
            <span>Stuns Taken: {oppStunsInflicted}</span>
          </div>
        </div>

        {/* CARD 4: Guard Uptime & Return */}
        <div className="flex flex-col justify-between p-space-md bg-surface-container rounded shadow-sm">
          <div className="flex items-center justify-between mb-space-xs gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
              GUARD UPTIME
            </span>
            <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container-highest text-secondary font-bold">
              {num(primaryDef?.guard_discipline.retraction_time_ms.median, 0)}ms RET
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs mb-space-sm">
            <span className={`font-telemetry-metric-lg font-bold tracking-tight ${primaryTextCls}`}>
              {pctPts(primaryDef?.guard_up_percent)}
            </span>
            <span className={`ml-auto font-label-caps font-bold ${oppTextCls}`}>
              vs {pctPts(oppDef?.guard_up_percent)}
            </span>
          </div>
          <div className="flex justify-between text-[11px] font-label-data text-outline">
            <span>Droop: {num(primaryDef?.guard_discipline.retraction_droop_m.median, 2)}m</span>
            <span>Sag &gt;10cm: {pctPts(primaryDef?.guard_discipline.retraction_droop_m.sag_over_10cm_percent)}</span>
          </div>
        </div>

        {/* CARD 5: Mean Punishment Delta per Landed */}
        <div className="flex flex-col justify-between p-space-md bg-surface-container rounded shadow-sm">
          <div className="flex items-center justify-between mb-space-xs gap-1">
            <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
              DAMAGE / LANDED
            </span>
            <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-tertiary-container text-on-tertiary font-bold">
              HIT EVENT
            </span>
          </div>
          <div className="flex items-baseline gap-space-xs mb-space-sm">
            <span className="font-telemetry-metric-lg text-tertiary font-bold tracking-tight">
              {num(primaryOff?.velocity.mean_damage_landed, 2)}
            </span>
            <span className="font-label-data text-outline">pts/hit</span>
            <span className={`ml-auto font-label-caps font-bold ${oppTextCls}`}>
              vs {num(oppOff?.velocity.mean_damage_landed, 2)}
            </span>
          </div>
          <div className="flex justify-between text-[11px] font-label-data text-outline">
            <span>Stiff ({primaryName}): {num(primaryStiffness, 2)}</span>
            <span>{opponentName}: {num(oppStiffness, 2)}</span>
          </div>
        </div>
      </div>

      {/* MAIN SECTION 1: VELOCITY HISTOGRAM & CORRELATION */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md items-stretch">
        <div className="lg:col-span-8 flex flex-col p-space-lg bg-surface-container-low rounded shadow-sm justify-between">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-space-md gap-space-xs">
            <div>
              <div className="flex items-center gap-space-xs">
                <span className={`w-2 h-2 rounded-full ${primaryBarCls}`} aria-hidden="true" />
                <h2 className="font-headline-sm text-headline-sm uppercase text-on-surface m-0">
                  Punch Speed Histogram &amp; Vector Breakdown ({primaryName})
                </h2>
              </div>
              <span className="font-label-data text-label-data text-outline">
                Bins across [0, 4, 6, 8, 10, 12, 15, 30] m/s of peak glove speed from the skeleton
              </span>
            </div>
          </div>

          <div className="w-full h-56 bg-surface-container-lowest rounded p-space-sm">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={histogramData}>
                <CartesianGrid stroke={GRID_HEX} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bin" stroke={MUTED_HEX} tick={{ fontSize: 11 }} />
                <YAxis stroke={MUTED_HEX} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#181c23", border: "1px solid #31353d", fontSize: 12 }}
                />
                <Legend />
                <Bar dataKey="red" name={redName} fill={RED_HEX} radius={[3, 3, 0, 0]} />
                <Bar dataKey="blue" name={blueName} fill={BLUE_HEX} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Trajectory Velocity Cards (for Focus Fighter) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-space-sm pt-space-md">
            {trajectoryCards.map((t) => (
              <div key={t.trajectory} className="bg-surface-container p-space-sm rounded flex flex-col justify-between">
                <div className="flex items-center justify-between font-label-caps text-label-caps text-outline gap-1">
                  <span className="truncate">{formatTrajectoryLabel(t.trajectory)}</span>
                  <span className={`${primaryTextCls} font-bold shrink-0`}>{pct(t.accuracy, 0)}</span>
                </div>
                <div className="flex items-baseline gap-1 my-1">
                  <span className="font-telemetry-metric-md text-on-surface font-bold">
                    {num(t.mean_speed, 2)}
                  </span>
                  <span className="font-label-data text-outline">m/s</span>
                </div>
                <div className="w-full bg-surface-container-lowest h-1 rounded overflow-hidden">
                  <div
                    className={`${primaryBarCls} h-full`}
                    style={{ width: `${clampPct(((t.mean_speed ?? 0) / 12) * 100)}%` }}
                  />
                </div>
                <span className="text-[11px] font-label-data text-outline pt-1">
                  Peak: {num(t.peak, 2)} m/s ({t.landed}/{t.thrown})
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Right 4 cols: Retraction & Stiffness Telemetry */}
        <div className="lg:col-span-4 flex flex-col justify-between p-space-lg bg-surface-container-low rounded shadow-sm gap-space-md">
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <span className="font-label-caps text-label-caps text-tertiary uppercase tracking-wider">
                KINEMATIC CORRELATION &amp; RETURN
              </span>
              <span className="material-symbols-outlined text-outline text-[18px]" aria-hidden="true">
                biotech
              </span>
            </div>
            <h2 className="font-headline-sm text-headline-sm text-on-surface leading-tight m-0">
              Speed-to-Damage &amp; Retraction Rigor
            </h2>
            <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed m-0">
              Pearson correlation between landed punch glove speed and hit damage:{" "}
              <strong className="text-primary">
                {num(redOff?.velocity.speed_damage_correlation, 3)}
              </strong>{" "}
              ({redName}) vs{" "}
              <strong className="text-secondary">
                {num(blueOff?.velocity.speed_damage_correlation, 3)}
              </strong>{" "}
              ({blueName}).
            </p>
          </div>

          <div className="flex flex-col gap-space-sm">
            <div className="flex flex-col gap-1 bg-surface-container p-space-sm rounded">
              <div className="flex justify-between items-center font-label-caps text-label-caps">
                <span className="text-outline uppercase">Retraction p90 Time</span>
                <span className="text-primary font-bold">
                  {num(redDef?.guard_discipline.retraction_time_ms.p90, 0)} ms vs{" "}
                  {num(blueDef?.guard_discipline.retraction_time_ms.p90, 0)} ms
                </span>
              </div>
              <div className="flex justify-between font-label-data text-[11px] text-outline">
                <span>Mean (R): {num(redDef?.guard_discipline.retraction_time_ms.mean, 0)} ms</span>
                <span>Mean (B): {num(blueDef?.guard_discipline.retraction_time_ms.mean, 0)} ms</span>
              </div>
            </div>

            <div className="flex flex-col gap-1 bg-surface-container p-space-sm rounded">
              <div className="flex justify-between items-center font-label-caps text-label-caps">
                <span className="text-outline uppercase">Return Directness Ratio</span>
                <span className="text-tertiary font-bold">
                  {num(redDef?.guard_discipline.retraction_directness_ratio.median, 2)} R ·{" "}
                  {num(blueDef?.guard_discipline.retraction_directness_ratio.median, 2)} B
                </span>
              </div>
              <div className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden flex">
                <div
                  className="bg-tertiary h-full rounded"
                  style={{
                    width: `${clampPct((redDef?.guard_discipline.retraction_directness_ratio.median ?? 0) * 100)}%`,
                  }}
                />
              </div>
              <span className="font-label-data text-[11px] text-outline">
                Chord length / actual glove arc length [0..1]
              </span>
            </div>

            <div className="flex items-center justify-between p-space-xs bg-surface-container-lowest rounded font-label-data text-label-data">
              <span className="text-outline">Shoulder Blade Angle:</span>
              <span className="text-on-surface font-bold">
                {num(redDef?.footwork.shoulder_blade_angle_deg, 1)}° R /{" "}
                {num(blueDef?.footwork.shoulder_blade_angle_deg, 1)}° B
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* MAIN SECTION 2: MULTI-CHANNEL PUNISHMENT METER DYNAMICS */}
      <div className="flex flex-col p-space-lg bg-surface-container-low rounded shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between pb-space-md gap-space-xs">
          <div>
            <div className="flex items-center gap-space-xs">
              <span className="w-2.5 h-2.5 rounded bg-tertiary" aria-hidden="true" />
              <h2 className="font-headline-sm text-headline-sm uppercase text-on-surface m-0">
                Multi-Channel Punishment Meter Dynamics
              </h2>
            </div>
            <span className="font-label-data text-label-data text-outline">
              0.25s bucketed punishment meter trajectory received by each corner
            </span>
          </div>
          <div className="flex items-center gap-space-md font-label-data text-label-data flex-wrap">
            <div className="flex items-center gap-space-xs">
              <span className="text-outline">{blueName} Peak:</span>
              <span className="font-bold text-secondary px-space-xs py-0.5 rounded bg-on-secondary-container">
                {num(bluePeakPunish, 2)} pts
              </span>
            </div>
            <div className="flex items-center gap-space-xs">
              <span className="text-outline">{redName} Peak:</span>
              <span className="font-bold text-primary px-space-xs py-0.5 rounded bg-on-primary-container">
                {num(redPeakPunish, 2)} pts
              </span>
            </div>
          </div>
        </div>

        <div className="w-full h-64 bg-surface-container-lowest rounded p-space-sm">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={punishmentTimeline}>
              <CartesianGrid stroke={GRID_HEX} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="t"
                stroke={MUTED_HEX}
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => clock(Number(v))}
              />
              <YAxis stroke={MUTED_HEX} tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{ backgroundColor: "#181c23", border: "1px solid #31353d", fontSize: 12 }}
                labelFormatter={(v) => `t = ${clock(Number(v))}`}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="red"
                name={`${redName} Punishment`}
                stroke={RED_HEX}
                dot={false}
                strokeWidth={1.8}
              />
              <Line
                type="monotone"
                dataKey="blue"
                name={`${blueName} Punishment`}
                stroke={BLUE_HEX}
                dot={false}
                strokeWidth={1.8}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* MAIN SECTION 3: GUARD CHANNELS & HIGH-VELOCITY IMPACT LEDGER */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md items-stretch">
        {/* Guard Channels (brace, friction, mass, ladder) */}
        <div className="lg:col-span-6 flex flex-col p-space-lg bg-surface-container-low rounded shadow-sm">
          <div className="flex items-center justify-between pb-space-md">
            <div>
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-secondary text-[18px]" aria-hidden="true">
                  shield
                </span>
                <h2 className="font-headline-sm text-headline-sm uppercase text-on-surface m-0">
                  T2SR Guard Physics (Brace, Friction, Mass, Ladder)
                </h2>
              </div>
              <span className="font-label-data text-label-data text-outline">
                Mean normalized guard telemetry channels across the selected slice
              </span>
            </div>
            <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container-high text-secondary">
              CONFIRMED
            </span>
          </div>

          <div className="flex flex-col gap-space-md flex-1 justify-between">
            {[
              { label: "Guard Brace [0 – 8]", r: redBrace, b: blueBrace, max: 8 },
              { label: "Guard Friction [0 – 4]", r: redFriction, b: blueFriction, max: 4 },
              { label: "Guard Mass [0 – 8]", r: redMass, b: blueMass, max: 8 },
              { label: "Guard Ladder [0 – 5]", r: redLadder, b: blueLadder, max: 5 },
            ].map((ch) => (
              <div key={ch.label} className="bg-surface-container p-space-sm rounded flex flex-col gap-space-xs">
                <div className="flex justify-between items-center font-label-caps text-label-caps">
                  <span className="text-on-surface uppercase font-bold">{ch.label}</span>
                  <span>
                    <span className="text-primary font-bold">Red {num(ch.r, 2)}</span>{" "}
                    <span className="text-outline">vs</span>{" "}
                    <span className="text-secondary font-bold">Blue {num(ch.b, 2)}</span>
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <div className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden flex">
                    <div
                      className="bg-primary h-full rounded"
                      style={{ width: `${clampPct(((ch.r ?? 0) / ch.max) * 100)}%` }}
                    />
                  </div>
                  <div className="w-full bg-surface-container-lowest h-2 rounded overflow-hidden flex">
                    <div
                      className="bg-secondary h-full rounded"
                      style={{ width: `${clampPct(((ch.b ?? 0) / ch.max) * 100)}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* High-Velocity Impact Ledger */}
        <div className="lg:col-span-6 flex flex-col p-space-lg bg-surface-container-low rounded shadow-sm">
          <div className="flex items-center justify-between pb-space-md">
            <div>
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-primary text-[18px]" aria-hidden="true">
                  format_list_bulleted
                </span>
                <h2 className="font-headline-sm text-headline-sm uppercase text-on-surface m-0">
                  Kinetic Impact Ledger
                </h2>
              </div>
              <span className="font-label-data text-label-data text-outline">
                Highest-velocity landed strikes in this slice
              </span>
            </div>
            <span className="font-label-caps text-label-caps text-secondary" style={{ color: AMBER_HEX }}>
              TOP {topImpacts.length} IMPACTS
            </span>
          </div>

          <div className="flex-1 overflow-x-auto bg-surface-container-lowest rounded">
            <table className="w-full text-left font-label-data text-label-data border-collapse">
              <thead>
                <tr className="bg-surface-container-high text-outline font-label-caps text-label-caps uppercase">
                  <th className="py-space-xs px-space-sm">Time</th>
                  <th className="py-space-xs px-space-sm">Corner / Vector</th>
                  <th className="py-space-xs px-space-sm text-right">Speed</th>
                  <th className="py-space-xs px-space-sm text-right">Damage</th>
                  <th className="py-space-xs px-space-sm text-right">Depth</th>
                </tr>
              </thead>
              <tbody className="text-on-surface divide-y divide-surface-container">
                {topImpacts.map((p, idx) => (
                  <tr key={`${p.corner}-${p.t_sec}-${idx}`} className="hover:bg-surface-container transition-colors">
                    <td className="py-space-xs px-space-sm text-outline whitespace-nowrap">
                      {roundTimestampLabel(report, p.t_sec, scope)}
                    </td>
                    <td className="py-space-xs px-space-sm">
                      <span className={p.color === "red" ? "text-primary font-semibold" : "text-secondary font-semibold"}>
                        {p.fighterName}
                      </span>{" "}
                      · {formatTrajectoryLabel(p.trajectory)}
                    </td>
                    <td className="py-space-xs px-space-sm text-right font-bold">
                      {p.speed != null ? `${p.speed.toFixed(2)} m/s` : "—"}
                    </td>
                    <td className="py-space-xs px-space-sm text-right text-tertiary font-bold">
                      {p.damage != null ? `+${p.damage.toFixed(2)}` : "—"}
                    </td>
                    <td className="py-space-xs px-space-sm text-right text-outline">
                      {p.combo_depth ? `D${p.combo_depth}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between pt-space-sm font-label-caps text-label-caps text-outline">
            <span>LANDED TOTAL: {(redOff?.landed ?? 0) + (blueOff?.landed ?? 0)}</span>
            <button
              type="button"
              onClick={() => onNavigate("punch-log")}
              className="min-h-[32px] px-space-xs text-secondary hover:text-on-surface flex items-center gap-0.5 transition-colors"
            >
              <span>Inspect All Strikes</span>
              <span className="material-symbols-outlined text-[14px]" aria-hidden="true">arrow_forward</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
