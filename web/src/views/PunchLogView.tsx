import { useMemo, useState } from "react";
import type { FightAnalytics } from "../types";
import {
  type ScopeSelection,
  clockWhole,
  cornerColor,
  formatTrajectoryLabel,
  getFighter,
  getScopeData,
  num,
  roundTimestampLabel,
} from "../utils";

export function PunchLogView({
  report,
  scope,
  onSelectScope,
}: {
  report: FightAnalytics;
  scope: ScopeSelection;
  onSelectScope: (next: ScopeSelection) => void;
}) {
  const [cornerFilter, setCornerFilter] = useState<"both" | "red" | "blue">("both");
  const [landedOnly, setLandedOnly] = useState(false);
  const [trajFilter, setTrajFilter] = useState("all");
  const [page, setPage] = useState(1);

  const red = getFighter(report, "red");
  const blue = getFighter(report, "blue");
  const redName = red?.name ?? "Red";
  const blueName = blue?.name ?? "Blue";

  const { completedRounds, offense } = getScopeData(report, scope);

  const allPunches = useMemo(() => {
    return offense
      .flatMap((off) => {
        const color = cornerColor(off.corner);
        return off.punches
          .filter((p) => p.hand !== "unmatched")
          .map((p) => ({
            ...p,
            corner: off.corner,
            color,
            fighterName: color === "red" ? redName : blueName,
          }));
      })
      .sort((a, b) => a.t_sec - b.t_sec);
  }, [offense, redName, blueName]);

  const trajectories = useMemo(
    () => ["all", ...Array.from(new Set(allPunches.map((p) => p.trajectory))).sort()],
    [allPunches],
  );

  const filtered = useMemo(() => {
    return allPunches.filter((p) => {
      if (cornerFilter !== "both" && p.color !== cornerFilter) return false;
      if (landedOnly && !p.landed) return false;
      if (trajFilter !== "all" && p.trajectory !== trajFilter) return false;
      return true;
    });
  }, [allPunches, cornerFilter, landedOnly, trajFilter]);

  const pageSize = 40;
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const rows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md bg-surface-container-low p-space-md rounded-lg shadow-sm">
        <div>
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-primary text-[20px]">list_alt</span>
            <h1 className="font-headline-sm text-headline-sm uppercase text-on-surface m-0">
              Complete Punch-by-Punch Telemetry Stream
            </h1>
          </div>
          <p className="font-label-data text-label-data text-outline m-0 mt-0.5">
            {filtered.length} matching records out of {allPunches.length} total punches in slice
          </p>
        </div>

        <div className="flex items-center bg-surface-container-lowest p-space-xs rounded gap-1 flex-wrap">
          <button
            type="button"
            onClick={() => {
              onSelectScope("all");
              setPage(1);
            }}
            className={`px-space-sm py-space-xs rounded font-label-data text-label-data ${
              scope === "all" ? "bg-surface-bright text-on-surface font-semibold" : "text-outline"
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
              className={`px-space-sm py-space-xs rounded font-label-data text-label-data ${
                scope === r.index ? "bg-surface-bright text-on-surface font-semibold" : "text-outline"
              }`}
            >
              R{r.index + 1} ({clockWhole(r.duration_sec)})
            </button>
          ))}
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center justify-between gap-space-md flex-wrap bg-surface-container p-space-md rounded-lg">
        <div className="flex items-center gap-space-xs flex-wrap">
          {(
            [
              ["both", "Both Corners"],
              ["red", `${redName} (Red)`],
              ["blue", `${blueName} (Blue)`],
            ] as const
          ).map(([val, label]) => (
            <button
              key={val}
              type="button"
              onClick={() => {
                setCornerFilter(val);
                setPage(1);
              }}
              className={`px-space-sm py-space-xs rounded font-label-caps text-label-caps transition-colors ${
                cornerFilter === val
                  ? "bg-surface-container-high text-primary font-bold"
                  : "bg-surface-container-lowest text-outline hover:text-on-surface"
              }`}
            >
              {label}
            </button>
          ))}

          <button
            type="button"
            onClick={() => {
              setLandedOnly((v) => !v);
              setPage(1);
            }}
            className={`px-space-sm py-space-xs rounded font-label-caps text-label-caps transition-colors ${
              landedOnly
                ? "bg-on-tertiary-container text-tertiary font-bold"
                : "bg-surface-container-lowest text-outline hover:text-on-surface"
            }`}
          >
            Landed Only
          </button>
        </div>

        <select
          value={trajFilter}
          onChange={(e) => {
            setTrajFilter(e.target.value);
            setPage(1);
          }}
          className="bg-surface-container-lowest text-on-surface font-label-data text-label-data px-space-sm py-1.5 rounded outline-none cursor-pointer"
        >
          {trajectories.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All Trajectories" : formatTrajectoryLabel(t)}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="bg-surface-container-low rounded-lg p-space-md shadow-sm overflow-x-auto">
        <table className="w-full text-left font-label-data text-label-data border-collapse">
          <thead>
            <tr className="bg-surface-container text-outline font-label-caps text-label-caps uppercase">
              <th className="p-space-sm">Time</th>
              <th className="p-space-sm">Fighter</th>
              <th className="p-space-sm">Hand</th>
              <th className="p-space-sm">Trajectory</th>
              <th className="p-space-sm text-right">Speed</th>
              <th className="p-space-sm">Outcome</th>
              <th className="p-space-sm text-right">Damage</th>
              <th className="p-space-sm text-right">Combo</th>
              <th className="p-space-sm text-right">Head Slip</th>
              <th className="p-space-sm text-right">Return</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-container">
            {rows.map((p, idx) => (
              <tr key={`${p.corner}-${p.t_sec}-${idx}`} className="hover:bg-surface-container-high/50 transition-colors">
                <td className="p-space-sm text-outline whitespace-nowrap">
                  {roundTimestampLabel(report, p.t_sec, scope)}
                </td>
                <td className="p-space-sm">
                  <span
                    className={`px-space-xs py-0.5 rounded font-label-caps text-[10px] font-bold ${
                      p.color === "red"
                        ? "bg-on-primary-container text-primary"
                        : "bg-on-secondary-container text-secondary"
                    }`}
                  >
                    {p.fighterName}
                  </span>
                </td>
                <td className="p-space-sm capitalize text-on-surface">{p.hand.replaceAll("_", " ")}</td>
                <td className="p-space-sm text-on-surface">{formatTrajectoryLabel(p.trajectory)}</td>
                <td className="p-space-sm text-right text-on-surface font-semibold">
                  {p.speed != null ? `${p.speed.toFixed(2)} m/s` : "—"}
                </td>
                <td className="p-space-sm">
                  {p.landed ? (
                    <span className="text-tertiary font-bold font-label-caps text-[10px] bg-tertiary-container/30 px-1.5 py-0.5 rounded">
                      LANDED
                    </span>
                  ) : (
                    <span className="text-outline font-label-caps text-[10px]">MISS</span>
                  )}
                  {p.countered && (
                    <span className="ml-1 text-error font-label-caps text-[10px] bg-error-container/40 px-1 py-0.5 rounded">
                      COUNTERED
                    </span>
                  )}
                </td>
                <td className="p-space-sm text-right text-tertiary">
                  {p.damage != null ? `+${num(p.damage, 2)}` : "—"}
                </td>
                <td className="p-space-sm text-right text-outline">
                  {p.combo_id != null ? `#${p.combo_id} (D${p.combo_depth ?? "1"})` : "—"}
                </td>
                <td className="p-space-sm text-right text-outline">
                  {p.head_slip_m != null ? `${p.head_slip_m >= 0 ? "+" : ""}${p.head_slip_m.toFixed(2)}m` : "—"}
                </td>
                <td className="p-space-sm text-right text-outline">
                  {p.retraction_ms != null ? `${Math.round(p.retraction_ms)}ms` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex items-center justify-between pt-space-md font-label-data text-label-data text-outline">
          <span>
            Page {safePage} of {totalPages}
          </span>
          <div className="flex items-center gap-space-xs">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright disabled:opacity-40 text-on-surface"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright disabled:opacity-40 text-on-surface"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
