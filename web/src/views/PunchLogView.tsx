import { useEffect, useMemo, useState } from "react";
import type { FightAnalytics } from "../types";
import {
  type ScopeSelection,
  cornerColor,
  formatTrajectoryLabel,
  getFighter,
  getScopeData,
  num,
  roundTimestampLabel,
} from "../utils";

type SortKey = "time" | "speed" | "damage" | "return";
type SortDir = "asc" | "desc";

function isKdOrStoppage(hitKind?: string | null): boolean {
  return (
    hitKind === "knockdown" ||
    hitKind === "punishment_knockdown" ||
    hitKind === "knockout" ||
    hitKind === "tko"
  );
}

function isStoppage(hitKind?: string | null): boolean {
  return hitKind === "knockout" || hitKind === "tko";
}

function hitKindBadge(
  hitKind?: string | null,
): { label: string; title: string; className: string } | null {
  switch (hitKind) {
    case "knockout":
      return {
        label: "KO",
        title: "Knockout blow — ended the fight",
        className: "bg-error text-on-error font-extrabold border border-error/80",
      };
    case "tko":
      return {
        label: "TKO",
        title: "Technical knockout blow — ended the fight",
        className: "bg-error text-on-error font-extrabold border border-error/80",
      };
    case "punishment_knockdown":
      return {
        label: "KD",
        title: "Knockdown blow (punishment)",
        className: "bg-primary text-on-primary font-bold",
      };
    case "knockdown":
      return {
        label: "KD",
        title: "Knockdown blow",
        className: "bg-primary text-on-primary font-bold",
      };
    case "punishment_stun":
      return {
        label: "P-STUN",
        title: "Punishment stun",
        className: "bg-on-primary-container text-primary font-bold",
      };
    case "stun":
      return {
        label: "STUN",
        title: "Stun blow",
        className: "bg-on-primary-container text-primary font-bold",
      };
    default:
      return null;
  }
}

export function PunchLogView({
  report,
  scope,
}: {
  report: FightAnalytics;
  scope: ScopeSelection;
}) {
  const [cornerFilter, setCornerFilter] = useState<"both" | "red" | "blue">("both");
  const [landedOnly, setLandedOnly] = useState(false);
  const [trajFilter, setTrajFilter] = useState("all");
  const [contextFilter, setContextFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("time");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);

  useEffect(() => {
    setPage(1);
  }, [scope, report.session.name]);

  const red = getFighter(report, "red");
  const blue = getFighter(report, "blue");
  const redName = red?.name ?? "Red";
  const blueName = blue?.name ?? "Blue";

  const { offense } = getScopeData(report, scope);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "time" ? "asc" : "desc");
    }
    setPage(1);
  }

  const hasActiveFilters =
    cornerFilter !== "both" || landedOnly || trajFilter !== "all" || contextFilter !== "all";

  function resetFilters() {
    setCornerFilter("both");
    setLandedOnly(false);
    setTrajFilter("all");
    setContextFilter("all");
    setPage(1);
  }

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

  const impactSummary = useMemo(() => {
    let kd = 0;
    let ko = 0;
    let tko = 0;
    for (const p of allPunches) {
      if (p.hit_kind === "knockdown" || p.hit_kind === "punishment_knockdown") kd += 1;
      else if (p.hit_kind === "knockout") ko += 1;
      else if (p.hit_kind === "tko") tko += 1;
    }
    const parts: string[] = [];
    if (kd > 0) parts.push(`${kd} KD`);
    if (ko > 0) parts.push(`${ko} KO`);
    if (tko > 0) parts.push(`${tko} TKO`);
    return { total: kd + ko + tko, label: parts.join(" · ") };
  }, [allPunches]);

  const filtered = useMemo(() => {
    return allPunches.filter((p) => {
      if (cornerFilter !== "both" && p.color !== cornerFilter) return false;
      if (landedOnly && !p.landed) return false;
      if (trajFilter !== "all" && p.trajectory !== trajFilter) return false;
      if (contextFilter === "opponent_stunned" && !p.opponent_stunned) return false;
      if (contextFilter === "self_stunned" && !p.self_stunned) return false;
      if (contextFilter === "opponent_hurt" && !p.opponent_hurt) return false;
      if (contextFilter === "self_hurt" && !p.self_hurt) return false;
      if (contextFilter === "exchange" && !p.in_exchange) return false;
      if (contextFilter === "clinch" && p.range_zone !== "clinch") return false;
      if (contextFilter === "pocket" && p.range_zone !== "pocket") return false;
      if (contextFilter === "outside" && p.range_zone !== "outside") return false;
      if (contextFilter === "kd_ko_tko" && !isKdOrStoppage(p.hit_kind)) return false;
      if (
        contextFilter === "stun" &&
        p.hit_kind !== "stun" &&
        p.hit_kind !== "punishment_stun"
      ) {
        return false;
      }
      return true;
    });
  }, [allPunches, cornerFilter, landedOnly, trajFilter, contextFilter]);

  const sorted = useMemo(() => {
    const mult = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sortKey === "time") return (a.t_sec - b.t_sec) * mult;
      const getVal = (p: (typeof filtered)[number]) => {
        if (sortKey === "speed") return p.speed;
        if (sortKey === "damage") return p.damage;
        return p.retraction_ms;
      };
      const va = getVal(a);
      const vb = getVal(b);
      if (va == null && vb == null) return a.t_sec - b.t_sec;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va - vb) * mult || a.t_sec - b.t_sec;
    });
  }, [filtered, sortKey, sortDir]);

  const pageSize = 40;
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const rows = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);
  const rangeStart = sorted.length === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const rangeEnd = (safePage - 1) * pageSize + rows.length;

  return (
    <div className="flex flex-col w-full space-y-space-lg text-on-surface">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md bg-surface-container-low p-space-md rounded-lg shadow-sm">
        <div>
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-primary text-[20px]" aria-hidden="true">
              list_alt
            </span>
            <h1 className="font-headline-md text-headline-md uppercase text-on-surface m-0">
              Complete Punch-by-Punch Telemetry Stream
            </h1>
          </div>
          <p className="font-label-data text-label-data text-outline m-0 mt-0.5">
            {sorted.length} matching records out of {allPunches.length} total punches in{" "}
            {scope === "all" ? "Full Bout" : `Round ${scope + 1}`}
          </p>
        </div>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={resetFilters}
            className="min-h-[34px] px-space-md py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-caps text-label-caps flex items-center gap-1.5 self-start lg:self-auto transition-colors"
          >
            <span className="material-symbols-outlined text-[15px]" aria-hidden="true">filter_alt_off</span>
            Reset Filters
          </button>
        )}
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
              aria-pressed={cornerFilter === val}
              onClick={() => {
                setCornerFilter(val);
                setPage(1);
              }}
              className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps transition-colors ${
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
            aria-pressed={landedOnly}
            onClick={() => {
              setLandedOnly((v) => !v);
              setPage(1);
            }}
            className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps transition-colors ${
              landedOnly
                ? "bg-on-tertiary-container text-tertiary font-bold"
                : "bg-surface-container-lowest text-outline hover:text-on-surface"
            }`}
          >
            Landed Only
          </button>

          {impactSummary.total > 0 && (
            <button
              type="button"
              aria-pressed={contextFilter === "kd_ko_tko"}
              onClick={() => {
                setContextFilter((cur) => (cur === "kd_ko_tko" ? "all" : "kd_ko_tko"));
                setPage(1);
              }}
              className={`min-h-[32px] px-space-sm py-1 rounded font-label-caps text-label-caps transition-colors ${
                contextFilter === "kd_ko_tko"
                  ? "bg-error text-on-error font-bold"
                  : "bg-error-container/30 text-error hover:bg-error-container/50 font-semibold"
              }`}
              title="Filter to punches that caused a knockdown, KO, or TKO"
            >
              {impactSummary.label}
            </button>
          )}
        </div>

        <div className="flex items-center gap-space-xs flex-wrap">
          <select
            aria-label="Filter punches by tactical context"
            value={contextFilter}
            onChange={(e) => {
              setContextFilter(e.target.value);
              setPage(1);
            }}
            className="min-h-[34px] bg-surface-container-lowest text-on-surface font-label-data text-label-data px-space-sm py-1.5 rounded outline-none cursor-pointer"
          >
            <option value="all">All Contexts</option>
            <option value="kd_ko_tko">Caused KD / KO / TKO</option>
            <option value="stun">Caused Stun</option>
            <option value="opponent_stunned">Opponent Stunned</option>
            <option value="self_stunned">Self Stunned</option>
            <option value="opponent_hurt">Opponent Hurt (Critical)</option>
            <option value="self_hurt">Self Hurt (Critical)</option>
            <option value="exchange">In Exchange</option>
            <option value="clinch">Clinch (&lt;0.85m)</option>
            <option value="pocket">Pocket (0.85–1.35m)</option>
            <option value="outside">Outside (&gt;1.35m)</option>
          </select>

          <select
            aria-label="Filter punches by strike trajectory"
            value={trajFilter}
            onChange={(e) => {
              setTrajFilter(e.target.value);
              setPage(1);
            }}
            className="min-h-[34px] bg-surface-container-lowest text-on-surface font-label-data text-label-data px-space-sm py-1.5 rounded outline-none cursor-pointer"
          >
            {trajectories.map((t) => (
              <option key={t} value={t}>
                {t === "all" ? "All Trajectories" : formatTrajectoryLabel(t)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-surface-container-low rounded-lg p-space-md shadow-sm overflow-x-auto">
        <table className="w-full text-left font-label-data text-label-data border-collapse">
          <thead>
            <tr className="bg-surface-container text-outline font-label-caps text-label-caps uppercase">
              <th
                className="p-space-sm"
                aria-sort={sortKey === "time" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <button
                  type="button"
                  onClick={() => toggleSort("time")}
                  className="inline-flex items-center gap-1 hover:text-on-surface uppercase"
                >
                  Time {sortKey === "time" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                </button>
              </th>
              <th className="p-space-sm">Fighter</th>
              <th className="p-space-sm">Hand</th>
              <th className="p-space-sm">Trajectory</th>
              <th
                className="p-space-sm text-right"
                aria-sort={sortKey === "speed" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <button
                  type="button"
                  onClick={() => toggleSort("speed")}
                  className="inline-flex items-center gap-1 hover:text-on-surface uppercase ml-auto"
                >
                  Speed {sortKey === "speed" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                </button>
              </th>
              <th className="p-space-sm">Outcome</th>
              <th className="p-space-sm">Context</th>
              <th
                className="p-space-sm text-right"
                aria-sort={sortKey === "damage" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <button
                  type="button"
                  onClick={() => toggleSort("damage")}
                  className="inline-flex items-center gap-1 hover:text-on-surface uppercase ml-auto"
                >
                  Damage {sortKey === "damage" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                </button>
              </th>
              <th className="p-space-sm text-right">Combo</th>
              <th className="p-space-sm text-right">Head Slip</th>
              <th
                className="p-space-sm text-right"
                aria-sort={sortKey === "return" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <button
                  type="button"
                  onClick={() => toggleSort("return")}
                  className="inline-flex items-center gap-1 hover:text-on-surface uppercase ml-auto"
                >
                  Return {sortKey === "return" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                </button>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-container">
            {rows.map((p, idx) => {
              const badge = hitKindBadge(p.hit_kind);
              const rowAccent = isStoppage(p.hit_kind)
                ? "bg-error-container/20 hover:bg-error-container/30"
                : isKdOrStoppage(p.hit_kind)
                  ? "bg-primary/10 hover:bg-primary/15"
                  : "hover:bg-surface-container-high/50";
              return (
              <tr key={`${p.corner}-${p.t_sec}-${idx}`} className={`${rowAccent} transition-colors`}>
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
                <td className="p-space-sm whitespace-nowrap">
                  {p.landed ? (
                    <span className="text-tertiary font-bold font-label-caps text-[10px] bg-tertiary-container/30 px-1.5 py-0.5 rounded">
                      LANDED
                    </span>
                  ) : (
                    <span className="text-outline font-label-caps text-[10px]">MISS</span>
                  )}
                  {badge && (
                    <span
                      title={badge.title}
                      className={`ml-1 font-label-caps text-[10px] px-1.5 py-0.5 rounded uppercase ${badge.className}`}
                    >
                      {badge.label}
                    </span>
                  )}
                  {p.graze && (
                    <span className="ml-1 text-outline font-label-caps text-[10px] bg-surface-container-high px-1 py-0.5 rounded">
                      GRAZE
                    </span>
                  )}
                  {p.countered && (
                    <span className="ml-1 text-error font-label-caps text-[10px] bg-error-container/40 px-1 py-0.5 rounded">
                      COUNTERED
                    </span>
                  )}
                </td>
                <td className="p-space-sm">
                  <div className="flex flex-wrap items-center gap-1">
                    {p.opponent_stunned && (
                      <span className="px-1.5 py-0.5 rounded font-label-caps text-[10px] font-bold bg-tertiary/20 text-tertiary">
                        OPP STUNNED
                      </span>
                    )}
                    {p.self_stunned && (
                      <span className="px-1.5 py-0.5 rounded font-label-caps text-[10px] font-bold bg-error-container/50 text-error">
                        SELF STUNNED
                      </span>
                    )}
                    {!p.opponent_stunned && p.opponent_hurt && (
                      <span className="px-1 py-0.5 rounded font-label-caps text-[10px] bg-tertiary/10 text-tertiary border border-tertiary/30">
                        OPP HURT
                      </span>
                    )}
                    {!p.self_stunned && p.self_hurt && (
                      <span className="px-1 py-0.5 rounded font-label-caps text-[10px] bg-error-container/25 text-error border border-error/30">
                        SELF HURT
                      </span>
                    )}
                    {p.in_exchange && (
                      <span className="px-1 py-0.5 rounded font-label-caps text-[10px] bg-secondary/15 text-secondary">
                        EXCHANGE
                      </span>
                    )}
                    {p.range_zone && (
                      <span
                        title={
                          p.fighter_distance_m != null
                            ? `Hip distance: ${p.fighter_distance_m.toFixed(2)} m`
                            : undefined
                        }
                        className="px-1 py-0.5 rounded font-label-caps text-[10px] bg-surface-container-high text-outline uppercase"
                      >
                        {p.range_zone}
                      </span>
                    )}
                  </div>
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
              );
            })}
          </tbody>
        </table>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-xs pt-space-md font-label-data text-label-data text-outline">
          <span>
            Showing {rangeStart}–{rangeEnd} of {sorted.length} · Page {safePage} of {totalPages}
          </span>
          <div className="flex items-center gap-space-xs">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="min-h-[32px] px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright disabled:opacity-40 text-on-surface"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="min-h-[32px] px-space-sm py-1 rounded bg-surface-container hover:bg-surface-bright disabled:opacity-40 text-on-surface"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
