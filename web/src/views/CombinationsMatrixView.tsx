import { useMemo, useState } from "react";
import type { FightAnalytics } from "../types";
import {
  type ScopeSelection,
  clampPct,
  clockWhole,
  cornerColor,
  formatTokenLabel,
  getFighter,
  getScopeData,
  num,
  pct,
  pctPts,
  roundTimestampLabel,
  splitShare,
} from "../utils";

const DEPTHS = ["1", "2", "3", "4", "5+"] as const;
const DEPTH_NAMES: Record<string, string> = {
  "1": "D1: Entry",
  "2": "D2: Follow-up",
  "3": "D3: Extension",
  "4": "D4: Over-ext",
  "5+": "D5+: Flurry",
};

type PatternSort = "punishment" | "accuracy" | "volume";

type SequencedCombo = {
  key: string;
  corner: number;
  color: "red" | "blue";
  tSec: number;
  tokens: string[];
  landedFlags: boolean[];
  thrown: number;
  landed: number;
  peakSpeed: number | null;
  punishmentSum: number;
  counteredAny: boolean;
};

function buildComboInstances(offenseList: FightAnalytics["offense"]): SequencedCombo[] {
  const result: SequencedCombo[] = [];
  for (const off of offenseList) {
    const color = cornerColor(off.corner);
    const groups = new Map<number, typeof off.punches>();
    for (const p of off.punches) {
      if (p.hand === "unmatched" || p.combo_id == null) continue;
      const list = groups.get(p.combo_id) ?? [];
      list.push(p);
      groups.set(p.combo_id, list);
    }
    for (const [cid, punches] of groups.entries()) {
      const ordered = [...punches].sort((a, b) => (a.launch_sec ?? a.t_sec) - (b.launch_sec ?? b.t_sec));
      const first = ordered[0];
      const tokens = ordered.map((p) => {
        if (["jab", "cross", "left_hook", "right_hook"].includes(p.trajectory)) return p.trajectory;
        if (p.hand === "left" || p.hand === "right") return `${p.hand}_${p.trajectory}`;
        return p.trajectory;
      });
      const speeds = ordered.map((p) => p.speed).filter((s): s is number => s != null);
      const punishmentSum = ordered.reduce(
        (acc, p) => acc + (p.landed && p.punishment_delta != null ? p.punishment_delta : 0),
        0,
      );
      result.push({
        key: `${off.corner}-${cid}-${first.t_sec}`,
        corner: off.corner,
        color,
        tSec: first.launch_sec ?? first.t_sec,
        tokens,
        landedFlags: ordered.map((p) => p.landed),
        thrown: ordered.length,
        landed: ordered.filter((p) => p.landed).length,
        peakSpeed: speeds.length ? Math.max(...speeds) : null,
        punishmentSum,
        counteredAny: ordered.some((p) => p.countered),
      });
    }
  }
  return result.sort((a, b) => a.tSec - b.tSec);
}

export function CombinationsMatrixView({
  report,
  scope,
  onSelectScope,
}: {
  report: FightAnalytics;
  scope: ScopeSelection;
  onSelectScope: (next: ScopeSelection) => void;
}) {
  const [sortBy, setSortBy] = useState<PatternSort>("punishment");
  const [searchQuery, setSearchQuery] = useState("");
  const [fighterFilter, setFighterFilter] = useState<"all" | "red" | "blue">("all");
  const [outcomeFilter, setOutcomeFilter] = useState<"all" | "landed" | "countered" | "high_punish">("all");
  const [page, setPage] = useState(1);

  const red = getFighter(report, "red");
  const blue = getFighter(report, "blue");
  const redName = red?.name ?? "Red";
  const blueName = blue?.name ?? "Blue";

  const { completedRounds, offense, redOff, blueOff, redDef, blueDef } = getScopeData(report, scope);
  const redCombos = redOff?.combinations;
  const blueCombos = blueOff?.combinations;
  const redVuln = redDef?.vulnerability;
  const blueVuln = blueDef?.vulnerability;

  const [chainShareRed, chainShareBlue] = splitShare(redCombos?.combo_count, blueCombos?.combo_count);
  const [altShareRed, altShareBlue] = splitShare(
    redCombos?.alternating_hand_percent,
    blueCombos?.alternating_hand_percent,
  );

  // Funnel SVG points across depths 1..5+
  const maxDepthThrown = Math.max(
    1,
    ...(redCombos?.by_depth.map((d) => d.thrown) ?? [1]),
    ...(blueCombos?.by_depth.map((d) => d.thrown) ?? [1]),
  );
  const xCoords = [60, 230, 400, 570, 740];
  const redPolyPoints = DEPTHS.map((d, i) => {
    const val = redCombos?.by_depth.find((x) => x.depth === d)?.thrown ?? 0;
    const y = 115 - (val / maxDepthThrown) * 95;
    return `${xCoords[i]},${y.toFixed(1)}`;
  }).join(" ");
  const bluePolyPoints = DEPTHS.map((d, i) => {
    const val = blueCombos?.by_depth.find((x) => x.depth === d)?.thrown ?? 0;
    const y = 115 - (val / maxDepthThrown) * 95;
    return `${xCoords[i]},${y.toFixed(1)}`;
  }).join(" ");

  // Merged pattern cards (both corners)
  const patternCards = useMemo(() => {
    const cards = [
      ...(redCombos?.patterns.map((p) => ({ ...p, color: "red" as const, fighterName: redName })) ?? []),
      ...(blueCombos?.patterns.map((p) => ({ ...p, color: "blue" as const, fighterName: blueName })) ?? []),
    ].filter((p) => p.count >= 2 || (p.mean_punishment_delta ?? 0) > 5);

    return cards
      .sort((a, b) => {
        if (sortBy === "punishment") {
          return (b.mean_punishment_delta ?? 0) - (a.mean_punishment_delta ?? 0) || b.count - a.count;
        }
        if (sortBy === "accuracy") {
          return (b.accuracy ?? 0) - (a.accuracy ?? 0) || b.count - a.count;
        }
        return b.count - a.count || b.landed - a.landed;
      })
      .slice(0, 6);
  }, [redCombos, blueCombos, redName, blueName, sortBy]);

  // Sequence instances log
  const allInstances = useMemo(() => buildComboInstances(offense), [offense]);
  const filteredInstances = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return allInstances.filter((item) => {
      if (fighterFilter !== "all" && item.color !== fighterFilter) return false;
      if (outcomeFilter === "landed" && item.landed === 0) return false;
      if (outcomeFilter === "countered" && !item.counteredAny) return false;
      if (outcomeFilter === "high_punish" && item.punishmentSum < 8) return false;
      if (q) {
        const text = item.tokens.map(formatTokenLabel).join(" ").toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }, [allInstances, fighterFilter, outcomeFilter, searchQuery]);

  const pageSize = 15;
  const totalPages = Math.max(1, Math.ceil(filteredInstances.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = filteredInstances.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      {/* TOP BREADCRUMB & METRIC CONTROLS BAR */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md bg-surface-container-low p-space-md rounded-lg shadow-sm">
        <div className="flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-sm font-label-caps text-label-caps tracking-widest text-outline flex-wrap">
            <span className="inline-flex items-center gap-1 text-secondary">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
              SYS.DIAGNOSTICS // COMBO ENGINE
            </span>
            <span className="text-surface-variant">/</span>
            <span className="text-primary-container">MODULE 03</span>
            <span className="text-surface-variant">/</span>
            <span className="text-on-surface uppercase">Combinations Matrix &amp; Strike Telemetry</span>
          </div>
          <div className="flex items-center gap-space-sm flex-wrap">
            <span className="font-headline-sm text-headline-sm uppercase tracking-tight text-on-surface">
              Sequence Depth, Accuracy Decay &amp; Counter Windows
            </span>
            <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container text-tertiary">
              GAP THRESHOLD 0.65s
            </span>
          </div>
        </div>

        <div className="flex items-center bg-surface-container-lowest p-space-xs rounded flex-wrap gap-1">
          <button
            type="button"
            onClick={() => {
              onSelectScope("all");
              setPage(1);
            }}
            className={`px-space-sm py-space-xs rounded font-label-data text-label-data transition-colors ${
              scope === "all"
                ? "bg-surface-bright text-on-surface font-semibold"
                : "text-outline hover:text-on-surface"
            }`}
          >
            Full Bout
          </button>
          {completedRounds.map((r) => (
            <button
              key={r.index}
              type="button"
              onClick={() => {
                onSelectScope(r.index);
                setPage(1);
              }}
              className={`px-space-sm py-space-xs rounded font-label-data text-label-data transition-colors ${
                scope === r.index
                  ? "bg-surface-bright text-on-surface font-semibold"
                  : "text-outline hover:text-on-surface"
              }`}
            >
              R{r.index + 1} ({clockWhole(r.duration_sec)})
            </button>
          ))}
        </div>
      </div>

      {/* PRIMARY STRIKING KPI COMPARISON CARDS (5 Core Tiles) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-space-md">
        {/* KPI 1: Total Chains */}
        <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
            <span>TOTAL CHAINS</span>
          </div>
          <div className="flex items-baseline justify-between mb-space-sm">
            <div className="flex items-baseline gap-1">
              <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary">
                {redCombos?.combo_count ?? 0}
              </span>
              <span className="font-label-caps text-label-caps text-primary/70">RED</span>
            </div>
            <span className="font-label-data text-label-data text-surface-variant font-bold">vs</span>
            <div className="flex items-baseline gap-1">
              <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-secondary">
                {blueCombos?.combo_count ?? 0}
              </span>
              <span className="font-label-caps text-label-caps text-secondary/70">BLU</span>
            </div>
          </div>
          <div className="w-full bg-surface-container-lowest h-1.5 rounded-full flex overflow-hidden">
            <div className="bg-primary-container h-full" style={{ width: `${chainShareRed}%` }} />
            <div className="bg-secondary h-full" style={{ width: `${chainShareBlue}%` }} />
          </div>
          <div className="flex justify-between items-center mt-space-xs font-label-data text-label-data text-outline">
            <span>{chainShareRed.toFixed(1)}% share</span>
            <span>{chainShareBlue.toFixed(1)}% share</span>
          </div>
        </div>

        {/* KPI 2: Mean Chain Depth */}
        <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
            <span>MEAN CHAIN DEPTH</span>
          </div>
          <div className="flex items-baseline justify-between mb-space-sm">
            <div className="flex items-baseline gap-1">
              <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary">
                {num(redCombos?.mean_combo_length, 2)}
              </span>
              <span className="font-label-data text-label-data text-outline">p</span>
            </div>
            <span className="font-label-data text-label-data text-surface-variant font-bold">vs</span>
            <div className="flex items-baseline gap-1">
              <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-secondary">
                {num(blueCombos?.mean_combo_length, 2)}
              </span>
              <span className="font-label-data text-label-data text-outline">p</span>
            </div>
          </div>
          <div className="flex justify-between font-label-caps text-label-caps text-outline bg-surface-container-lowest px-space-xs py-0.5 rounded">
            <span>
              MAX RED: <b className="text-primary font-bold">{redCombos?.max_combo_length ?? 0}×</b>
            </span>
            <span>
              MAX BLU: <b className="text-secondary font-bold">{blueCombos?.max_combo_length ?? 0}×</b>
            </span>
          </div>
        </div>

        {/* KPI 3: Alternating Hand Flow */}
        <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
            <span>ALT-HAND FLOW</span>
          </div>
          <div className="flex items-baseline justify-between mb-space-sm">
            <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary">
              {pctPts(redCombos?.alternating_hand_percent)}
            </span>
            <span className="font-label-data text-label-data text-surface-variant font-bold">vs</span>
            <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-secondary">
              {pctPts(blueCombos?.alternating_hand_percent)}
            </span>
          </div>
          <div className="w-full bg-surface-container-lowest h-1.5 rounded-full flex overflow-hidden">
            <div className="bg-primary-container h-full" style={{ width: `${altShareRed}%` }} />
            <div className="bg-secondary h-full" style={{ width: `${altShareBlue}%` }} />
          </div>
          <span className="font-label-data text-label-data text-outline mt-space-xs">
            Multi-punch strict L↔R share
          </span>
        </div>

        {/* KPI 4: Single-Shot Share */}
        <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
            <span>SINGLE-SHOT SHARE</span>
          </div>
          <div className="flex items-baseline justify-between mb-space-sm">
            <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary">
              {pctPts(redCombos?.single_shot_percent)}
            </span>
            <span className="font-label-data text-label-data text-surface-variant font-bold">vs</span>
            <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-secondary">
              {pctPts(blueCombos?.single_shot_percent)}
            </span>
          </div>
          <div className="font-label-data text-label-data text-outline bg-surface-container-lowest px-space-xs py-0.5 rounded text-center">
            <span>Share of 1-punch groups</span>
          </div>
        </div>

        {/* KPI 5: Mean Landed Velocity */}
        <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
            <span>MEAN LANDED SPEED</span>
            {redOff?.velocity.max_speed != null && (
              <span className="text-tertiary font-label-data">MAX {num(redOff.velocity.max_speed, 2)}</span>
            )}
          </div>
          <div className="flex items-baseline justify-between mb-space-sm">
            <div className="flex items-baseline gap-1">
              <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-on-surface">
                {num(redOff?.velocity.mean_landed, 2)}
              </span>
              <span className="font-label-caps text-label-caps text-outline">m/s</span>
            </div>
            <div className="flex flex-col text-right">
              <span className="font-label-caps text-label-caps text-secondary">BLU MEAN</span>
              <span className="font-label-data text-label-data text-outline">
                {blueOff?.velocity.mean_landed != null ? `${num(blueOff.velocity.mean_landed, 2)} m/s` : "n/a (AI)"}
              </span>
            </div>
          </div>
          <span className="font-label-data text-label-data text-outline">
            Kinematic samples: {redOff?.velocity.samples ?? 0}R · {blueOff?.velocity.samples ?? 0}B
          </span>
        </div>
      </div>

      {/* SECTION 2: COMBINATION DEPTH & DECAY FUNNEL */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        <div className="xl:col-span-8 bg-surface-container-low rounded-lg p-space-lg flex flex-col gap-space-md shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-xs pb-space-sm border-b border-surface-variant/40">
            <div>
              <div className="flex items-center gap-space-xs">
                <span className="font-headline-sm text-headline-sm text-on-surface">
                  Combination Depth &amp; Kinetic Decay Funnel
                </span>
                <span className="bg-surface-container text-secondary text-label-caps font-label-caps px-space-xs py-0.5 rounded">
                  DEPTH 1 → 5+
                </span>
              </div>
              <p className="font-body-sm text-body-sm text-outline m-0 mt-0.5">
                Volume throughput, strike accuracy, mean speed, and countered rate by sequence position.
              </p>
            </div>
            <div className="flex items-center gap-space-md font-label-caps text-label-caps">
              <span className="flex items-center gap-1 text-primary">
                <span className="w-2 h-2 rounded-full bg-primary-container" />
                {redName} (RED)
              </span>
              <span className="flex items-center gap-1 text-secondary">
                <span className="w-2 h-2 rounded-full bg-secondary" />
                {blueName} (BLU)
              </span>
            </div>
          </div>

          <div className="bg-surface-container-lowest p-space-md rounded-md flex flex-col gap-space-sm">
            <svg className="w-full h-32" fill="none" preserveAspectRatio="none" viewBox="0 0 800 130">
              {[20, 55, 90, 120].map((y) => (
                <line
                  key={y}
                  x1="0"
                  y1={y}
                  x2="800"
                  y2={y}
                  stroke="#31353d"
                  strokeDasharray="3 3"
                  strokeWidth="0.6"
                />
              ))}
              <polyline
                points={redPolyPoints}
                stroke="#ff5451"
                strokeLinecap="round"
                strokeWidth="2.5"
                fill="none"
              />
              <polyline
                points={bluePolyPoints}
                stroke="#4cd7f6"
                strokeLinecap="round"
                strokeDasharray="4 2"
                strokeWidth="2"
                fill="none"
              />
              {DEPTHS.map((d, i) => {
                const rVal = redCombos?.by_depth.find((x) => x.depth === d)?.thrown ?? 0;
                const bVal = blueCombos?.by_depth.find((x) => x.depth === d)?.thrown ?? 0;
                const ry = 115 - (rVal / maxDepthThrown) * 95;
                const by = 115 - (bVal / maxDepthThrown) * 95;
                return (
                  <g key={d}>
                    <circle cx={xCoords[i]} cy={ry} r="4" fill="#ff5451" />
                    <circle cx={xCoords[i]} cy={by} r="3.5" fill="#4cd7f6" />
                  </g>
                );
              })}
            </svg>
            <div className="grid grid-cols-5 text-center font-label-caps text-label-caps text-outline pt-1">
              {DEPTHS.map((d) => (
                <div key={d}>DEPTH {d}</div>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-label-data text-label-data border-collapse">
              <thead>
                <tr className="bg-surface-container-high/60 text-outline font-label-caps text-label-caps">
                  <th className="p-space-sm">STAGE</th>
                  <th className="p-space-sm">THROWN (R / B)</th>
                  <th className="p-space-sm">ACCURACY (R / B)</th>
                  <th className="p-space-sm">MEAN SPEED (R / B)</th>
                  <th className="p-space-sm">COUNTERED RATE (R / B)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container-highest/30">
                {DEPTHS.map((d) => {
                  const rD = redCombos?.by_depth.find((x) => x.depth === d);
                  const bD = blueCombos?.by_depth.find((x) => x.depth === d);
                  return (
                    <tr key={d} className="hover:bg-surface-container transition-colors">
                      <td className="p-space-sm font-semibold text-on-surface">
                        <span className="px-space-xs py-0.5 rounded bg-surface-container-highest text-primary">
                          {DEPTH_NAMES[d]}
                        </span>
                      </td>
                      <td className="p-space-sm">
                        <span className="text-primary font-bold">{rD?.thrown ?? 0}</span>{" "}
                        <span className="text-outline">/</span>{" "}
                        <span className="text-secondary font-bold">{bD?.thrown ?? 0}</span>
                      </td>
                      <td className="p-space-sm">
                        <div className="flex items-center gap-2">
                          <span className="text-primary font-bold">{pct(rD?.accuracy)}</span>
                          <div className="w-14 bg-surface-container-highest h-1 rounded overflow-hidden">
                            <div
                              className="bg-primary-container h-full"
                              style={{ width: `${clampPct((rD?.accuracy ?? 0) * 100)}%` }}
                            />
                          </div>
                          <span className="text-secondary font-medium">{pct(bD?.accuracy)}</span>
                        </div>
                      </td>
                      <td className="p-space-sm text-on-surface">
                        {num(rD?.mean_speed, 2)} / {num(bD?.mean_speed, 2)} m/s
                      </td>
                      <td className="p-space-sm">
                        <span className="text-tertiary">{pct(rD?.countered_rate)}</span>{" "}
                        <span className="text-outline">vs</span>{" "}
                        <span className="text-error font-bold">{pct(bD?.countered_rate)}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right 4 cols: Summary Telemetry Readout */}
        <div className="xl:col-span-4 flex flex-col gap-space-md">
          <div className="bg-surface-container-low rounded-lg p-space-lg flex flex-col gap-space-sm shadow-sm">
            <div className="flex items-center gap-space-xs text-tertiary font-label-caps text-label-caps">
              <span className="material-symbols-outlined text-[18px]">verified</span>
              <span>COUNTER EXPOSURE SUMMARY</span>
            </div>
            <div className="font-headline-sm text-headline-sm text-on-surface leading-tight">
              Depth-1 Entry Counter Rates
            </div>
            <p className="font-body-md text-body-md text-on-surface-variant m-0">
              On initiating strikes (Depth 1), <strong className="text-primary">{redName}</strong> was countered on{" "}
              <span className="font-label-data text-on-surface">
                {pct(redCombos?.by_depth.find((d) => d.depth === "1")?.countered_rate)}
              </span>{" "}
              of launches, while <strong className="text-secondary">{blueName}</strong> was countered on{" "}
              <span className="font-label-data text-on-surface">
                {pct(blueCombos?.by_depth.find((d) => d.depth === "1")?.countered_rate)}
              </span>
              .
            </p>
            <div className="bg-surface-container-lowest p-space-sm rounded mt-space-xs flex flex-col gap-space-xs">
              <div className="flex items-center justify-between font-label-caps text-label-caps">
                <span className="text-outline">TOTAL COUNTERED LAUNCHES</span>
                <span className="text-on-surface font-bold">
                  {redCombos?.by_depth.reduce((acc, d) => acc + d.countered_count, 0) ?? 0}R ·{" "}
                  {blueCombos?.by_depth.reduce((acc, d) => acc + d.countered_count, 0) ?? 0}B
                </span>
              </div>
              <div className="w-full bg-surface-container h-1.5 rounded-full overflow-hidden flex">
                {(() => {
                  const rC = redCombos?.by_depth.reduce((acc, d) => acc + d.countered_count, 0) ?? 0;
                  const bC = blueCombos?.by_depth.reduce((acc, d) => acc + d.countered_count, 0) ?? 0;
                  const [sR, sB] = splitShare(rC, bC);
                  return (
                    <>
                      <div className="bg-primary-container h-full" style={{ width: `${sR}%` }} />
                      <div className="bg-error h-full" style={{ width: `${sB}%` }} />
                    </>
                  );
                })()}
              </div>
            </div>
          </div>

          <div className="bg-surface-container-low rounded-lg p-space-md flex flex-col justify-between shadow-sm flex-1">
            <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
              <span>HEAD-SLIP OFFSET AT LAUNCH</span>
              <span className="text-secondary font-label-data">MEDIAN PUNCH LAUNCH</span>
            </div>
            <div className="flex items-center justify-around py-space-sm">
              <div className="flex flex-col items-center">
                <span className="font-label-caps text-label-caps text-primary">{redName}</span>
                <span className="font-telemetry-metric-md text-on-surface">
                  {pctPts(redDef?.head_movement.off_centerline_while_punching_percent)}
                </span>
                <span className="font-label-data text-label-data text-outline">Off-center punching</span>
              </div>
              <div className="w-px h-10 bg-surface-variant" />
              <div className="flex flex-col items-center">
                <span className="font-label-caps text-label-caps text-secondary">{blueName}</span>
                <span className="font-telemetry-metric-md text-on-surface">
                  {pctPts(blueDef?.head_movement.off_centerline_while_punching_percent)}
                </span>
                <span className="font-label-data text-label-data text-outline">Off-center punching</span>
              </div>
            </div>
            <div className="bg-surface-container-lowest p-space-xs rounded text-center font-label-data text-label-data text-outline">
              Lateral slip &ge; 0.10m during launch-to-end interval
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 3: SEQUENCE SIGNATURE MATRIX */}
      <div className="bg-surface-container-low rounded-lg p-space-lg shadow-sm flex flex-col gap-space-md">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-xs pb-space-sm border-b border-surface-variant/40">
          <div>
            <div className="flex items-center gap-space-xs">
              <span className="font-headline-sm text-headline-sm text-on-surface">
                Sequence Signature Matrix
              </span>
              <span className="bg-tertiary/20 text-tertiary text-label-caps font-label-caps px-space-xs py-0.5 rounded">
                PUNISHMENT CHANNELS 0+1
              </span>
            </div>
            <p className="font-body-sm text-body-sm text-outline m-0 mt-0.5">
              Mean punishment step is summed across landed punches per pattern instance (not official damage).
            </p>
          </div>
          <div className="flex items-center gap-space-xs">
            <span className="font-label-caps text-label-caps text-outline">SORT:</span>
            {(
              [
                ["punishment", "Punishment Δ"],
                ["accuracy", "Accuracy %"],
                ["volume", "Volume"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setSortBy(key)}
                className={`px-space-xs py-0.5 rounded font-label-data text-label-data transition-colors ${
                  sortBy === key
                    ? "bg-surface-bright text-on-surface font-semibold"
                    : "bg-surface-container text-outline hover:text-on-surface"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-md">
          {patternCards.map((card, idx) => {
            const tokens = card.pattern.split("-");
            const isRed = card.color === "red";
            return (
              <div
                key={`${card.color}-${card.pattern}`}
                className={`bg-surface-container-lowest p-space-md rounded-lg flex flex-col justify-between border-l-2 ${
                  isRed ? "border-primary-container" : "border-secondary"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-space-xs">
                    <span
                      className={`font-label-caps text-label-caps ${isRed ? "text-primary" : "text-secondary"}`}
                    >
                      {card.fighterName} // #{idx + 1}
                    </span>
                    <span className="bg-surface-container text-on-surface-variant font-label-caps text-label-caps px-space-xs py-0.5 rounded">
                      {card.length}-STRIKE
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap my-space-sm">
                    {tokens.map((tok, i) => (
                      <span key={`${tok}-${i}`} className="inline-flex items-center gap-1">
                        {i > 0 && <span className="text-outline text-[12px]">→</span>}
                        <span className="px-space-xs py-0.5 bg-surface-container text-on-surface font-label-data text-label-data rounded">
                          {formatTokenLabel(tok)}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
                <div className="pt-space-sm border-t border-surface-variant/30 flex flex-col gap-space-xs">
                  <div className="grid grid-cols-3 text-center">
                    <div>
                      <span className="block font-label-caps text-label-caps text-outline">COUNT</span>
                      <span className="font-telemetry-metric-sm text-on-surface">{card.count}×</span>
                    </div>
                    <div>
                      <span className="block font-label-caps text-label-caps text-outline">ACCURACY</span>
                      <span className={`font-telemetry-metric-sm ${isRed ? "text-primary" : "text-secondary"}`}>
                        {pct(card.accuracy)}
                      </span>
                    </div>
                    <div>
                      <span className="block font-label-caps text-label-caps text-outline">MEAN Δ</span>
                      <span className="font-telemetry-metric-sm text-tertiary">
                        {num(card.mean_punishment_delta, 2)}
                      </span>
                    </div>
                  </div>
                  <div className="bg-surface-container px-space-xs py-0.5 rounded text-center font-label-data text-label-data text-outline mt-1">
                    {card.landed}/{card.thrown} punches landed · {num(card.mean_punishment_delta_landed, 2)} Δ / landed
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* SECTION 4: VULNERABILITY & EXCHANGE TIMING WINDOWS */}
      <div className="bg-surface-container-low rounded-lg p-space-lg shadow-sm flex flex-col gap-space-md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-xs pb-space-sm border-b border-surface-variant/40">
          <div>
            <div className="flex items-center gap-space-xs">
              <span className="font-headline-sm text-headline-sm text-on-surface">
                Vulnerability &amp; Exchange Timing Windows
              </span>
              <span className="bg-surface-container text-tertiary text-label-caps font-label-caps px-space-xs py-0.5 rounded">
                3 DISCRETE STATES
              </span>
            </div>
            <p className="font-body-sm text-body-sm text-outline m-0 mt-0.5">
              Hit share, bell-to-bell time share, and risk ratio (hit share / time share) across launch windows.
            </p>
          </div>
          <div className="font-label-caps text-label-caps text-outline">
            THROW: <span className="text-secondary">±150ms</span> · RECOVERY: <span className="text-tertiary">600ms</span>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-space-md">
          {(
            [
              ["while_throwing", "1. While Throwing", "border-error", "±0.15s around own punch launch."],
              ["post_punch_recovery", "2. Punch Recovery", "border-tertiary", "0.15s–0.60s post-launch outside throwing."],
              ["neutral_guard", "3. Neutral Guard", "border-secondary", "All remaining bell-to-bell frames."],
            ] as const
          ).map(([key, title, borderCls, desc]) => {
            const rW = redVuln?.[key];
            const bW = blueVuln?.[key];
            return (
              <div
                key={key}
                className={`bg-surface-container-lowest p-space-md rounded-lg flex flex-col gap-space-sm border-t-2 ${borderCls}`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-headline-sm text-headline-sm text-on-surface">{title}</span>
                  <span className="font-label-caps text-label-caps text-outline">
                    Opp Acc: {pct(rW?.opponent_accuracy)} / {pct(bW?.opponent_accuracy)}
                  </span>
                </div>
                <p className="font-body-sm text-body-sm text-outline m-0">{desc}</p>
                <div className="space-y-space-sm pt-space-xs">
                  <div className="bg-surface-container p-space-sm rounded">
                    <div className="flex justify-between font-label-caps text-label-caps text-primary mb-1">
                      <span>{redName} (RED)</span>
                      <span>RISK RATIO: {num(rW?.risk_ratio, 2)}</span>
                    </div>
                    <div className="flex justify-between font-label-data text-label-data text-on-surface mb-1">
                      <span>{pctPts(rW?.hit_share)} hits taken ({rW?.hits ?? 0})</span>
                      <span className="text-outline">{pctPts(rW?.time_share)} time</span>
                    </div>
                    <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                      <div
                        className="bg-primary-container h-full"
                        style={{ width: `${clampPct(rW?.hit_share)}%` }}
                      />
                    </div>
                  </div>

                  <div className="bg-surface-container p-space-sm rounded">
                    <div className="flex justify-between font-label-caps text-label-caps text-secondary mb-1">
                      <span>{blueName} (BLUE)</span>
                      <span>RISK RATIO: {num(bW?.risk_ratio, 2)}</span>
                    </div>
                    <div className="flex justify-between font-label-data text-label-data text-on-surface mb-1">
                      <span>{pctPts(bW?.hit_share)} hits taken ({bW?.hits ?? 0})</span>
                      <span className="text-outline">{pctPts(bW?.time_share)} time</span>
                    </div>
                    <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                      <div className="bg-secondary h-full" style={{ width: `${clampPct(bW?.hit_share)}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* SECTION 5: INTERACTIVE COMBO FLOW EXPLORER */}
      <div className="bg-surface-container-low rounded-lg p-space-lg shadow-sm flex flex-col gap-space-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-space-md pb-space-sm border-b border-surface-variant/40">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-secondary text-[22px]">format_list_bulleted</span>
            <div>
              <span className="font-headline-sm text-headline-sm text-on-surface">Interactive Combo Flow Log</span>
              <span className="font-label-caps text-label-caps text-outline ml-space-xs">
                {filteredInstances.length} SEQUENCES
              </span>
            </div>
          </div>

          <div className="flex items-center gap-space-xs flex-wrap">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setPage(1);
                }}
                placeholder="Filter (e.g. Jab, Hook)..."
                className="bg-surface-container-lowest text-on-surface font-label-data text-label-data px-space-sm py-1.5 pl-7 rounded outline-none focus:ring-1 focus:ring-secondary w-52"
              />
              <span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-outline text-[14px]">
                search
              </span>
            </div>
            <select
              value={fighterFilter}
              onChange={(e) => {
                setFighterFilter(e.target.value as "all" | "red" | "blue");
                setPage(1);
              }}
              className="bg-surface-container-lowest text-on-surface font-label-data text-label-data px-space-sm py-1.5 rounded outline-none cursor-pointer"
            >
              <option value="all">All Fighters</option>
              <option value="red">{redName} (Red)</option>
              <option value="blue">{blueName} (Blue)</option>
            </select>
            <select
              value={outcomeFilter}
              onChange={(e) => {
                setOutcomeFilter(e.target.value as "all" | "landed" | "countered" | "high_punish");
                setPage(1);
              }}
              className="bg-surface-container-lowest text-on-surface font-label-data text-label-data px-space-sm py-1.5 rounded outline-none cursor-pointer"
            >
              <option value="all">All Outcomes</option>
              <option value="landed">At Least 1 Landed</option>
              <option value="high_punish">Punishment &ge; 8.0</option>
              <option value="countered">Countered Entries</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left font-label-data text-label-data border-collapse">
            <thead>
              <tr className="bg-surface-container-lowest text-outline font-label-caps text-label-caps">
                <th className="p-space-sm">TIME</th>
                <th className="p-space-sm">FIGHTER</th>
                <th className="p-space-sm">COMBINATION SEQUENCE</th>
                <th className="p-space-sm">LENGTH</th>
                <th className="p-space-sm">LANDED</th>
                <th className="p-space-sm">PEAK SPEED</th>
                <th className="p-space-sm text-right">PUNISHMENT Δ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container-highest/20">
              {pageRows.map((row) => (
                <tr key={row.key} className="hover:bg-surface-container transition-colors">
                  <td className="p-space-sm text-outline whitespace-nowrap">
                    {roundTimestampLabel(report, row.tSec, scope)}
                  </td>
                  <td className="p-space-sm">
                    <span
                      className={`px-space-xs py-0.5 rounded font-label-caps text-label-caps ${
                        row.color === "red"
                          ? "bg-on-primary-container text-primary-fixed"
                          : "bg-on-secondary-container text-secondary"
                      }`}
                    >
                      {row.color === "red" ? redName : blueName}
                    </span>
                  </td>
                  <td className="p-space-sm">
                    <div className="flex items-center gap-1 flex-wrap">
                      {row.tokens.map((tok, idx) => (
                        <span key={`${tok}-${idx}`} className="inline-flex items-center gap-1">
                          {idx > 0 && <span className="text-outline">→</span>}
                          <span
                            className={
                              row.landedFlags[idx]
                                ? "text-on-surface font-semibold"
                                : "text-outline line-through"
                            }
                          >
                            {formatTokenLabel(tok)}
                          </span>
                        </span>
                      ))}
                      {row.counteredAny && (
                        <span className="ml-1 px-1 py-0.5 rounded bg-error-container/50 text-error text-[10px] font-label-caps">
                          COUNTERED
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="p-space-sm text-on-surface">{row.thrown}-Hit</td>
                  <td className="p-space-sm">
                    <span className={row.landed > 0 ? "text-primary font-bold" : "text-outline"}>
                      {row.landed}/{row.thrown} ({Math.round((row.landed / row.thrown) * 100)}%)
                    </span>
                  </td>
                  <td className="p-space-sm text-on-surface">
                    {row.peakSpeed != null ? `${row.peakSpeed.toFixed(2)} m/s` : "—"}
                  </td>
                  <td className="p-space-sm text-right text-tertiary font-semibold">
                    {row.punishmentSum > 0 ? `+${row.punishmentSum.toFixed(2)}` : "0.00"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-xs pt-space-xs font-label-data text-label-data text-outline">
          <span>
            Showing {(safePage - 1) * pageSize + (pageRows.length ? 1 : 0)}–
            {(safePage - 1) * pageSize + pageRows.length} of {filteredInstances.length} combinations
          </span>
          <div className="flex items-center gap-space-xs">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright disabled:opacity-40 text-on-surface transition-colors"
            >
              Previous
            </button>
            <span className="px-space-sm py-1 rounded bg-surface-bright text-on-surface font-bold">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright disabled:opacity-40 text-on-surface transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
