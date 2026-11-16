import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { FightAnalytics } from "../types";
import {
  BLUE_HEX,
  GRID_HEX,
  MUTED_HEX,
  RED_HEX,
  type ScopeSelection,
  type ViewId,
  clampPct,
  clock,
  clockWhole,
  cornerColor,
  formatMomentDetail,
  formatTokenLabel,
  formatTrajectoryLabel,
  getFighter,
  getScopeData,
  num,
  pct,
  pctPts,
  roundTimestampLabel,
  seriesPoints,
  splitShare,
} from "../utils";

export function FightSummaryView({
  report,
  scope,
  onSelectScope,
  onNavigate,
}: {
  report: FightAnalytics;
  scope: ScopeSelection;
  onSelectScope: (next: ScopeSelection) => void;
  onNavigate: (view: ViewId) => void;
}) {
  const [momentFilter, setMomentFilter] = useState<string>("all");
  const [comboCorner, setComboCorner] = useState<"red" | "blue">("red");

  const red = getFighter(report, "red");
  const blue = getFighter(report, "blue");
  const redName = red?.name ?? "Red";
  const blueName = blue?.name ?? "Blue";

  const {
    completedRounds,
    redOff,
    blueOff,
    redDef,
    blueDef,
    redStuns,
    blueStuns,
    redDamage,
    blueDamage,
    keyMoments,
    series,
  } = getScopeData(report, scope);

  const redAcc = (redOff?.accuracy ?? 0) * 100;
  const blueAcc = (blueOff?.accuracy ?? 0) * 100;
  const accDelta = redAcc - blueAcc;
  const [accShareRed, accShareBlue] = splitShare(redAcc, blueAcc);
  const [dmgShareRed, dmgShareBlue] = splitShare(redDamage, blueDamage);
  const [guardShareRed, guardShareBlue] = splitShare(
    redDef?.guard_up_percent_under_fire,
    blueDef?.guard_up_percent_under_fire,
  );
  const [volShareRed, volShareBlue] = splitShare(redOff?.thrown, blueOff?.thrown);

  // Trajectories sorted by combined thrown count
  const trajNames = Array.from(
    new Set([
      ...(redOff?.trajectories.map((t) => t.trajectory) ?? []),
      ...(blueOff?.trajectories.map((t) => t.trajectory) ?? []),
    ]),
  )
    .filter((t) => t !== "unknown")
    .sort((a, b) => {
      const countA =
        (redOff?.trajectories.find((x) => x.trajectory === a)?.thrown ?? 0) +
        (blueOff?.trajectories.find((x) => x.trajectory === a)?.thrown ?? 0);
      const countB =
        (redOff?.trajectories.find((x) => x.trajectory === b)?.thrown ?? 0) +
        (blueOff?.trajectories.find((x) => x.trajectory === b)?.thrown ?? 0);
      return countB - countA;
    });

  // Hand bars
  const blueLeft = blueOff?.hands.find((h) => h.hand === "left");
  const blueRight = blueOff?.hands.find((h) => h.hand === "right");
  const redLeft = redOff?.hands.find((h) => h.hand === "left");
  const redRight = redOff?.hands.find((h) => h.hand === "right");
  const maxHandThrown = Math.max(
    1,
    blueLeft?.thrown ?? 0,
    blueRight?.thrown ?? 0,
    redLeft?.thrown ?? 0,
    redRight?.thrown ?? 0,
  );

  // Punch density chart
  const densityData = seriesPoints(series, "punch_density");

  // Top punishment combinations for active combo corner
  const activeComboOff = comboCorner === "red" ? redOff : blueOff;
  const topCombos = [...(activeComboOff?.combinations.patterns ?? [])]
    .filter((p) => p.length >= 2)
    .sort(
      (a, b) =>
        (b.mean_punishment_delta ?? 0) * b.count - (a.mean_punishment_delta ?? 0) * a.count ||
        b.landed - a.landed ||
        b.count - a.count,
    )
    .slice(0, 4);

  // Key moments filter
  const momentCounts = new Map<string, number>();
  for (const m of keyMoments) {
    momentCounts.set(m.type, (momentCounts.get(m.type) ?? 0) + 1);
  }
  const momentTypes = ["all", ...Array.from(momentCounts.keys()).sort()];
  const filteredMoments = keyMoments
    .filter((m) => momentFilter === "all" || m.type === momentFilter)
    .slice(0, 12);

  const totalPunchRecords = (redOff?.thrown ?? 0) + (blueOff?.thrown ?? 0);

  // Methodology grouping
  const confirmedNotes = report.decode_status.filter((n) => n.confidence === "confirmed");
  const inferredNotes = report.decode_status.filter((n) => n.confidence === "inferred");
  const unavailNotes = report.decode_status.filter((n) => n.confidence === "unavailable");

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      {/* TOP SUMMARY COMPARISON GRID (4 Distinct Telemetry KPI Modules) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-space-md">
        {/* KPI 1: Strike Accuracy */}
        <div className="bg-surface-container p-space-md rounded-xl flex flex-col justify-between shadow-md relative overflow-hidden">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline uppercase tracking-wider mb-space-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              Strike Accuracy
            </span>
            <span className={accDelta >= 0 ? "text-primary font-bold" : "text-secondary font-bold"}>
              {accDelta >= 0 ? "+" : ""}
              {accDelta.toFixed(1)}% Delta
            </span>
          </div>
          <div className="flex items-baseline justify-between my-space-xs">
            <div>
              <span className="font-display-hero text-telemetry-metric-lg text-primary font-bold">
                {pct(redOff?.accuracy)}
              </span>
              <span className="font-label-data text-body-sm text-outline block">
                {redOff?.landed ?? 0} / {redOff?.thrown ?? 0} Landed
              </span>
            </div>
            <div className="text-right">
              <span className="font-display-hero text-telemetry-metric-lg text-secondary font-bold">
                {pct(blueOff?.accuracy)}
              </span>
              <span className="font-label-data text-body-sm text-outline block">
                {blueOff?.landed ?? 0} / {blueOff?.thrown ?? 0} Landed
              </span>
            </div>
          </div>
          <div className="w-full bg-surface-container-lowest h-2 rounded-full flex overflow-hidden mt-space-sm">
            <div className="bg-primary-container h-full transition-all duration-500" style={{ width: `${accShareRed}%` }} />
            <div className="bg-surface-container-high h-full w-1" />
            <div className="bg-secondary-container h-full transition-all duration-500" style={{ width: `${accShareBlue}%` }} />
          </div>
          <div className="flex justify-between items-center mt-space-xs font-label-data text-label-caps text-outline">
            <span className="text-primary truncate">{redName} (RED)</span>
            <span className="text-secondary truncate">{blueName} (BLUE)</span>
          </div>
        </div>

        {/* KPI 2: Damage Absorbed & Stuns */}
        <div className="bg-surface-container p-space-md rounded-xl flex flex-col justify-between shadow-md relative overflow-hidden">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline uppercase tracking-wider mb-space-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-tertiary" />
              Official Damage Taken
            </span>
            <span className="text-tertiary font-bold">
              Stuns Taken: {redStuns}R · {blueStuns}B
            </span>
          </div>
          <div className="flex items-baseline justify-between my-space-xs">
            <div>
              <span className="font-display-hero text-telemetry-metric-lg text-on-surface font-bold">
                {Math.round(redDamage).toLocaleString()}
              </span>
              <span className="font-label-data text-body-sm text-outline block">{redName} Absorbed</span>
            </div>
            <div className="text-right">
              <span className="font-display-hero text-telemetry-metric-lg text-secondary font-bold">
                {Math.round(blueDamage).toLocaleString()}
              </span>
              <span className="font-label-data text-body-sm text-outline block">{blueName} Absorbed</span>
            </div>
          </div>
          <div className="w-full bg-surface-container-lowest h-2 rounded-full flex overflow-hidden mt-space-sm">
            <div className="bg-primary h-full transition-all duration-500" style={{ width: `${dmgShareRed}%` }} />
            <div className="bg-surface-container-high h-full w-1" />
            <div className="bg-secondary h-full transition-all duration-500" style={{ width: `${dmgShareBlue}%` }} />
          </div>
          <div className="flex justify-between items-center mt-space-xs font-label-data text-label-caps text-outline">
            <span className="text-primary">Peak Punish: {num(redDef?.punishment_peak?.[0], 1)}</span>
            <span className="text-secondary">Peak Punish: {num(blueDef?.punishment_peak?.[0], 1)}</span>
          </div>
        </div>

        {/* KPI 3: Guard Under Fire */}
        <div className="bg-surface-container p-space-md rounded-xl flex flex-col justify-between shadow-md relative overflow-hidden">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline uppercase tracking-wider mb-space-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
              Guard Under Fire
            </span>
            <span className="text-secondary font-bold">Both Gloves Up</span>
          </div>
          <div className="flex items-baseline justify-between my-space-xs">
            <div>
              <span className="font-display-hero text-telemetry-metric-lg text-on-surface font-bold">
                {pctPts(redDef?.guard_up_percent_under_fire)}
              </span>
              <span className="font-label-data text-body-sm text-outline block">
                {num(redDef?.under_fire_seconds, 1)}s Under Fire
              </span>
            </div>
            <div className="text-right">
              <span className="font-display-hero text-telemetry-metric-lg text-secondary font-bold">
                {pctPts(blueDef?.guard_up_percent_under_fire)}
              </span>
              <span className="font-label-data text-body-sm text-outline block">
                {num(blueDef?.under_fire_seconds, 1)}s Under Fire
              </span>
            </div>
          </div>
          <div className="w-full bg-surface-container-lowest h-2 rounded-full flex overflow-hidden mt-space-sm">
            <div className="bg-primary-container h-full transition-all duration-500" style={{ width: `${guardShareRed}%` }} />
            <div className="bg-surface-container-high h-full w-1" />
            <div className="bg-secondary h-full transition-all duration-500" style={{ width: `${guardShareBlue}%` }} />
          </div>
          <div className="flex justify-between items-center mt-space-xs font-label-data text-label-caps text-outline">
            <span>Off-Center: {pctPts(redDef?.head_movement.off_centerline_under_fire_percent)}</span>
            <span className="text-secondary">
              Off-Center: {pctPts(blueDef?.head_movement.off_centerline_under_fire_percent)}
            </span>
          </div>
        </div>

        {/* KPI 4: Pace & Volume */}
        <div className="bg-surface-container p-space-md rounded-xl flex flex-col justify-between shadow-md relative overflow-hidden">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline uppercase tracking-wider mb-space-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-surface-bright" />
              Pace &amp; Volume
            </span>
            <span className="text-on-surface font-bold">{totalPunchRecords} Thrown</span>
          </div>
          <div className="flex items-baseline justify-between my-space-xs">
            <div>
              <span className="font-display-hero text-telemetry-metric-lg text-on-surface font-bold">
                {num(redOff?.punches_per_minute, 1)}
              </span>
              <span className="font-label-data text-body-sm text-outline block">Punches / Min</span>
            </div>
            <div className="text-right">
              <span className="font-display-hero text-telemetry-metric-lg text-on-surface font-bold">
                {num(blueOff?.punches_per_minute, 1)}
              </span>
              <span className="font-label-data text-body-sm text-outline block">Punches / Min</span>
            </div>
          </div>
          <div className="w-full bg-surface-container-lowest h-2 rounded-full flex overflow-hidden mt-space-sm">
            <div className="bg-primary-container h-full transition-all duration-500" style={{ width: `${volShareRed}%` }} />
            <div className="bg-surface-container-high h-full w-1" />
            <div className="bg-secondary-container h-full transition-all duration-500" style={{ width: `${volShareBlue}%` }} />
          </div>
          <div className="flex justify-between items-center mt-space-xs font-label-data text-label-caps text-outline">
            <span>{redOff?.thrown ?? 0} Thrown (R)</span>
            <span>{blueOff?.thrown ?? 0} Thrown (B)</span>
          </div>
        </div>
      </div>

      {/* ROUND SWITCHER & MINI OFFICIAL SCORECARD ROW */}
      {completedRounds.length > 0 && (
        <div className="bg-surface-container-low p-space-md rounded-xl shadow-sm flex flex-col xl:flex-row items-stretch xl:items-center justify-between gap-space-md">
          <div className="flex items-center gap-space-xs bg-surface-container-lowest p-1 rounded-lg flex-wrap">
            <button
              type="button"
              onClick={() => onSelectScope("all")}
              className={`px-space-md py-space-xs rounded font-label-caps text-label-caps uppercase transition-all ${
                scope === "all"
                  ? "bg-surface-container-high text-primary shadow-sm"
                  : "text-outline hover:text-on-surface hover:bg-surface-container"
              }`}
            >
              All Rounds (Full Bout)
            </button>
            {completedRounds.map((r) => (
              <button
                key={r.index}
                type="button"
                onClick={() => onSelectScope(r.index)}
                className={`px-space-md py-space-xs rounded font-label-caps text-label-caps uppercase transition-all ${
                  scope === r.index
                    ? "bg-surface-container-high text-primary shadow-sm"
                    : "text-outline hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                Round {r.index + 1}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-x-auto">
            <div
              className="grid gap-space-xs text-center font-label-data text-label-data min-w-[420px]"
              style={{ gridTemplateColumns: `repeat(${Math.min(completedRounds.length + 1, 5)}, minmax(120px, 1fr))` }}
            >
              <div className="bg-surface-container px-space-sm py-space-xs rounded flex flex-col justify-center">
                <span className="font-label-caps text-label-caps text-outline uppercase">SCORECARD</span>
                <span className="text-on-surface-variant font-medium">
                  {report.session.red_total_score ?? "–"}–{report.session.blue_total_score ?? "–"}
                </span>
              </div>
              {completedRounds.map((r) => {
                const rOff = r.offense.find((o) => cornerColor(o.corner) === "red");
                const bOff = r.offense.find((o) => cornerColor(o.corner) === "blue");
                return (
                  <button
                    key={r.index}
                    type="button"
                    onClick={() => onSelectScope(r.index)}
                    className={`px-space-sm py-space-xs rounded flex flex-col text-left transition-colors ${
                      scope === r.index
                        ? "bg-surface-container-high ring-1 ring-primary/50"
                        : "bg-surface-container hover:bg-surface-container-high"
                    }`}
                  >
                    <div className="flex justify-between items-center text-label-caps text-outline font-label-caps mb-0.5 w-full">
                      <span>
                        R{r.index + 1} ({clockWhole(r.duration_sec)})
                      </span>
                      <span
                        className={
                          r.red.score > r.blue.score
                            ? "text-primary font-bold"
                            : r.blue.score > r.red.score
                              ? "text-secondary font-bold"
                              : "text-tertiary font-bold"
                        }
                      >
                        {r.red.score}-{r.blue.score}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-on-surface w-full text-[11px]">
                      <span className="text-primary font-semibold">
                        {rOff?.landed ?? r.blue.hits}/{rOff?.thrown ?? "—"}
                      </span>
                      <span className="text-outline">vs</span>
                      <span className="text-secondary font-semibold">
                        {bOff?.landed ?? r.red.hits}/{bOff?.thrown ?? "—"}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* QUICK MODULE NAVIGATION PILLS */}
      <div className="flex items-center gap-space-xs overflow-x-auto pb-space-xs">
        <button
          type="button"
          className="flex items-center gap-space-xs px-space-md py-space-sm rounded-lg bg-surface-container-high text-primary font-headline-sm text-body-md font-semibold whitespace-nowrap shadow-sm"
        >
          <span className="material-symbols-outlined text-[18px]">sports_mma</span>
          Overview &amp; Striking
        </button>
        <button
          type="button"
          onClick={() => onNavigate("strike-telemetry")}
          className="flex items-center gap-space-xs px-space-md py-space-sm rounded-lg bg-surface-container-lowest text-outline hover:text-on-surface hover:bg-surface-container transition-colors font-headline-sm text-body-md whitespace-nowrap"
        >
          <span className="material-symbols-outlined text-[18px]">hub</span>
          Combinations Matrix
        </button>
        <button
          type="button"
          onClick={() => onNavigate("spatial-heatmaps")}
          className="flex items-center gap-space-xs px-space-md py-space-sm rounded-lg bg-surface-container-lowest text-outline hover:text-on-surface hover:bg-surface-container transition-colors font-headline-sm text-body-md whitespace-nowrap"
        >
          <span className="material-symbols-outlined text-[18px]">radar</span>
          Spatial Heatmaps &amp; Movement
        </button>
        <button
          type="button"
          onClick={() => onNavigate("kinetics-force")}
          className="flex items-center gap-space-xs px-space-md py-space-sm rounded-lg bg-surface-container-lowest text-outline hover:text-on-surface hover:bg-surface-container transition-colors font-headline-sm text-body-md whitespace-nowrap"
        >
          <span className="material-symbols-outlined text-[18px]">speed</span>
          Kinetics &amp; Velocity
        </button>
        <button
          type="button"
          onClick={() => onNavigate("force-degradation")}
          className="flex items-center gap-space-xs px-space-md py-space-sm rounded-lg bg-surface-container-lowest text-outline hover:text-on-surface hover:bg-surface-container transition-colors font-headline-sm text-body-md whitespace-nowrap"
        >
          <span className="material-symbols-outlined text-[18px]">ecg_heart</span>
          Round Degradation Curves
        </button>
      </div>

      {/* PRIMARY 12-COLUMN ANALYTICS BENTO GRID */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* LEFT 7 COLS */}
        <div className="xl:col-span-7 flex flex-col space-y-space-lg">
          {/* Strike Distribution by Vector */}
          <div className="bg-surface-container p-space-lg rounded-xl shadow-md flex flex-col">
            <div className="flex items-center justify-between mb-space-md flex-wrap gap-2">
              <div>
                <h2 className="font-headline-sm text-headline-sm text-on-surface m-0">Strike Distribution by Vector</h2>
                <p className="font-label-data text-body-sm text-outline m-0">
                  Landed / Thrown and accuracy per trajectory class
                </p>
              </div>
              <div className="flex items-center gap-space-md font-label-caps text-label-caps">
                <span className="flex items-center gap-1 text-primary">
                  <span className="w-2 h-2 rounded bg-primary" />
                  {redName}
                </span>
                <span className="flex items-center gap-1 text-secondary">
                  <span className="w-2 h-2 rounded bg-secondary" />
                  {blueName}
                </span>
              </div>
            </div>

            <div className="space-y-space-md">
              {trajNames.length === 0 && (
                <p className="font-label-data text-outline">No classified trajectories in this slice.</p>
              )}
              {trajNames.map((tName) => {
                const rT = redOff?.trajectories.find((x) => x.trajectory === tName);
                const bT = blueOff?.trajectories.find((x) => x.trajectory === tName);
                const rAccPct = clampPct((rT?.accuracy ?? 0) * 100);
                const bAccPct = clampPct((bT?.accuracy ?? 0) * 100);
                return (
                  <div key={tName} className="bg-surface-container-low p-space-sm rounded-lg">
                    <div className="flex justify-between items-center font-label-data text-body-sm mb-space-xs flex-wrap gap-2">
                      <span className="font-bold text-on-surface uppercase tracking-wide">
                        {formatTrajectoryLabel(tName)}
                      </span>
                      <div className="flex items-center gap-space-sm">
                        <span className="text-primary font-medium">
                          {rT?.landed ?? 0}/{rT?.thrown ?? 0} ({pct(rT?.accuracy ?? null)})
                        </span>
                        <span className="text-outline">vs</span>
                        <span className="text-secondary font-medium">
                          {bT?.landed ?? 0}/{bT?.thrown ?? 0} ({pct(bT?.accuracy ?? null)})
                        </span>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-space-xs h-2.5">
                      <div className="w-full bg-surface-container-lowest rounded-full overflow-hidden flex justify-end">
                        <div className="bg-primary h-full rounded-full" style={{ width: `${rAccPct}%` }} />
                      </div>
                      <div className="w-full bg-surface-container-lowest rounded-full overflow-hidden">
                        <div className="bg-secondary h-full rounded-full" style={{ width: `${bAccPct}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Dual Telemetry Panels: Hand Allocation & Punch Density */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
            {/* Hand Allocation */}
            <div className="bg-surface-container p-space-md rounded-xl shadow-md flex flex-col justify-between">
              <div className="flex justify-between items-start mb-space-xs">
                <div>
                  <span className="font-headline-sm text-body-lg font-bold text-on-surface block">
                    Landed vs Thrown by Hand
                  </span>
                  <span className="font-label-data text-label-caps text-outline">Left &amp; Right wrist volume</span>
                </div>
                <span className="material-symbols-outlined text-outline">pan_tool</span>
              </div>

              <div className="h-44 w-full flex items-end justify-between px-space-sm pt-space-lg gap-space-sm">
                {[
                  { label: "B-Left", row: blueLeft, color: "secondary" as const },
                  { label: "B-Right", row: blueRight, color: "secondary" as const },
                  { label: "R-Left", row: redLeft, color: "primary" as const },
                  { label: "R-Right", row: redRight, color: "primary" as const },
                ].map((bar) => {
                  const thrown = bar.row?.thrown ?? 0;
                  const landed = bar.row?.landed ?? 0;
                  const thrownH = Math.max(4, (thrown / maxHandThrown) * 100);
                  const landedH = thrown > 0 ? Math.max(0, (landed / thrown) * 100) : 0;
                  const isRed = bar.color === "primary";
                  return (
                    <div key={bar.label} className="flex-1 flex flex-col items-center gap-1">
                      <span className="font-label-caps text-label-caps text-outline">
                        {landed}/{thrown}
                      </span>
                      <div className="w-full bg-surface-container-lowest rounded-t h-32 flex flex-col justify-end p-0.5">
                        <div
                          className={`w-full rounded-t flex flex-col justify-end ${
                            isRed ? "bg-primary/30" : "bg-secondary/30"
                          }`}
                          style={{ height: `${thrownH}%` }}
                        >
                          <div
                            className={`w-full rounded-t ${isRed ? "bg-primary" : "bg-secondary"}`}
                            style={{ height: `${landedH}%` }}
                          />
                        </div>
                      </div>
                      <span
                        className={`font-label-data text-label-caps ${isRed ? "text-primary" : "text-secondary"}`}
                      >
                        {bar.label}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="flex justify-center items-center gap-space-md pt-space-xs font-label-data text-label-caps text-outline">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded bg-surface-variant" /> Thrown
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded bg-primary" /> Landed (R)
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded bg-secondary" /> Landed (B)
                </span>
              </div>
            </div>

            {/* Punch Density Over Time */}
            <div className="bg-surface-container p-space-md rounded-xl shadow-md flex flex-col justify-between">
              <div className="flex justify-between items-start mb-space-xs">
                <div>
                  <span className="font-headline-sm text-body-lg font-bold text-on-surface block">
                    Punch Density Curve
                  </span>
                  <span className="font-label-data text-label-caps text-outline">1-second punch bin counts</span>
                </div>
                <span className="material-symbols-outlined text-outline">stacked_line_chart</span>
              </div>
              <div className="h-44 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={densityData}>
                    <CartesianGrid stroke={GRID_HEX} strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="t"
                      stroke={MUTED_HEX}
                      tick={{ fontSize: 10 }}
                      tickFormatter={(v) => clockWhole(Number(v))}
                    />
                    <YAxis stroke={MUTED_HEX} tick={{ fontSize: 10 }} width={26} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#181c23", border: "1px solid #31353d", fontSize: 12 }}
                      labelFormatter={(v) => `t = ${clock(Number(v))}`}
                    />
                    <Line type="monotone" dataKey="red" name={redName} stroke={RED_HEX} dot={false} strokeWidth={1.8} />
                    <Line
                      type="monotone"
                      dataKey="blue"
                      name={blueName}
                      stroke={BLUE_HEX}
                      dot={false}
                      strokeWidth={1.6}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-between items-center pt-space-xs font-label-data text-label-caps text-outline">
                <span className="text-primary">{redName}</span>
                <span>{scope === "all" ? "Full Recording" : `Round ${scope + 1}`}</span>
                <span className="text-secondary">{blueName}</span>
              </div>
            </div>
          </div>

          {/* Defensive Biomechanics & Evasion */}
          <div className="bg-surface-container p-space-lg rounded-xl shadow-md">
            <div className="flex items-center justify-between mb-space-md">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-secondary">security</span>
                <h2 className="font-headline-sm text-headline-sm text-on-surface m-0">
                  Defensive Biomechanics &amp; Evasion
                </h2>
              </div>
              <span className="font-label-caps text-label-caps text-outline uppercase">Bell-to-Bell Trackers</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md text-on-surface">
              <div className="bg-surface-container-low p-space-sm rounded-lg flex flex-col justify-between">
                <span className="font-label-caps text-label-caps text-outline">HIGH GUARD RETENTION</span>
                <div className="my-space-xs">
                  <div className="flex justify-between items-baseline">
                    <span className="font-telemetry-metric-md text-primary font-bold">
                      {pctPts(redDef?.guard_up_percent)}
                    </span>
                    <span className="font-telemetry-metric-md text-secondary font-bold">
                      {pctPts(blueDef?.guard_up_percent)}
                    </span>
                  </div>
                  <span className="font-label-data text-body-sm text-outline block mt-0.5">Both gloves in box</span>
                </div>
                <div className="w-full bg-surface-container-lowest h-1.5 rounded-full overflow-hidden flex">
                  <div
                    className="bg-primary-container h-full"
                    style={{
                      width: `${splitShare(redDef?.guard_up_percent, blueDef?.guard_up_percent)[0]}%`,
                    }}
                  />
                  <div
                    className="bg-secondary h-full"
                    style={{
                      width: `${splitShare(redDef?.guard_up_percent, blueDef?.guard_up_percent)[1]}%`,
                    }}
                  />
                </div>
              </div>

              <div className="bg-surface-container-low p-space-sm rounded-lg flex flex-col justify-between">
                <span className="font-label-caps text-label-caps text-outline">MEDIAN LATERAL SLIP</span>
                <div className="my-space-xs">
                  <div className="flex justify-between items-baseline">
                    <span className="font-telemetry-metric-md text-primary font-bold">
                      {num(redDef?.head_movement.head_lateral_slip_m.median, 2)} m
                    </span>
                    <span className="font-telemetry-metric-md text-secondary font-bold">
                      {num(blueDef?.head_movement.head_lateral_slip_m.median, 2)} m
                    </span>
                  </div>
                  <span className="font-label-data text-body-sm text-outline block mt-0.5">
                    p90: {num(redDef?.head_movement.head_lateral_slip_m.p90, 2)}m vs{" "}
                    {num(blueDef?.head_movement.head_lateral_slip_m.p90, 2)}m
                  </span>
                </div>
                <div className="w-full bg-surface-container-lowest h-1.5 rounded-full overflow-hidden flex">
                  <div
                    className="bg-primary-container h-full"
                    style={{
                      width: `${
                        splitShare(
                          redDef?.head_movement.head_lateral_slip_m.p90,
                          blueDef?.head_movement.head_lateral_slip_m.p90,
                        )[0]
                      }%`,
                    }}
                  />
                  <div
                    className="bg-secondary h-full"
                    style={{
                      width: `${
                        splitShare(
                          redDef?.head_movement.head_lateral_slip_m.p90,
                          blueDef?.head_movement.head_lateral_slip_m.p90,
                        )[1]
                      }%`,
                    }}
                  />
                </div>
              </div>

              <div className="bg-surface-container-low p-space-sm rounded-lg flex flex-col justify-between">
                <span className="font-label-caps text-label-caps text-outline">DUCKS / BOB-WEAVES</span>
                <div className="my-space-xs">
                  <div className="flex justify-between items-baseline">
                    <span className="font-telemetry-metric-md text-primary font-bold">
                      {redDef?.head_movement.duck_count ?? 0} / {redDef?.head_movement.bob_and_weave_count ?? 0}
                    </span>
                    <span className="font-telemetry-metric-md text-secondary font-bold">
                      {blueDef?.head_movement.duck_count ?? 0} / {blueDef?.head_movement.bob_and_weave_count ?? 0}
                    </span>
                  </div>
                  <span className="font-label-data text-body-sm text-outline block mt-0.5">Ducks / U-shape weaves</span>
                </div>
                <div className="w-full bg-surface-container-lowest h-1.5 rounded-full overflow-hidden flex">
                  <div
                    className="bg-primary-container h-full"
                    style={{
                      width: `${
                        splitShare(
                          (redDef?.head_movement.duck_count ?? 0) + (redDef?.head_movement.bob_and_weave_count ?? 0),
                          (blueDef?.head_movement.duck_count ?? 0) + (blueDef?.head_movement.bob_and_weave_count ?? 0),
                        )[0]
                      }%`,
                    }}
                  />
                  <div
                    className="bg-secondary h-full"
                    style={{
                      width: `${
                        splitShare(
                          (redDef?.head_movement.duck_count ?? 0) + (redDef?.head_movement.bob_and_weave_count ?? 0),
                          (blueDef?.head_movement.duck_count ?? 0) + (blueDef?.head_movement.bob_and_weave_count ?? 0),
                        )[1]
                      }%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT 5 COLS */}
        <div className="xl:col-span-5 flex flex-col space-y-space-lg">
          {/* Punishment Combinations Highlight Pod */}
          <div className="bg-surface-container p-space-lg rounded-xl shadow-md flex flex-col">
            <div className="flex items-center justify-between mb-space-md gap-2">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-tertiary">bolt</span>
                <h2 className="font-headline-sm text-headline-sm text-on-surface m-0">Punishment Combinations</h2>
              </div>
              <div className="flex items-center bg-surface-container-lowest p-0.5 rounded gap-1">
                <button
                  type="button"
                  onClick={() => setComboCorner("red")}
                  className={`font-label-caps text-label-caps px-space-xs py-0.5 rounded font-bold transition-colors ${
                    comboCorner === "red" ? "bg-on-primary-container text-primary" : "text-outline hover:text-on-surface"
                  }`}
                >
                  RED
                </button>
                <button
                  type="button"
                  onClick={() => setComboCorner("blue")}
                  className={`font-label-caps text-label-caps px-space-xs py-0.5 rounded font-bold transition-colors ${
                    comboCorner === "blue"
                      ? "bg-on-secondary-container text-secondary"
                      : "text-outline hover:text-on-surface"
                  }`}
                >
                  BLUE
                </button>
              </div>
            </div>

            <div className="space-y-space-sm">
              {topCombos.length === 0 && (
                <p className="font-label-data text-outline py-2">No multi-punch sequences recorded in this slice.</p>
              )}
              {topCombos.map((combo, idx) => {
                const tokens = combo.pattern.split("-");
                const totalDelta = (combo.mean_punishment_delta ?? 0) * combo.count;
                return (
                  <div
                    key={combo.pattern}
                    className="bg-surface-container-low p-space-sm rounded-lg flex flex-col gap-1.5 hover:bg-surface-container-high transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-label-caps text-label-caps text-tertiary font-bold tracking-wider">
                        RANK #{idx + 1} · {combo.count}× THROWN
                      </span>
                      <span className="font-label-data text-body-sm text-on-surface font-semibold">
                        {num(combo.mean_punishment_delta, 2)} mean Δ ({num(totalDelta, 1)} sum)
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1 text-on-surface font-label-data text-label-data">
                      {tokens.map((tok, i) => (
                        <span key={`${tok}-${i}`} className="inline-flex items-center gap-1">
                          {i > 0 && <span className="text-outline">→</span>}
                          <span
                            className={`bg-surface-container-lowest px-1.5 py-0.5 rounded ${
                              comboCorner === "red" ? "text-primary" : "text-secondary"
                            }`}
                          >
                            {formatTokenLabel(tok)}
                          </span>
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center justify-between font-label-data text-label-caps text-outline pt-1">
                      <span>
                        Sequence Accuracy: {pct(combo.accuracy)} ({combo.landed}/{combo.thrown})
                      </span>
                      <span>
                        {combo.mean_speed != null ? `${num(combo.mean_speed, 2)} m/s` : "Speed n/a"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Filterable Key Telemetry Events */}
          <div className="bg-surface-container p-space-lg rounded-xl shadow-md flex flex-col flex-1">
            <div className="flex items-center justify-between mb-space-sm">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-primary">sensors</span>
                <h2 className="font-headline-sm text-headline-sm text-on-surface m-0">Key Telemetry Events</h2>
              </div>
              <span className="font-label-caps text-label-caps text-outline uppercase">
                {keyMoments.length} Events
              </span>
            </div>

            <div className="flex items-center gap-1.5 overflow-x-auto pb-space-sm">
              {momentTypes.map((type) => {
                const count = type === "all" ? keyMoments.length : (momentCounts.get(type) ?? 0);
                const active = momentFilter === type;
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setMomentFilter(type)}
                    className={`px-2 py-0.5 rounded font-label-caps text-label-caps whitespace-nowrap transition-colors ${
                      active
                        ? "bg-surface-container-high text-primary"
                        : "bg-surface-container-lowest text-outline hover:text-on-surface"
                    }`}
                  >
                    {type.replaceAll("_", " ")} ({count})
                  </button>
                );
              })}
            </div>

            <div className="space-y-space-xs font-label-data text-label-data max-h-80 overflow-y-auto pr-1">
              {filteredMoments.length === 0 && (
                <p className="text-outline py-4 text-center">No events match this filter.</p>
              )}
              {filteredMoments.map((m, idx) => {
                const singleColor = m.corners.length === 1 ? cornerColor(m.corners[0]) : null;
                return (
                  <div
                    key={`${m.tick}-${m.type}-${idx}`}
                    className="p-space-xs bg-surface-container-low rounded flex items-center justify-between gap-2 hover:bg-surface-container-high transition-colors"
                  >
                    <div className="flex items-center gap-space-sm min-w-0">
                      <span className="text-outline shrink-0">
                        {roundTimestampLabel(report, m.t_sec, scope)}
                      </span>
                      <span
                        className={`px-1 rounded text-label-caps font-bold shrink-0 ${
                          singleColor === "red"
                            ? "bg-on-primary-container text-primary"
                            : singleColor === "blue"
                              ? "bg-on-secondary-container text-secondary"
                              : "bg-surface-container-highest text-tertiary"
                        }`}
                      >
                        {singleColor === "red" ? "RED" : singleColor === "blue" ? "BLU" : "BOTH"}
                      </span>
                      <span className="text-on-surface truncate capitalize">{m.type.replaceAll("_", " ")}</span>
                    </div>
                    <span className="text-outline text-[11px] text-right shrink-0">
                      {formatMomentDetail(m.detail)}
                    </span>
                  </div>
                );
              })}
            </div>

            <button
              type="button"
              onClick={() => onNavigate("punch-log")}
              className="mt-space-md w-full py-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface rounded font-label-data text-label-data flex items-center justify-center gap-space-xs transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">list_alt</span>
              Open Complete Punch-by-Punch Stream ({totalPunchRecords} Records)
            </button>
          </div>
        </div>
      </div>

      {/* COLLAPSIBLE MEASUREMENT & METHODOLOGY DRAWER */}
      <div className="bg-surface-container-low rounded-xl p-space-md shadow-sm">
        <details className="group cursor-pointer">
          <summary className="flex items-center justify-between list-none">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-outline text-[18px]">verified</span>
              <span className="font-headline-sm text-body-md font-semibold text-on-surface">
                Measurement Methodology &amp; Data Confidence Registry ({report.decode_status.length} notes)
              </span>
            </div>
            <span className="material-symbols-outlined text-outline group-open:rotate-180 transition-transform duration-200">
              expand_more
            </span>
          </summary>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-space-md mt-space-md pt-space-sm border-t border-surface-variant/40 font-label-data text-label-data">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-secondary" />
                <span className="text-secondary font-bold font-label-caps text-label-caps">
                  CONFIRMED ({confirmedNotes.length})
                </span>
              </div>
              {confirmedNotes.map((n) => (
                <div key={n.field} className="bg-surface-container p-space-xs rounded">
                  <span className="text-on-surface font-semibold block">{n.field}</span>
                  <span className="text-outline text-body-sm leading-relaxed">{n.note}</span>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-tertiary" />
                <span className="text-tertiary font-bold font-label-caps text-label-caps">
                  INFERRED ({inferredNotes.length})
                </span>
              </div>
              <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
                {inferredNotes.map((n) => (
                  <div key={n.field} className="bg-surface-container p-space-xs rounded">
                    <span className="text-on-surface font-semibold block">{n.field}</span>
                    <span className="text-outline text-body-sm leading-relaxed">{n.note}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-outline" />
                <span className="text-outline font-bold font-label-caps text-label-caps">
                  UNAVAILABLE ({unavailNotes.length})
                </span>
              </div>
              {unavailNotes.length === 0 ? (
                <p className="text-outline text-body-sm">All expected channels decoded for this session.</p>
              ) : (
                unavailNotes.map((n) => (
                  <div key={n.field} className="bg-surface-container p-space-xs rounded">
                    <span className="text-on-surface font-semibold block">{n.field}</span>
                    <span className="text-outline text-body-sm leading-relaxed">{n.note}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </details>
      </div>
    </div>
  );
}
