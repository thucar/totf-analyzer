import { useEffect, useMemo, useState } from "react";
import type { FightAnalytics } from "../types";
import {
  type CornerColor,
  type ScopeSelection,
  clampPct,
  clockWhole,
  cornerColor,
  formatMomentDetail,
  getFighter,
  getFocalColor,
  getScopeData,
  num,
  pct,
  pctPts,
  roundTimestampLabel,
  seriesMean,
  splitShare,
} from "../utils";

type HeatmapLayer = "all" | "red" | "blue" | "trajectory";

function extractHipsPath(seriesList: FightAnalytics["series"], corner: number, ringSizeM: number) {
  const sx = seriesList.find((s) => s.name === "hips_x" && s.corner === corner);
  const sz = seriesList.find((s) => s.name === "hips_z" && s.corner === corner);
  if (!sx || !sz || sx.t.length === 0) return { cells: [] as { cx: number; cy: number; weight: number }[], path: "" };

  const half = Math.max(1.5, ringSizeM / 2);
  const mapCoord = (val: number) => 250 + Math.max(-200, Math.min(200, (val / half) * 200));

  const zByT = new Map<number, number>();
  sz.t.forEach((t, idx) => zByT.set(t, sz.y[idx]));

  const pts: { x: number; y: number }[] = [];
  sx.t.forEach((t, idx) => {
    const z = zByT.get(t);
    if (z != null) {
      pts.push({ x: mapCoord(sx.y[idx]), y: mapCoord(-z) });
    }
  });

  // Bin into 12x12 grid across [50, 450]
  const grid = new Map<string, { sumX: number; sumY: number; count: number }>();
  const step = 400 / 12;
  for (const p of pts) {
    const gx = Math.floor((p.x - 50) / step);
    const gy = Math.floor((p.y - 50) / step);
    const key = `${gx},${gy}`;
    const cell = grid.get(key) ?? { sumX: 0, sumY: 0, count: 0 };
    cell.sumX += p.x;
    cell.sumY += p.y;
    cell.count += 1;
    grid.set(key, cell);
  }
  const maxCount = Math.max(1, ...Array.from(grid.values()).map((c) => c.count));
  const cells = Array.from(grid.values())
    .sort((a, b) => b.count - a.count)
    .slice(0, 18)
    .map((c) => ({
      cx: c.sumX / c.count,
      cy: c.sumY / c.count,
      weight: c.count / maxCount,
    }));

  // Subsample trajectory polyline (~80 points max for clean rendering)
  const stride = Math.max(1, Math.floor(pts.length / 80));
  const sampled = pts.filter((_, idx) => idx % stride === 0);
  const path = sampled.map((p, idx) => `${idx === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  return { cells, path, last: pts[pts.length - 1] };
}

function bladeLineCoords(angleDeg: number | null | undefined): { x1: number; y1: number; x2: number; y2: number } {
  const rad = (((angleDeg ?? 0) * Math.PI) / 180);
  const r = 56;
  const dx = Math.cos(rad) * r;
  const dy = Math.sin(rad) * r;
  return { x1: 100 - dx, y1: 60 + dy, x2: 100 + dx, y2: 60 - dy };
}

export function SpatialHeatmapsView({
  report,
  scope,
}: {
  report: FightAnalytics;
  scope: ScopeSelection;
}) {
  const focalColor = getFocalColor(report);
  const [layer, setLayer] = useState<HeatmapLayer>("all");
  const [guardCorner, setGuardCorner] = useState<CornerColor>(focalColor);
  const [eventFilter, setEventFilter] = useState<"all" | "angle_cut" | "duck_weave">("all");
  const [eventLimit, setEventLimit] = useState<number>(40);

  useEffect(() => {
    setGuardCorner(focalColor);
    setEventFilter("all");
    setEventLimit(40);
  }, [report.session.name, focalColor]);

  useEffect(() => {
    setEventLimit(40);
  }, [eventFilter, scope]);

  const red = getFighter(report, "red");
  const blue = getFighter(report, "blue");
  const redName = red?.name ?? "Red";
  const blueName = blue?.name ?? "Blue";

  const { redDef, blueDef, keyMoments, series, durationSec } = getScopeData(report, scope);
  const redFoot = redDef?.footwork;
  const blueFoot = blueDef?.footwork;
  const redHead = redDef?.head_movement;
  const blueHead = blueDef?.head_movement;

  const ringSize = report.session.ring_size_x_m ?? 5.3;
  const redCornerId = red?.corner ?? 2;
  const blueCornerId = blue?.corner ?? 1;

  const redSpatial = useMemo(() => extractHipsPath(series, redCornerId, ringSize), [series, redCornerId, ringSize]);
  const blueSpatial = useMemo(() => extractHipsPath(series, blueCornerId, ringSize), [series, blueCornerId, ringSize]);

  // Center occupancy share (cells inside central 50% radius of the ring)
  const centerCount = (cells: { cx: number; cy: number; weight: number }[]) =>
    cells.reduce((acc, c) => (Math.hypot(c.cx - 250, c.cy - 250) <= 115 ? acc + c.weight : acc), 0);
  const [centerRedShare, centerBlueShare] = splitShare(centerCount(redSpatial.cells), centerCount(blueSpatial.cells));

  // Coronal plane head cross-section parameters
  const redMeanHeadY = seriesMean(series, "head_height", redCornerId) ?? red?.height_m ?? 1.75;
  const blueMeanHeadY = seriesMean(series, "head_height", blueCornerId) ?? blue?.height_m ?? 1.75;
  const topRefM = Math.max(red?.height_m ?? 1.85, blue?.height_m ?? 1.85, redMeanHeadY + 0.15);
  const botRefM = Math.max(0.9, Math.min(redMeanHeadY, blueMeanHeadY) - 0.45);
  const mapHeightY = (m: number) => {
    const ratio = (topRefM - m) / Math.max(0.2, topRefM - botRefM);
    return Math.max(35, Math.min(190, 35 + ratio * 150));
  };

  const redRx = Math.max(10, Math.min(150, (redHead?.head_lateral_slip_m.p90 ?? 0.05) * 420));
  const redRy = Math.max(10, Math.min(75, ((redHead?.p05_p95_span_m ?? 0.1) / 2) * 240));
  const blueRx = Math.max(10, Math.min(150, (blueHead?.head_lateral_slip_m.p90 ?? 0.05) * 420));
  const blueRy = Math.max(10, Math.min(75, ((blueHead?.p05_p95_span_m ?? 0.1) / 2) * 240));

  const redShoulderLine = bladeLineCoords(redFoot?.shoulder_blade_angle_deg);
  const blueShoulderLine = bladeLineCoords(blueFoot?.shoulder_blade_angle_deg);
  const redFootLine = bladeLineCoords(redFoot?.foot_blade_angle_deg);
  const blueFootLine = bladeLineCoords(blueFoot?.foot_blade_angle_deg);

  const activeGuard = guardCorner === "red" ? redDef?.guard_discipline : blueDef?.guard_discipline;

  // Spatial movement moments (angle_cut, duck, bob_and_weave, head_drop)
  const spatialMoments = keyMoments.filter((m) =>
    ["angle_cut", "duck", "bob_and_weave", "head_drop"].includes(m.type),
  );
  const angleCutCount = spatialMoments.filter((m) => m.type === "angle_cut").length;
  const duckWeaveCount = spatialMoments.filter((m) =>
    ["duck", "bob_and_weave", "head_drop"].includes(m.type),
  ).length;
  const filteredSpatialMoments = spatialMoments.filter((m) => {
    if (eventFilter === "angle_cut") return m.type === "angle_cut";
    if (eventFilter === "duck_weave") return ["duck", "bob_and_weave", "head_drop"].includes(m.type);
    return true;
  });

  const hz = report.session.fixed_timestep ? Math.round(1 / report.session.fixed_timestep) : 120;

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      {/* Sub-Header View Navigation & Compact Spatial Summary */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md py-space-xs">
        <div className="flex items-center gap-space-sm flex-wrap">
          <span className="font-label-caps text-label-caps text-secondary uppercase bg-surface-container px-space-sm py-1 rounded">
            Module 02
          </span>
          <h1 className="font-headline-md text-headline-md text-on-surface uppercase tracking-tight m-0">
            Spatial Heatmaps &amp; Movement Biomechanics
          </h1>
          <span className="flex items-center gap-space-xs font-label-data text-label-data text-outline bg-surface-container-low px-space-sm py-1 rounded">
            <span className="w-1.5 h-1.5 rounded-full bg-secondary" aria-hidden="true" />
            6-DOF Skeleton Stream @ {hz}Hz
          </span>
        </div>

        {/* Compact Spatial Summary Strip (replaces redundant Fighter Bio Banner) */}
        <div className="flex items-center gap-space-md flex-wrap bg-surface-container-low px-space-md py-space-xs rounded font-label-data text-label-data">
          <div>
            <span className="text-outline mr-1.5">Canvas Dist:</span>
            <span className="text-primary font-bold">{num(redFoot?.total_distance_m, 1)}m</span>
            <span className="text-outline mx-1">vs</span>
            <span className="text-secondary font-bold">{num(blueFoot?.total_distance_m, 1)}m</span>
          </div>
          <span className="text-outline" aria-hidden="true">·</span>
          <div>
            <span className="text-outline mr-1.5">Range Mean/Med:</span>
            <span className="text-on-surface font-semibold">
              {num(redFoot?.fighter_distance_m.mean, 2)}m / {num(redFoot?.fighter_distance_m.median, 2)}m
            </span>
          </div>
        </div>
      </div>

      {/* Primary Section: 2D Spatial Ring Control & Footwork Kinematics */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Left: Interactive Vector Ring Arena Heatmap Canvas */}
        <div className="xl:col-span-7 bg-surface-container-low p-space-lg rounded flex flex-col justify-between shadow-md">
          <div className="flex items-center justify-between mb-space-md flex-wrap gap-2">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-secondary text-[20px]" aria-hidden="true">radar</span>
              <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
                Ring Footprint &amp; Positional Density
              </h2>
            </div>
            <div className="flex items-center gap-space-xs bg-surface-container px-space-xs py-1 rounded flex-wrap">
              {(
                [
                  ["all", "Merged", "text-on-surface"],
                  ["red", "Red Only", "text-primary"],
                  ["blue", "Blue Only", "text-secondary"],
                  ["trajectory", "Hips Trace", "text-tertiary"],
                ] as const
              ).map(([id, label, colorCls]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={layer === id}
                  onClick={() => setLayer(id)}
                  className={`min-h-[32px] font-label-data text-label-data px-space-sm py-1 rounded transition-colors ${colorCls} ${
                    layer === id ? "bg-surface-bright font-semibold" : "hover:bg-surface-container-high"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="relative w-full aspect-square max-h-[460px] mx-auto bg-surface-container-lowest rounded overflow-hidden flex items-center justify-center p-space-md">
            <svg className="w-full h-full select-none" viewBox="0 0 500 500">
              <defs>
                <pattern id="canvas-grid" width="25" height="25" patternUnits="userSpaceOnUse">
                  <path
                    d="M 25 0 L 0 0 0 25"
                    fill="none"
                    stroke="#31353d"
                    strokeOpacity="0.45"
                    strokeWidth="0.75"
                  />
                </pattern>
                <radialGradient id="heat-red-blob" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#ff5451" stopOpacity="0.75" />
                  <stop offset="50%" stopColor="#ff5451" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#ff5451" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="heat-blue-blob" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#4cd7f6" stopOpacity="0.7" />
                  <stop offset="50%" stopColor="#4cd7f6" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#4cd7f6" stopOpacity="0" />
                </radialGradient>
              </defs>

              <rect x="0" y="0" width="500" height="500" fill="#0a0e15" />
              <rect x="30" y="30" width="440" height="440" fill="url(#canvas-grid)" />
              <rect x="50" y="50" width="400" height="400" fill="none" stroke="#31353d" strokeWidth="2" />
              <rect
                x="62"
                y="62"
                width="376"
                height="376"
                fill="none"
                stroke="#5b403e"
                strokeOpacity="0.6"
                strokeDasharray="4 4"
                strokeWidth="1.5"
              />
              <circle
                cx="250"
                cy="250"
                r="110"
                fill="none"
                stroke="#31353d"
                strokeDasharray="6 6"
                strokeWidth="1.5"
              />
              <circle cx="250" cy="250" r="45" fill="none" stroke="#31353d" strokeWidth="1" />
              <path d="M 240 250 L 260 250 M 250 240 L 250 260" stroke="#353941" strokeWidth="2" />

              {/* Corner Pads */}
              <polygon points="50,50 104,50 50,104" fill="#5c0008" fillOpacity="0.45" />
              <circle cx="50" cy="50" r="8" fill="#ff5451" />
              <text x="62" y="68" fill="#ffb3ad" fontSize="10" fontFamily="JetBrains Mono" fontWeight="700">
                RED
              </text>

              <polygon points="450,450 396,450 450,396" fill="#00424e" fillOpacity="0.45" />
              <circle cx="450" cy="450" r="8" fill="#4cd7f6" />
              <text x="412" y="442" fill="#4cd7f6" fontSize="10" fontFamily="JetBrains Mono" fontWeight="700">
                BLUE
              </text>

              {/* Red Heatmap Cells */}
              <g opacity={layer === "blue" ? 0.08 : layer === "trajectory" ? 0.25 : 0.92}>
                {redSpatial.cells.map((c, idx) => (
                  <circle
                    key={`r-${idx}`}
                    cx={c.cx}
                    cy={c.cy}
                    r={22 + c.weight * 34}
                    fill="url(#heat-red-blob)"
                    opacity={0.35 + c.weight * 0.65}
                  />
                ))}
              </g>

              {/* Blue Heatmap Cells */}
              <g opacity={layer === "red" ? 0.08 : layer === "trajectory" ? 0.25 : 0.88}>
                {blueSpatial.cells.map((c, idx) => (
                  <circle
                    key={`b-${idx}`}
                    cx={c.cx}
                    cy={c.cy}
                    r={22 + c.weight * 34}
                    fill="url(#heat-blue-blob)"
                    opacity={0.35 + c.weight * 0.65}
                  />
                ))}
              </g>

              {/* Hips Trajectory Paths */}
              {(layer === "trajectory" || layer === "all" || layer === "red") && redSpatial.path && (
                <path
                  d={redSpatial.path}
                  fill="none"
                  stroke="#ff5451"
                  strokeWidth={layer === "trajectory" ? 1.8 : 1.1}
                  strokeOpacity={layer === "trajectory" ? 0.85 : 0.4}
                />
              )}
              {(layer === "trajectory" || layer === "all" || layer === "blue") && blueSpatial.path && (
                <path
                  d={blueSpatial.path}
                  fill="none"
                  stroke="#4cd7f6"
                  strokeDasharray="3 2"
                  strokeWidth={layer === "trajectory" ? 1.8 : 1.1}
                  strokeOpacity={layer === "trajectory" ? 0.85 : 0.4}
                />
              )}

              {/* Terminal Markers */}
              {redSpatial.last && (
                <circle cx={redSpatial.last.x} cy={redSpatial.last.y} r="6" fill="#ff5451" stroke="#0a0e15" strokeWidth="2" />
              )}
              {blueSpatial.last && (
                <circle cx={blueSpatial.last.x} cy={blueSpatial.last.y} r="6" fill="#4cd7f6" stroke="#0a0e15" strokeWidth="2" />
              )}
            </svg>

            <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between gap-2 flex-wrap pointer-events-none">
              <div className="flex items-center gap-space-md bg-surface-container-high/90 backdrop-blur-md px-space-md py-space-xs rounded shadow-md">
                <div className="flex items-center gap-space-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-primary-container" />
                  <span className="font-label-caps text-label-caps text-on-surface">{redName}</span>
                </div>
                <div className="flex items-center gap-space-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-secondary" />
                  <span className="font-label-caps text-label-caps text-on-surface">{blueName}</span>
                </div>
              </div>
              <div className="font-label-data text-label-data text-outline bg-surface-container-high/90 backdrop-blur-md px-space-sm py-space-xs rounded">
                Ring Bounds: {ringSize.toFixed(1)}m × {(report.session.ring_size_z_m ?? ringSize).toFixed(1)}m
              </div>
            </div>
          </div>

          <div className="mt-space-md bg-surface-container p-space-md rounded">
            <div className="flex items-center justify-between font-label-caps text-label-caps mb-space-xs flex-wrap gap-1">
              <div className="flex items-center gap-space-xs text-primary">
                <span>CENTER RING OCCUPANCY</span>
                <span className="font-bold">{centerRedShare.toFixed(1)}%</span>
              </div>
              <div className="text-outline uppercase">Hips 0.25s Bucket Share</div>
              <div className="flex items-center gap-space-xs text-secondary">
                <span className="font-bold">{centerBlueShare.toFixed(1)}%</span>
                <span>OPPONENT CENTER SHARE</span>
              </div>
            </div>
            <div className="w-full h-2.5 bg-surface-container-highest rounded overflow-hidden flex">
              <div className="h-full bg-primary-container transition-all duration-500" style={{ width: `${centerRedShare}%` }} />
              <div className="h-full bg-secondary transition-all duration-500" style={{ width: `${centerBlueShare}%` }} />
            </div>
          </div>
        </div>

        {/* Right: Footwork Kinematics & Spatial Metrics */}
        <div className="xl:col-span-5 flex flex-col gap-space-md">
          <div className="grid grid-cols-2 gap-space-md">
            {/* Clockwise / Counterclockwise Circling */}
            <div className="bg-surface-container-low p-space-md rounded shadow-sm">
              <div className="flex items-center justify-between text-outline font-label-caps text-label-caps mb-space-xs">
                <span>CLOCKWISE CIRCLING</span>
              </div>
              <div className="flex items-baseline gap-space-xs flex-wrap">
                <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary font-bold">
                  {num(redFoot?.clockwise_distance_m, 1)}
                </span>
                <span className="font-label-data text-label-data text-outline">m</span>
                <span className="text-surface-variant font-label-data text-label-data">/</span>
                <span className="font-telemetry-metric-md text-telemetry-metric-md text-secondary">
                  {num(blueFoot?.clockwise_distance_m, 1)}
                </span>
                <span className="font-label-data text-label-data text-outline">m</span>
              </div>
              <div className="mt-space-sm flex items-center justify-between font-label-data text-label-data text-outline">
                <span>CCW: {num(redFoot?.counterclockwise_distance_m, 1)}m R</span>
                <span>{num(blueFoot?.counterclockwise_distance_m, 1)}m B</span>
              </div>
            </div>

            {/* Tangential / Lateral Share */}
            <div className="bg-surface-container-low p-space-md rounded shadow-sm">
              <div className="flex items-center justify-between text-outline font-label-caps text-label-caps mb-space-xs">
                <span>LATERAL SHARE</span>
              </div>
              <div className="flex items-baseline gap-space-xs flex-wrap">
                <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary font-bold">
                  {pct(redFoot?.tangential_share)}
                </span>
                <span className="text-surface-variant font-label-data text-label-data">/</span>
                <span className="font-telemetry-metric-md text-telemetry-metric-md text-secondary font-bold">
                  {pct(blueFoot?.tangential_share)}
                </span>
              </div>
              <div className="mt-space-sm flex items-center justify-between font-label-data text-label-data text-outline">
                <span>Radial: {num(redFoot?.radial_distance_m, 1)}m R</span>
                <span>{num(blueFoot?.radial_distance_m, 1)}m B</span>
              </div>
            </div>

            {/* Radial vs Lateral Path */}
            <div className="bg-surface-container-low p-space-md rounded shadow-sm">
              <div className="flex items-center justify-between text-outline font-label-caps text-label-caps mb-space-xs">
                <span>LATERAL DISTANCE</span>
              </div>
              <div className="flex items-baseline gap-space-xs flex-wrap">
                <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary font-bold">
                  {num(redFoot?.tangential_distance_m, 1)}
                </span>
                <span className="font-label-data text-label-data text-outline">m</span>
                <span className="text-surface-variant font-label-data text-label-data">/</span>
                <span className="font-telemetry-metric-md text-telemetry-metric-md text-secondary">
                  {num(blueFoot?.tangential_distance_m, 1)}
                </span>
                <span className="font-label-data text-label-data text-outline">m</span>
              </div>
              <div className="mt-space-sm font-label-data text-label-data text-outline">
                p10–p90 Range: {num(redFoot?.fighter_distance_m.p10, 2)}–{num(redFoot?.fighter_distance_m.p90, 2)}m
              </div>
            </div>

            {/* Angle Cuts */}
            <div className="bg-surface-container-low p-space-md rounded shadow-sm">
              <div className="flex items-center justify-between text-outline font-label-caps text-label-caps mb-space-xs">
                <span>TOTAL ANGLE CUTS</span>
              </div>
              <div className="flex items-baseline gap-space-xs">
                <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary font-bold">
                  {redFoot?.angle_cut_count ?? 0}
                </span>
                <span className="font-label-data text-label-data text-outline">R</span>
                <span className="text-surface-variant font-label-data text-label-data">/</span>
                <span className="font-telemetry-metric-md text-telemetry-metric-md text-secondary">
                  {blueFoot?.angle_cut_count ?? 0}
                </span>
                <span className="font-label-data text-label-data text-outline">B</span>
              </div>
              <div className="mt-space-sm font-label-data text-label-data text-outline">
                Entry: <span className="text-primary">{num(redFoot?.attack_entry_angle_deg, 1)}°</span> vs{" "}
                <span className="text-secondary">{num(blueFoot?.attack_entry_angle_deg, 1)}°</span>
              </div>
            </div>
          </div>

          {/* Pocket & Engagement Ranges */}
          <div className="bg-surface-container-low p-space-md rounded shadow-sm flex flex-col justify-between flex-1">
            <div className="flex items-center justify-between mb-space-sm">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-tertiary text-[18px]" aria-hidden="true">
                  straighten
                </span>
                <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
                  Pocket &amp; Engagement Ranges
                </h2>
              </div>
              <span className="font-label-data text-label-data text-outline">
                Bell Span: {clockWhole(durationSec)}
              </span>
            </div>

            <div className="space-y-space-sm">
              <div>
                <div className="flex items-center justify-between font-label-data text-label-data mb-space-xs">
                  <span className="text-outline">Clinch Range (&lt; 0.85m)</span>
                  <span className="text-on-surface font-label-caps text-label-caps font-semibold">
                    {pctPts(redFoot?.clinch_range_percent)} ({clockWhole(((redFoot?.clinch_range_percent ?? 0) / 100) * durationSec)})
                  </span>
                </div>
                <div className="w-full h-2 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-outline-variant rounded"
                    style={{ width: `${clampPct(redFoot?.clinch_range_percent)}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between font-label-data text-label-data mb-space-xs">
                  <span className="text-primary font-semibold">Pocket Zone (0.85m – 1.35m)</span>
                  <span className="text-primary font-label-caps text-label-caps font-bold">
                    {pctPts(redFoot?.pocket_range_percent)} ({clockWhole(((redFoot?.pocket_range_percent ?? 0) / 100) * durationSec)})
                  </span>
                </div>
                <div className="w-full h-2.5 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-primary-container rounded"
                    style={{ width: `${clampPct(redFoot?.pocket_range_percent)}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between font-label-data text-label-data mb-space-xs">
                  <span className="text-secondary font-semibold">Outside Range (&gt; 1.35m)</span>
                  <span className="text-secondary font-label-caps text-label-caps font-semibold">
                    {pctPts(redFoot?.outside_range_percent)} ({clockWhole(((redFoot?.outside_range_percent ?? 0) / 100) * durationSec)})
                  </span>
                </div>
                <div className="w-full h-2 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-secondary-container rounded"
                    style={{ width: `${clampPct(redFoot?.outside_range_percent)}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="mt-space-md p-space-sm bg-surface-container-lowest rounded flex items-center justify-between gap-space-md">
              <div>
                <span className="font-label-caps text-label-caps text-tertiary font-bold uppercase">
                  Post-Combo Exit Sweep
                </span>
                <p className="font-body-sm text-body-sm text-outline m-0 mt-0.5">
                  Mean 0.5s angular sweep after last punch: Red{" "}
                  <span className="text-primary font-semibold">{num(redFoot?.post_combo_exit_angle_deg, 1)}°</span> vs
                  Blue{" "}
                  <span className="text-secondary font-semibold">{num(blueFoot?.post_combo_exit_angle_deg, 1)}°</span>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Section 3: Head Movement & Centerline Evasion Biomechanics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg">
        <div className="lg:col-span-6 bg-surface-container-low p-space-lg rounded shadow-md flex flex-col justify-between">
          <div className="flex items-center justify-between mb-space-md">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-primary text-[20px]" aria-hidden="true">
                airline_seat_recline_extra
              </span>
              <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
                Centerline &amp; Head Envelope
              </h2>
            </div>
            <span className="font-label-caps text-label-caps text-outline bg-surface-container px-space-sm py-space-xs rounded">
              OPPONENT FRAME
            </span>
          </div>

          <div className="relative w-full h-60 bg-surface-container-lowest rounded flex items-center justify-center p-space-md overflow-hidden">
            <svg className="w-full h-full" viewBox="0 0 460 220">
              <line
                x1="230"
                y1="20"
                x2="230"
                y2="200"
                stroke="#ffb95f"
                strokeOpacity="0.65"
                strokeDasharray="4 4"
                strokeWidth="1.5"
              />
              <text x="236" y="32" fill="#ffb95f" fontSize="9" fontFamily="JetBrains Mono">
                CENTERLINE (0.00m)
              </text>

              <line x1="35" y1="45" x2="425" y2="45" stroke="#31353d" strokeWidth="0.7" />
              <text x="40" y="41" fill="#ab8986" fontSize="9" fontFamily="JetBrains Mono">
                {topRefM.toFixed(2)}m STANDING REF
              </text>

              <line x1="35" y1="185" x2="425" y2="185" stroke="#31353d" strokeWidth="0.7" />
              <text x="40" y="181" fill="#ab8986" fontSize="9" fontFamily="JetBrains Mono">
                {botRefM.toFixed(2)}m LEVEL CHANGE REF
              </text>

              {/* Blue Envelope */}
              <ellipse
                cx={230}
                cy={mapHeightY(blueMeanHeadY)}
                rx={blueRx}
                ry={blueRy}
                fill="#4cd7f6"
                fillOpacity="0.1"
                stroke="#4cd7f6"
                strokeDasharray="3 3"
                strokeWidth="1.5"
              />
              <circle cx={230} cy={mapHeightY(blueMeanHeadY)} r="4" fill="#4cd7f6" />
              <text
                x={Math.min(350, 238 + blueRx * 0.5)}
                y={mapHeightY(blueMeanHeadY) + 14}
                fill="#4cd7f6"
                fontSize="10"
                fontFamily="JetBrains Mono"
                fontWeight="700"
              >
                {blueName} [p90 {num(blueHead?.head_lateral_slip_m.p90, 2)}m]
              </text>

              {/* Red Envelope */}
              <ellipse
                cx={230}
                cy={mapHeightY(redMeanHeadY)}
                rx={redRx}
                ry={redRy}
                fill="#ff5451"
                fillOpacity="0.18"
                stroke="#ff5451"
                strokeWidth="1.8"
              />
              <circle cx={230} cy={mapHeightY(redMeanHeadY)} r="4.5" fill="#ffb3ad" />
              <text
                x={Math.max(42, 222 - redRx - 85)}
                y={mapHeightY(redMeanHeadY) - 6}
                fill="#ffb3ad"
                fontSize="10"
                fontFamily="JetBrains Mono"
                fontWeight="700"
              >
                {redName} [p90 {num(redHead?.head_lateral_slip_m.p90, 2)}m]
              </text>
            </svg>
          </div>

          <div className="mt-space-md grid grid-cols-3 gap-space-sm text-center">
            <div className="bg-surface-container p-space-sm rounded">
              <div className="font-label-caps text-label-caps text-outline">HEAD SPAN (P05–P95)</div>
              <div className="font-telemetry-metric-md text-telemetry-metric-md text-primary font-bold">
                {num(redHead?.p05_p95_span_m, 2)} <span className="font-label-data text-outline">m</span>
              </div>
              <div className="font-label-data text-label-data text-secondary mt-0.5">
                vs {num(blueHead?.p05_p95_span_m, 2)}m B
              </div>
            </div>
            <div className="bg-surface-container p-space-sm rounded">
              <div className="font-label-caps text-label-caps text-outline">MEDIAN LATERAL SLIP</div>
              <div className="font-telemetry-metric-md text-telemetry-metric-md text-primary font-bold">
                {num(redHead?.head_lateral_slip_m.median, 2)} <span className="font-label-data text-outline">m</span>
              </div>
              <div className="font-label-data text-label-data text-secondary mt-0.5">
                vs {num(blueHead?.head_lateral_slip_m.median, 2)}m B
              </div>
            </div>
            <div className="bg-surface-container p-space-sm rounded">
              <div className="font-label-caps text-label-caps text-outline">P90 SLIP UNDER FIRE</div>
              <div className="font-telemetry-metric-md text-telemetry-metric-md text-primary font-bold">
                {num(redHead?.head_lateral_slip_m.under_fire_p90, 2)}{" "}
                <span className="font-label-data text-outline">m</span>
              </div>
              <div className="font-label-data text-label-data text-secondary mt-0.5">
                vs {num(blueHead?.head_lateral_slip_m.under_fire_p90, 2)}m B
              </div>
            </div>
          </div>
        </div>

        {/* Centerline Discipline Under Fire */}
        <div className="lg:col-span-6 flex flex-col justify-between gap-space-md">
          <div className="bg-surface-container-low p-space-lg rounded shadow-md flex-1 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-space-sm">
                <div className="flex items-center gap-space-sm">
                  <span className="material-symbols-outlined text-secondary text-[20px]" aria-hidden="true">
                    crisis_alert
                  </span>
                  <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
                    Centerline Discipline (&ge; 0.10m Slip)
                  </h2>
                </div>
                <span className="font-label-caps text-label-caps text-tertiary bg-on-tertiary-container/30 px-space-xs rounded font-semibold">
                  Overall: {pctPts(redHead?.off_centerline_percent)} R · {pctPts(blueHead?.off_centerline_percent)} B
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-md mt-space-md">
                <div className="bg-surface-container p-space-md rounded">
                  <span className="font-label-caps text-label-caps text-outline block mb-space-xs">
                    OFF-CENTERLINE (UNDER FIRE)
                  </span>
                  <div className="flex items-baseline justify-between">
                    <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary font-bold">
                      {pctPts(redHead?.off_centerline_under_fire_percent)}
                    </span>
                    <span className="font-telemetry-metric-md text-telemetry-metric-md text-secondary font-bold">
                      {pctPts(blueHead?.off_centerline_under_fire_percent)}
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-container-highest rounded mt-space-xs flex">
                    <div
                      className="h-full bg-primary-container"
                      style={{
                        width: `${
                          splitShare(
                            redHead?.off_centerline_under_fire_percent,
                            blueHead?.off_centerline_under_fire_percent,
                          )[0]
                        }%`,
                      }}
                    />
                    <div
                      className="h-full bg-secondary"
                      style={{
                        width: `${
                          splitShare(
                            redHead?.off_centerline_under_fire_percent,
                            blueHead?.off_centerline_under_fire_percent,
                          )[1]
                        }%`,
                      }}
                    />
                  </div>
                  <p className="font-body-sm text-body-sm text-outline m-0 mt-space-xs">
                    Head speed under fire: {num(redDef?.head_mean_speed_under_fire, 2)} vs{" "}
                    {num(blueDef?.head_mean_speed_under_fire, 2)} m/s
                  </p>
                </div>

                <div className="bg-surface-container p-space-md rounded">
                  <span className="font-label-caps text-label-caps text-outline block mb-space-xs">
                    OFF-CENTERLINE (WHILE PUNCHING)
                  </span>
                  <div className="flex items-baseline justify-between">
                    <span className="font-telemetry-metric-lg text-telemetry-metric-lg text-primary font-bold">
                      {pctPts(redHead?.off_centerline_while_punching_percent)}
                    </span>
                    <span className="font-telemetry-metric-md text-telemetry-metric-md text-secondary font-bold">
                      {pctPts(blueHead?.off_centerline_while_punching_percent)}
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-container-highest rounded mt-space-xs flex">
                    <div
                      className="h-full bg-primary-container"
                      style={{
                        width: `${
                          splitShare(
                            redHead?.off_centerline_while_punching_percent,
                            blueHead?.off_centerline_while_punching_percent,
                          )[0]
                        }%`,
                      }}
                    />
                    <div
                      className="h-full bg-secondary"
                      style={{
                        width: `${
                          splitShare(
                            redHead?.off_centerline_while_punching_percent,
                            blueHead?.off_centerline_while_punching_percent,
                          )[1]
                        }%`,
                      }}
                    />
                  </div>
                  <p className="font-body-sm text-body-sm text-outline m-0 mt-space-xs">
                    Pelvis drop IQR: {num(redHead?.pelvis_drop_iqr_m, 2)}m vs {num(blueHead?.pelvis_drop_iqr_m, 2)}m
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-space-md bg-surface-container-lowest p-space-md rounded flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-space-lg">
                <div>
                  <span className="font-label-caps text-label-caps text-outline block">DUCKS COUNT</span>
                  <div className="flex items-center gap-space-xs mt-0.5">
                    <span className="font-telemetry-metric-md text-primary font-bold">{redHead?.duck_count ?? 0}</span>
                    <span className="font-label-data text-outline">vs</span>
                    <span className="font-telemetry-metric-md text-secondary font-bold">
                      {blueHead?.duck_count ?? 0}
                    </span>
                  </div>
                </div>
                <div className="h-8 w-[1px] bg-surface-container-highest" />
                <div>
                  <span className="font-label-caps text-label-caps text-outline block">BOB &amp; WEAVES</span>
                  <div className="flex items-center gap-space-xs mt-0.5">
                    <span className="font-telemetry-metric-md text-primary font-bold">
                      {redHead?.bob_and_weave_count ?? 0}
                    </span>
                    <span className="font-label-data text-outline">vs</span>
                    <span className="font-telemetry-metric-md text-secondary font-bold">
                      {blueHead?.bob_and_weave_count ?? 0}
                    </span>
                  </div>
                </div>
              </div>
              <div className="text-right">
                <span className="font-label-caps text-label-caps text-outline">TRUNK BEND IQR</span>
                <div className="font-telemetry-metric-md text-on-surface font-bold">
                  {num(redHead?.trunk_bend_iqr_m, 2)}m{" "}
                  <span className="text-secondary font-label-data">/ {num(blueHead?.trunk_bend_iqr_m, 2)}m</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Section 4: Stance Geometry & Guard Integrity */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        <div className="xl:col-span-8 bg-surface-container-low p-space-lg rounded shadow-md">
          <div className="flex items-center justify-between mb-space-md">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-secondary text-[20px]" aria-hidden="true">
                architecture
              </span>
              <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
                Stance Geometry &amp; Blade Orientation
              </h2>
            </div>
            <span className="font-label-caps text-label-caps text-outline bg-surface-container px-space-sm py-space-xs rounded">
              0° SQUARE · 90° BLADED
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
            {/* Shoulder Blade Angle */}
            <div className="bg-surface-container p-space-md rounded flex flex-col justify-between">
              <div className="flex items-center justify-between mb-space-sm">
                <span className="font-label-caps text-label-caps text-outline">SHOULDER BLADE ANGLE</span>
                <span className="font-label-data text-label-data text-primary font-bold">
                  {num(redFoot?.shoulder_blade_angle_deg, 1)}° vs {num(blueFoot?.shoulder_blade_angle_deg, 1)}°
                </span>
              </div>
              <div className="flex items-center justify-center py-space-sm">
                <svg className="w-52 h-28" viewBox="0 0 200 120">
                  <line x1="20" y1="60" x2="180" y2="60" stroke="#31353d" strokeDasharray="2 2" strokeWidth="1" />
                  <line
                    x1={redShoulderLine.x1}
                    y1={redShoulderLine.y1}
                    x2={redShoulderLine.x2}
                    y2={redShoulderLine.y2}
                    stroke="#ff5451"
                    strokeWidth="3"
                  />
                  <circle cx={redShoulderLine.x1} cy={redShoulderLine.y1} r="3.5" fill="#ff5451" />
                  <circle cx={redShoulderLine.x2} cy={redShoulderLine.y2} r="3.5" fill="#ff5451" />
                  <line
                    x1={blueShoulderLine.x1}
                    y1={blueShoulderLine.y1}
                    x2={blueShoulderLine.x2}
                    y2={blueShoulderLine.y2}
                    stroke="#4cd7f6"
                    strokeDasharray="4 2"
                    strokeWidth="2.2"
                  />
                  <circle cx={blueShoulderLine.x1} cy={blueShoulderLine.y1} r="3" fill="#4cd7f6" />
                  <circle cx={blueShoulderLine.x2} cy={blueShoulderLine.y2} r="3" fill="#4cd7f6" />
                </svg>
              </div>
              <div className="font-label-data text-body-sm text-outline">
                Square Stance (&lt;15°): {pctPts(redFoot?.square_stance_percent)} R ·{" "}
                {pctPts(blueFoot?.square_stance_percent)} B
              </div>
            </div>

            {/* Foot Blade Angle */}
            <div className="bg-surface-container p-space-md rounded flex flex-col justify-between">
              <div className="flex items-center justify-between mb-space-sm">
                <span className="font-label-caps text-label-caps text-outline">FOOT BLADE ANGLE (IK)</span>
                <span className="font-label-data text-label-data text-secondary font-bold">
                  {num(redFoot?.foot_blade_angle_deg, 1)}° vs {num(blueFoot?.foot_blade_angle_deg, 1)}°
                </span>
              </div>
              <div className="flex items-center justify-center py-space-sm">
                <svg className="w-52 h-28" viewBox="0 0 200 120">
                  <line x1="20" y1="60" x2="180" y2="60" stroke="#31353d" strokeDasharray="2 2" strokeWidth="1" />
                  <line
                    x1={redFootLine.x1}
                    y1={redFootLine.y1}
                    x2={redFootLine.x2}
                    y2={redFootLine.y2}
                    stroke="#ff5451"
                    strokeWidth="3"
                  />
                  <line
                    x1={blueFootLine.x1}
                    y1={blueFootLine.y1}
                    x2={blueFootLine.x2}
                    y2={blueFootLine.y2}
                    stroke="#4cd7f6"
                    strokeDasharray="4 2"
                    strokeWidth="2.2"
                  />
                </svg>
              </div>
              <div className="font-label-data text-body-sm text-outline">
                Ankle line median angle (IK-estimated on Quest)
              </div>
            </div>
          </div>

          <div className="mt-space-md bg-surface-container-lowest p-space-md rounded grid grid-cols-1 md:grid-cols-2 gap-space-lg">
            <div className="space-y-1.5">
              <div className="flex justify-between font-label-data text-label-data">
                <span className="text-outline">Lead Left Shoulder Share</span>
                <span>
                  <span className="text-primary font-bold">{pctPts(redFoot?.lead_left_percent)} R</span>
                  <span className="text-outline mx-1">vs</span>
                  <span className="text-secondary font-bold">{pctPts(blueFoot?.lead_left_percent)} B</span>
                </span>
              </div>
              <div className="space-y-1">
                <div className="w-full h-2 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-primary-container rounded"
                    style={{ width: `${clampPct(redFoot?.lead_left_percent)}%` }}
                  />
                </div>
                <div className="w-full h-2 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-secondary rounded"
                    style={{ width: `${clampPct(blueFoot?.lead_left_percent)}%` }}
                  />
                </div>
              </div>
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between font-label-data text-label-data">
                <span className="text-outline">Square Stance While Punching</span>
                <span>
                  <span className="text-primary font-bold">
                    {pctPts(redFoot?.square_while_punching_percent)} R
                  </span>
                  <span className="text-outline mx-1">vs</span>
                  <span className="text-secondary font-bold">
                    {pctPts(blueFoot?.square_while_punching_percent)} B
                  </span>
                </span>
              </div>
              <div className="space-y-1">
                <div className="w-full h-2 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-primary-container rounded"
                    style={{ width: `${clampPct(redFoot?.square_while_punching_percent)}%` }}
                  />
                </div>
                <div className="w-full h-2 bg-surface-container rounded overflow-hidden">
                  <div
                    className="h-full bg-secondary rounded"
                    style={{ width: `${clampPct(blueFoot?.square_while_punching_percent)}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Guard Integrity & Hand Return */}
        <div className="xl:col-span-4 bg-surface-container-low p-space-lg rounded shadow-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-space-md gap-2 flex-wrap">
              <div className="flex items-center gap-space-sm">
                <span className="material-symbols-outlined text-primary text-[20px]" aria-hidden="true">
                  shield
                </span>
                <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
                  Guard Integrity
                </h2>
              </div>
              <div className="flex items-center bg-surface-container-lowest p-0.5 rounded gap-1">
                <button
                  type="button"
                  aria-pressed={guardCorner === "red"}
                  onClick={() => setGuardCorner("red")}
                  className={`min-h-[32px] font-label-caps text-label-caps px-space-sm py-1 rounded ${
                    guardCorner === "red"
                      ? "bg-on-primary-container text-primary font-bold"
                      : "text-outline hover:text-on-surface"
                  }`}
                >
                  {redName}
                </button>
                <button
                  type="button"
                  aria-pressed={guardCorner === "blue"}
                  onClick={() => setGuardCorner("blue")}
                  className={`min-h-[32px] font-label-caps text-label-caps px-space-sm py-1 rounded ${
                    guardCorner === "blue"
                      ? "bg-on-secondary-container text-secondary font-bold"
                      : "text-outline hover:text-on-surface"
                  }`}
                >
                  {blueName}
                </button>
              </div>
            </div>

            <div className="space-y-space-md">
              <div className="bg-surface-container p-space-md rounded">
                <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
                  <span>OFF-HAND KEPT (THROWING LEFT)</span>
                  <span className="text-primary font-bold">
                    {pctPts(activeGuard?.offhand_guard_kept_percent_throwing_left)}
                  </span>
                </div>
                <div className="w-full h-2 bg-surface-container-highest rounded overflow-hidden">
                  <div
                    className="h-full bg-primary-container"
                    style={{ width: `${clampPct(activeGuard?.offhand_guard_kept_percent_throwing_left)}%` }}
                  />
                </div>
                <p className="font-body-sm text-body-sm text-outline m-0 mt-space-xs">
                  Rear hand drop median: {num(activeGuard?.offhand_drop_below_head_m_rear.median, 2)}m · flare{" "}
                  {num(activeGuard?.offhand_lateral_flare_m_rear.median, 2)}m
                </p>
              </div>

              <div className="bg-surface-container p-space-md rounded">
                <div className="flex items-center justify-between font-label-caps text-label-caps text-outline mb-space-xs">
                  <span>OFF-HAND KEPT (THROWING RIGHT)</span>
                  <span className="text-secondary font-bold">
                    {pctPts(activeGuard?.offhand_guard_kept_percent_throwing_right)}
                  </span>
                </div>
                <div className="w-full h-2 bg-surface-container-highest rounded overflow-hidden">
                  <div
                    className="h-full bg-secondary"
                    style={{ width: `${clampPct(activeGuard?.offhand_guard_kept_percent_throwing_right)}%` }}
                  />
                </div>
                <p className="font-body-sm text-body-sm text-outline m-0 mt-space-xs">
                  Lead hand drop median: {num(activeGuard?.offhand_drop_below_head_m_lead.median, 2)}m · flare{" "}
                  {num(activeGuard?.offhand_lateral_flare_m_lead.median, 2)}m
                </p>
              </div>

              <div className="bg-surface-container p-space-md rounded flex items-center justify-between">
                <div>
                  <span className="font-label-caps text-label-caps text-outline block">MEDIAN HAND RETURN</span>
                  <div className="font-telemetry-metric-lg text-on-surface font-bold">
                    {num(activeGuard?.retraction_time_ms.median, 0)}{" "}
                    <span className="text-outline font-label-data">ms</span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="font-label-caps text-label-caps text-outline block">RETURN DROOP</span>
                  <div className="font-telemetry-metric-lg text-primary font-bold">
                    {num(activeGuard?.retraction_droop_m.median, 2)}{" "}
                    <span className="text-outline font-label-data">m</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-space-md pt-space-sm flex items-center justify-between font-label-data text-label-data text-outline">
            <span>Returned within 800ms: {pctPts(activeGuard?.retraction_returned_percent)}</span>
            <span>Directness: {num(activeGuard?.retraction_directness_ratio.median, 2)}</span>
          </div>
        </div>
      </div>

      {/* Section 5: Spatial Movement Event Stream */}
      <div className="bg-surface-container-low p-space-lg rounded shadow-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-space-md mb-space-md">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-secondary text-[20px]" aria-hidden="true">
              list_alt
            </span>
            <h2 className="font-headline-sm text-headline-sm text-on-surface uppercase m-0">
              Spatial Movement Event Stream
            </h2>
          </div>
          <div className="flex items-center gap-space-xs flex-wrap font-label-caps text-label-caps">
            <button
              type="button"
              aria-pressed={eventFilter === "all"}
              onClick={() => setEventFilter("all")}
              className={`min-h-[32px] px-space-sm py-1 rounded ${
                eventFilter === "all"
                  ? "bg-surface-bright text-on-surface font-semibold"
                  : "bg-surface-container text-outline hover:text-on-surface"
              }`}
            >
              ALL ({spatialMoments.length})
            </button>
            <button
              type="button"
              aria-pressed={eventFilter === "angle_cut"}
              onClick={() => setEventFilter("angle_cut")}
              className={`min-h-[32px] px-space-sm py-1 rounded ${
                eventFilter === "angle_cut"
                  ? "bg-surface-bright text-primary font-semibold"
                  : "bg-surface-container text-primary hover:bg-surface-container-high"
              }`}
            >
              Angle Cuts ({angleCutCount})
            </button>
            <button
              type="button"
              aria-pressed={eventFilter === "duck_weave"}
              onClick={() => setEventFilter("duck_weave")}
              className={`min-h-[32px] px-space-sm py-1 rounded ${
                eventFilter === "duck_weave"
                  ? "bg-surface-bright text-secondary font-semibold"
                  : "bg-surface-container text-secondary hover:bg-surface-container-high"
              }`}
            >
              Ducks &amp; Weaves ({duckWeaveCount})
            </button>
          </div>
        </div>

        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-left font-label-data text-label-data">
            <thead className="sticky top-0 bg-surface-container text-outline font-label-caps text-label-caps uppercase">
              <tr>
                <th className="py-space-sm px-space-md">TIMESTAMP</th>
                <th className="py-space-sm px-space-md">CORNER</th>
                <th className="py-space-sm px-space-md">KINEMATIC EVENT</th>
                <th className="py-space-sm px-space-md">MEASURED PARAMETERS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container">
              {filteredSpatialMoments.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-space-md px-space-md text-outline text-center">
                    No spatial movement events in this slice.
                  </td>
                </tr>
              )}
              {filteredSpatialMoments.slice(0, eventLimit).map((m, idx) => {
                const c = m.corners.length === 1 ? cornerColor(m.corners[0]) : null;
                return (
                  <tr key={`${m.tick}-${m.type}-${idx}`} className="hover:bg-surface-container-high/60 transition-colors">
                    <td className="py-space-sm px-space-md text-on-surface font-semibold">
                      {roundTimestampLabel(report, m.t_sec, scope)}
                    </td>
                    <td className="py-space-sm px-space-md">
                      <span
                        className={`font-label-caps text-[10px] px-space-xs py-0.5 rounded font-bold ${
                          c === "red" ? "bg-on-primary-container text-primary" : "bg-on-secondary-container text-secondary"
                        }`}
                      >
                        {c === "red" ? redName : blueName}
                      </span>
                    </td>
                    <td className="py-space-sm px-space-md text-on-surface font-medium capitalize">
                      {m.type.replaceAll("_", " ")}
                    </td>
                    <td className="py-space-sm px-space-md text-outline">{formatMomentDetail(m.detail)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filteredSpatialMoments.length > 0 && (
          <div className="mt-space-md pt-space-sm border-t border-surface-container flex items-center justify-between flex-wrap gap-space-sm font-label-data text-label-data text-outline">
            <span>
              Showing {Math.min(eventLimit, filteredSpatialMoments.length)} of {filteredSpatialMoments.length}{" "}
              spatial events
            </span>
            {filteredSpatialMoments.length > eventLimit && (
              <div className="flex items-center gap-space-xs">
                <button
                  type="button"
                  onClick={() => setEventLimit((n) => n + 40)}
                  className="min-h-[32px] px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright text-on-surface transition-colors"
                >
                  Load more (+{Math.min(40, filteredSpatialMoments.length - eventLimit)})
                </button>
                <button
                  type="button"
                  onClick={() => setEventLimit(filteredSpatialMoments.length)}
                  className="min-h-[32px] px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright text-outline hover:text-on-surface transition-colors"
                >
                  Show all
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
