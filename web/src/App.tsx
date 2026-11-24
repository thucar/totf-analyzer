import { useEffect, useRef, useState } from "react";
import type { FightAnalytics, GameListing, SessionRow, SyncRunResult, SyncStatus } from "./types";
import {
  type ScopeSelection,
  type ViewId,
  clock,
  clockWhole,
  filenameWhen,
  formatBytesMb,
  formatWhen,
  getFighter,
  isTrainingSession,
  verdictBadge,
} from "./utils";
import { CombinationsMatrixView } from "./views/CombinationsMatrixView";
import { FightSummaryView } from "./views/FightSummaryView";
import { ForceDegradationView } from "./views/ForceDegradationView";
import { KineticsForceView } from "./views/KineticsForceView";
import { PunchLogView } from "./views/PunchLogView";
import { SpatialHeatmapsView } from "./views/SpatialHeatmapsView";

const NAV_ITEMS: { id: ViewId; label: string; icon: string }[] = [
  { id: "fight-summary", label: "Fight Summary", icon: "analytics" },
  { id: "spatial-heatmaps", label: "Spatial Heatmaps", icon: "radar" },
  { id: "strike-telemetry", label: "Combinations Matrix", icon: "hub" },
  { id: "kinetics-force", label: "Kinetics & Force", icon: "fitness_center" },
  { id: "force-degradation", label: "Force Degradation", icon: "ecg_heart" },
  { id: "punch-log", label: "Punch Log", icon: "list_alt" },
];

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* non-json error */
  }
  return text || "Request failed.";
}

function formatPath(path: string): string {
  return path.replaceAll("/", "/\u200b");
}

function RecordingCardRow({
  row,
  notes = [],
}: {
  row: SessionRow;
  notes?: string[];
}) {
  const when = formatWhen(row.created) || filenameWhen(row.name);
  const subject = row.local ?? row.winner ?? (row.red ? "red" : row.blue ? "blue" : null);
  const lead = subject === "blue" ? row.blue : subject === "red" ? row.red : null;
  const other = subject === "blue" ? row.red : subject === "red" ? row.blue : null;
  const tone = row.result?.startsWith("W")
    ? "bg-secondary/20 text-secondary"
    : row.result?.startsWith("L")
      ? "bg-error-container text-error"
      : "bg-surface-container-highest text-on-surface";

  const training = isTrainingSession(row);
  const caption = [row.bout, when, ...notes].filter(Boolean).join(" · ");

  return (
    <div className="flex flex-col gap-0.5 w-full text-left">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="font-headline-sm text-body-md font-semibold text-on-surface">
          {lead && other ? `${lead} vs ${other}` : lead ?? other ?? row.name}
        </span>
        {training && (
          <span className="px-1.5 py-0.5 rounded font-label-caps text-[10px] font-bold bg-tertiary/20 text-tertiary">
            TRAINING
          </span>
        )}
        {row.result && (
          <span className={`px-1.5 py-0.5 rounded font-label-caps text-[10px] font-bold ${tone}`}>
            {row.result}
          </span>
        )}
      </div>
      {caption && <span className="font-label-data text-[11px] text-outline">{caption}</span>}
    </div>
  );
}

export function App() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<FightAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportToken, setReportToken] = useState(0);

  const [activeView, setActiveView] = useState<ViewId>("fight-summary");
  const [scope, setScope] = useState<ScopeSelection>("all");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const [kindFilter, setKindFilter] = useState<"match" | "training" | "all">("match");
  const [sessionSearch, setSessionSearch] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importKindFilter, setImportKindFilter] = useState<"all" | "match" | "training">("all");
  const [gameListing, setGameListing] = useState<GameListing | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState<string | null>(null);

  const [syncOpen, setSyncOpen] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncRunning, setSyncRunning] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncRunResult | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const importCloseRef = useRef<HTMLButtonElement | null>(null);
  const syncCloseRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    fetch("/api/sessions")
      .then((res) => res.json())
      .then((rows: SessionRow[]) => {
        setSessions(rows);
        const firstMatch = rows.find((r) => !isTrainingSession(r));
        if (firstMatch) {
          setSelected(firstMatch.name);
        } else if (rows[0]) {
          setKindFilter("all");
          setSelected(rows[0].name);
        }
      })
      .catch(() => setError("Could not list recordings. Start totf-analyzer serve."));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setError(null);
    setLoading(true);
    fetch(`/api/sessions/${encodeURIComponent(selected)}/report`)
      .then(async (res) => {
        if (!res.ok) throw new Error(await readError(res));
        return res.json();
      })
      .then((body: FightAnalytics) => {
        setReport(body);
        setScope("all");
      })
      .catch((exc: Error) => setError(exc.message))
      .finally(() => setLoading(false));
  }, [selected, reportToken]);

  useEffect(() => {
    if (!importOpen && !syncOpen && !mobileMenuOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setImportOpen(false);
        setSyncOpen(false);
        setMobileMenuOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [importOpen, syncOpen, mobileMenuOpen]);

  useEffect(() => {
    if (importOpen) {
      importCloseRef.current?.focus();
    }
  }, [importOpen]);

  useEffect(() => {
    if (syncOpen) {
      syncCloseRef.current?.focus();
    }
  }, [syncOpen]);

  function openImport() {
    setImportOpen(true);
    setImportKindFilter("all");
    setImportError(null);
    setGameListing(null);
    fetch("/api/game-recordings")
      .then(async (res) => {
        if (!res.ok) throw new Error(await readError(res));
        return res.json();
      })
      .then((body: GameListing) => setGameListing(body))
      .catch((exc: Error) => setImportError(exc.message));
  }

  async function refreshSyncStatus() {
    setSyncLoading(true);
    setSyncError(null);
    try {
      const res = await fetch("/api/sync/status");
      if (!res.ok) throw new Error(await readError(res));
      setSyncStatus((await res.json()) as SyncStatus);
    } catch (exc) {
      setSyncError(exc instanceof Error ? exc.message : "Failed to inspect Quest 3 sync status.");
    } finally {
      setSyncLoading(false);
    }
  }

  function openSync() {
    setSyncOpen(true);
    setSyncResult(null);
    void refreshSyncStatus();
  }

  async function runQuestSync() {
    setSyncRunning(true);
    setSyncError(null);
    setSyncResult(null);
    try {
      const res = await fetch("/api/sync/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ copy_to_library: true }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const body = (await res.json()) as SyncRunResult;
      setSyncResult(body);
      if (body.pulled.length > 0) {
        const listed = await fetch("/api/sessions");
        if (listed.ok) {
          const updated = (await listed.json()) as SessionRow[];
          setSessions(updated);
          const newest = body.pulled[body.pulled.length - 1];
          if (newest?.copied_to_library && !selected) {
            setSelected(newest.name);
            setReportToken((t) => t + 1);
          }
        }
      }
      await refreshSyncStatus();
    } catch (exc) {
      setSyncError(exc instanceof Error ? exc.message : "Quest 3 sync failed.");
    } finally {
      setSyncRunning(false);
    }
  }

  async function onImport(name: string) {
    setImporting(name);
    setImportError(null);
    const res = await fetch("/api/sessions/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      setImportError(await readError(res));
      setImporting(null);
      return;
    }
    const importedRow = (await res.json()) as SessionRow;
    const listed = await fetch("/api/sessions");
    if (listed.ok) setSessions(await listed.json());
    if (isTrainingSession(importedRow) && kindFilter === "match") {
      setKindFilter("training");
    } else if (!isTrainingSession(importedRow) && kindFilter === "training") {
      setKindFilter("match");
    }
    setSelected(name);
    setReportToken((t) => t + 1);
    setImporting(null);
    setImportOpen(false);
  }

  async function onUpload(file: File) {
    const form = new FormData();
    form.append("file", file);
    setError(null);
    setLoading(true);
    const res = await fetch("/api/sessions/upload", { method: "POST", body: form });
    setLoading(false);
    if (!res.ok) {
      setError(await readError(res));
      return;
    }
    const uploaded: FightAnalytics = await res.json();
    setReport(uploaded);
    setScope("all");
  }

  function exportJson() {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.session.name || "totf_report"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const red = report ? getFighter(report, "red") : undefined;
  const blue = report ? getFighter(report, "blue") : undefined;
  const completedRounds = report ? report.rounds.filter((r) => r.completed) : [];
  const hz = report?.session.fixed_timestep ? Math.round(1 / report.session.fixed_timestep) : 120;
  const reportIsTraining = Boolean(
    report?.session.is_training || report?.session.session_kind === "training",
  );

  const matchCount = sessions.filter((s) => !isTrainingSession(s)).length;
  const trainingCount = sessions.length - matchCount;
  const sessionQuery = sessionSearch.trim().toLowerCase();
  const visibleSessions = sessions.filter((s) => {
    if (kindFilter === "match" && isTrainingSession(s)) return false;
    if (kindFilter === "training" && !isTrainingSession(s)) return false;
    if (!sessionQuery) return true;
    const when = formatWhen(s.created) || filenameWhen(s.name) || "";
    const haystack = [s.red, s.blue, s.result, s.bout, when, s.name]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(sessionQuery);
  });

  const gameRecordingsAll = gameListing?.recordings ?? [];
  const gameMatchCount = gameRecordingsAll.filter((r) => !isTrainingSession(r)).length;
  const gameTrainingCount = gameRecordingsAll.length - gameMatchCount;
  const visibleGameRecordings = gameRecordingsAll.filter((r) => {
    if (importKindFilter === "match") return !isTrainingSession(r);
    if (importKindFilter === "training") return isTrainingSession(r);
    return true;
  });

  return (
    <div className="min-h-screen bg-surface text-on-surface">
      {/* MOBILE DRAWER BACKDROP */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          aria-hidden="true"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* LEFT TELEMETRY RAIL */}
      <aside
        className={`fixed left-0 top-0 h-full w-72 bg-surface-container-lowest z-50 flex flex-col border-r border-surface-container-high transition-transform duration-200 ${
          mobileMenuOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="p-space-lg bg-surface-container-low flex items-center justify-between">
          <div className="flex items-center gap-space-sm">
            <div className="w-8 h-8 bg-primary-container text-on-primary-container rounded flex items-center justify-center font-display-hero text-telemetry-metric-sm font-bold">
              T
            </div>
            <div className="flex flex-col">
              <span className="font-headline-sm text-headline-sm uppercase tracking-tight text-on-surface">
                TOTF ANALYZER
              </span>
              <span className="font-label-caps text-label-caps text-secondary tracking-widest">
                VR COMBAT TELEMETRY
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setMobileMenuOpen(false)}
            className="lg:hidden min-h-[36px] min-w-[36px] flex items-center justify-center rounded text-outline hover:text-on-surface hover:bg-surface-container"
            aria-label="Close navigation"
          >
            <span className="material-symbols-outlined" aria-hidden="true">close</span>
          </button>
        </div>

        {/* Analysis Views Navigation */}
        <div className="px-space-lg pt-space-md pb-space-xs">
          <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
            Analysis Views
          </span>
        </div>
        <nav aria-label="Analysis views" className="px-space-md flex flex-col gap-space-xs">
          {NAV_ITEMS.map((item) => {
            const active = activeView === item.id;
            return (
              <button
                key={item.id}
                type="button"
                aria-current={active ? "page" : undefined}
                onClick={() => {
                  setActiveView(item.id);
                  setMobileMenuOpen(false);
                }}
                className={`flex items-center min-h-[36px] px-space-md py-space-sm rounded transition-colors text-left font-headline-sm text-telemetry-metric-sm ${
                  active
                    ? "bg-surface-container-high text-primary font-bold"
                    : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
                }`}
              >
                <span className="material-symbols-outlined mr-space-sm text-[18px]" aria-hidden="true">
                  {item.icon}
                </span>
                {item.label}
              </button>
            );
          })}
        </nav>

        {/* Bout Kind Filter & Searchable Session Library */}
        <div className="px-space-md pt-space-md pb-space-xs border-t border-surface-container mt-space-md space-y-space-xs">
          <div className="flex items-center justify-between px-space-xs">
            <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
              {kindFilter === "training"
                ? "Training Drills"
                : kindFilter === "match"
                  ? "Match Recordings"
                  : "Library Recordings"}
            </span>
            <span className="font-label-data text-[11px] text-outline">{visibleSessions.length}</span>
          </div>
          <div className="grid grid-cols-3 gap-1 bg-surface-container p-0.5 rounded">
            {(
              [
                { id: "match", label: `Matches (${matchCount})` },
                { id: "training", label: `Training (${trainingCount})` },
                { id: "all", label: `All (${sessions.length})` },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setKindFilter(tab.id)}
                className={`min-h-[32px] py-1 px-1 rounded font-label-caps text-[10px] transition-colors truncate ${
                  kindFilter === tab.id
                    ? "bg-surface-bright text-on-surface font-bold"
                    : "text-outline hover:text-on-surface"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="relative">
            <span
              className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-outline pointer-events-none text-[16px]"
              aria-hidden="true"
            >
              search
            </span>
            <input
              type="search"
              value={sessionSearch}
              onChange={(e) => setSessionSearch(e.target.value)}
              placeholder="Filter recordings…"
              aria-label="Filter recordings"
              className="w-full min-h-[34px] bg-surface-container-high text-on-surface placeholder:text-outline font-label-data text-label-data pl-8 pr-7 py-1.5 rounded focus:outline-none focus:ring-1 focus:ring-secondary"
            />
            {sessionSearch && (
              <button
                type="button"
                onClick={() => setSessionSearch("")}
                aria-label="Clear recording filter"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded text-outline hover:text-on-surface"
              >
                <span className="material-symbols-outlined text-[14px]" aria-hidden="true">close</span>
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-space-md space-y-1 pb-space-sm">
          {visibleSessions.length === 0 && (
            <p className="font-label-data text-[11px] text-outline px-space-xs py-space-sm">
              {sessionSearch
                ? "No recordings match your search."
                : kindFilter === "training"
                  ? "No training drills (1x0:35) in library."
                  : "No recordings match this filter."}
            </p>
          )}
          {visibleSessions.map((s) => {
            const isSel = s.name === selected;
            return (
              <button
                key={s.name}
                type="button"
                aria-pressed={isSel}
                onClick={() => {
                  setSelected(s.name);
                  setMobileMenuOpen(false);
                }}
                className={`w-full p-space-sm rounded transition-colors ${
                  isSel
                    ? "bg-surface-container-high ring-1 ring-primary/50"
                    : "hover:bg-surface-container"
                }`}
              >
                <RecordingCardRow row={s} />
              </button>
            );
          })}
        </div>

        {/* Bottom Session Telemetry Card */}
        <div className="p-space-md bg-surface-container-low border-t border-surface-container">
          <div className="bg-surface-container-lowest p-space-sm rounded flex flex-col gap-space-xs">
            <div className="flex items-center justify-between font-label-caps text-label-caps text-outline">
              <span>SESSION TELEMETRY</span>
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
            </div>
            <div className="font-label-data text-label-data text-on-surface truncate">
              {report?.session.venue ?? "No Venue"}
            </div>
            <div className="flex items-center justify-between font-label-data text-label-data text-outline">
              <span>
                {report
                  ? `${report.session.rounds_scheduled} × ${clockWhole(report.session.round_duration_sec)}`
                  : "—"}
              </span>
              <span className="text-tertiary">{report ? `${clock(report.session.duration_sec)} total` : "—"}</span>
            </div>
          </div>
        </div>
      </aside>

      {/* MAIN SHELL CONTENT */}
      <div className="lg:pl-72 flex flex-col min-h-screen">
        {/* TOP HEADER BAR */}
        <header className="sticky top-0 z-40 h-16 bg-surface/95 backdrop-blur-xl border-b border-surface-container px-space-md lg:px-space-gutter-desktop flex items-center justify-between gap-2 relative">
          {loading && report && (
            <div
              className="absolute bottom-0 left-0 right-0 h-0.5 bg-surface-container overflow-hidden"
              role="status"
              aria-label="Loading bout telemetry"
            >
              <div className="h-full w-1/3 bg-secondary animate-pulse" />
            </div>
          )}
          <div className="flex items-center gap-space-sm min-w-0">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="lg:hidden min-h-[36px] min-w-[36px] flex items-center justify-center rounded bg-surface-container text-on-surface"
              aria-label="Open menu"
            >
              <span className="material-symbols-outlined" aria-hidden="true">menu</span>
            </button>
            <div className="flex items-center gap-space-xs bg-surface-container px-space-md py-space-xs rounded truncate">
              <span className="material-symbols-outlined text-secondary text-[18px]" aria-hidden="true">
                videocam
              </span>
              <span className="font-label-caps text-label-caps text-on-surface">BOUT RECORDING</span>
              {report?.session.venue && (
                <span className="font-label-data text-label-data text-outline hidden sm:inline">
                  · {report.session.venue}
                </span>
              )}
            </div>
            {loading && report && (
              <span className="inline-flex items-center gap-1.5 px-space-sm py-1 rounded bg-secondary/15 text-secondary font-label-caps text-label-caps">
                <span className="w-2 h-2 rounded-full bg-secondary animate-ping" aria-hidden="true" />
                Decoding…
              </span>
            )}
            {report && !loading && (
              <div className="hidden xl:flex items-center gap-space-sm text-outline font-label-data text-label-data">
                <span className="w-2 h-2 rounded-full bg-secondary" aria-hidden="true" />
                <span>Tick Base: {hz} Hz</span>
                <span className="text-outline" aria-hidden="true">·</span>
                <span>{report.session.source}</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-space-xs sm:gap-space-sm shrink-0">
            <button
              type="button"
              onClick={openSync}
              aria-label="Quest Sync"
              title="Quest 3 Wi-Fi Sync"
              className="min-h-[36px] flex items-center justify-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-1.5 rounded font-label-data text-label-data transition-colors"
            >
              <span className="material-symbols-outlined text-[16px] text-secondary" aria-hidden="true">
                sync
              </span>
              <span className="hidden sm:inline">Quest Sync</span>
            </button>

            <button
              type="button"
              onClick={openImport}
              aria-label="Import Recording"
              title="Import Recording from Steam Spectator"
              className="min-h-[36px] flex items-center justify-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-1.5 rounded font-label-data text-label-data transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                file_upload
              </span>
              <span className="hidden sm:inline">Import Recording</span>
            </button>

            <button
              type="button"
              onClick={() => uploadInputRef.current?.click()}
              aria-label="Open Zip"
              title="Upload a .zip recording"
              className="min-h-[36px] flex items-center justify-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-1.5 rounded font-label-data text-label-data transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                folder_zip
              </span>
              <span className="hidden sm:inline">Open Zip</span>
            </button>
            <input
              ref={uploadInputRef}
              type="file"
              accept=".zip"
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void onUpload(file);
              }}
            />

            {report && (
              <button
                type="button"
                onClick={exportJson}
                aria-label="Export JSON"
                title="Download full analytics JSON"
                className="min-h-[36px] flex items-center justify-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-1.5 rounded font-label-data text-label-data transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                  ios_share
                </span>
                <span className="hidden md:inline">Export JSON</span>
              </button>
            )}
          </div>
        </header>

        {/* SUB-HEADER FIGHTER ANCHOR & ROUND BAR */}
        {report && (
          <div className="md:sticky md:top-16 z-30 bg-surface-container-low border-b border-surface-container px-space-md lg:px-space-gutter-desktop py-space-sm flex flex-col md:flex-row md:items-center justify-between gap-space-sm shadow-sm">
            <div className="flex items-center gap-space-md flex-wrap">
              {/* Red Fighter */}
              <div className="flex items-center gap-space-sm">
                <span
                  className="w-2.5 h-2.5 rounded bg-primary-container shadow-[0_0_10px_rgba(255,84,81,0.5)]"
                  aria-hidden="true"
                />
                <div>
                  <div className="flex items-center gap-space-xs">
                    <span className="font-headline-sm text-headline-sm text-on-surface">
                      {red?.name ?? "Red"}
                    </span>
                    <span className="font-label-caps text-label-caps text-primary bg-on-primary-container px-space-xs rounded">
                      RED
                    </span>
                    {red?.is_local_player && (
                      <span className="font-label-caps text-[10px] text-on-tertiary bg-tertiary px-1.5 py-0.2 rounded font-bold">
                        YOU
                      </span>
                    )}
                  </div>
                  <span className="font-label-data text-label-data text-outline">
                    {[red?.stance, red?.ai_archetype, red?.height_m ? `${red.height_m.toFixed(2)}m` : null]
                      .filter(Boolean)
                      .join(" · ") || "Corner 2"}
                  </span>
                </div>
              </div>

              {/* Verdict Badge */}
              <div className="flex items-center gap-space-xs px-space-md py-space-xs bg-surface-container rounded">
                {reportIsTraining && (
                  <span className="px-1.5 py-0.5 rounded font-label-caps text-[10px] font-bold bg-tertiary/20 text-tertiary">
                    TRAINING
                  </span>
                )}
                <span className="font-label-caps text-label-caps text-tertiary font-bold">VERDICT:</span>
                <span className="font-telemetry-metric-sm text-on-surface font-bold">
                  {verdictBadge(report)}
                </span>
              </div>

              {/* Blue Fighter */}
              <div className="flex items-center gap-space-sm">
                <div className="md:text-right">
                  <div className="flex items-center md:justify-end gap-space-xs">
                    {blue?.is_local_player && (
                      <span className="font-label-caps text-[10px] text-on-tertiary bg-tertiary px-1.5 py-0.2 rounded font-bold">
                        YOU
                      </span>
                    )}
                    <span className="font-label-caps text-label-caps text-secondary bg-on-secondary-container px-space-xs rounded">
                      BLUE
                    </span>
                    <span className="font-headline-sm text-headline-sm text-on-surface">
                      {blue?.name ?? "Blue"}
                    </span>
                  </div>
                  <span className="font-label-data text-label-data text-outline">
                    {[blue?.stance, blue?.ai_archetype, blue?.height_m ? `${blue.height_m.toFixed(2)}m` : null]
                      .filter(Boolean)
                      .join(" · ") || "Corner 1"}
                  </span>
                </div>
                <span
                  className="w-2.5 h-2.5 rounded bg-secondary shadow-[0_0_10px_rgba(76,215,246,0.5)]"
                  aria-hidden="true"
                />
              </div>
            </div>

            {/* Global Round Slice Selector (hidden on Force Degradation which compares a round pair) */}
            {activeView === "force-degradation" ? (
              <div className="flex items-center gap-space-xs bg-surface-container px-space-md py-1.5 rounded font-label-caps text-label-caps text-outline self-start md:self-auto">
                <span className="material-symbols-outlined text-[16px] text-tertiary" aria-hidden="true">
                  compare_arrows
                </span>
                <span>Comparing Round Pair</span>
              </div>
            ) : (
              <div
                className="flex items-center bg-surface-container p-1 rounded gap-space-xs overflow-x-auto"
                role="group"
                aria-label="Round scope selector"
              >
                <button
                  type="button"
                  aria-pressed={scope === "all"}
                  onClick={() => setScope("all")}
                  className={`min-h-[32px] px-space-sm py-1 rounded font-label-data text-label-data whitespace-nowrap transition-colors ${
                    scope === "all"
                      ? "bg-surface-bright text-on-surface font-semibold"
                      : "text-outline hover:text-on-surface hover:bg-surface-container-high"
                  }`}
                >
                  Full Bout
                </button>
                {completedRounds.map((r) => (
                  <button
                    key={r.index}
                    type="button"
                    aria-pressed={scope === r.index}
                    onClick={() => setScope(r.index)}
                    className={`min-h-[32px] px-space-sm py-1 rounded font-label-data text-label-data whitespace-nowrap transition-colors ${
                      scope === r.index
                        ? "bg-surface-bright text-on-surface font-semibold"
                        : "text-outline hover:text-on-surface hover:bg-surface-container-high"
                    }`}
                  >
                    R{r.index + 1} ({clockWhole(r.duration_sec)})
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* IMPORT MODAL */}
        {importOpen && (
          <div
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-start justify-center p-4 sm:p-8 overflow-y-auto"
            role="dialog"
            aria-modal="true"
            aria-labelledby="import-modal-title"
            onClick={(e) => {
              if (e.target === e.currentTarget) setImportOpen(false);
            }}
          >
            <div className="bg-surface-container-low border border-surface-variant rounded-xl w-full max-w-2xl p-space-lg shadow-2xl my-8">
              <div className="flex items-start justify-between gap-space-md pb-space-md border-b border-surface-container">
                <div>
                  <h2 id="import-modal-title" className="font-headline-md text-headline-md text-on-surface m-0">
                    Import Game Session Recording
                  </h2>
                  <p className="font-label-data text-label-data text-outline m-0 mt-1 break-all">
                    {formatPath(gameListing?.directory ?? "Steam Proton SessionRecordings folder")}
                  </p>
                </div>
                <button
                  ref={importCloseRef}
                  type="button"
                  onClick={() => setImportOpen(false)}
                  className="min-h-[34px] px-space-md py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-data text-label-data"
                >
                  Close
                </button>
              </div>

              {importError && <p className="text-error font-label-data py-space-md">{importError}</p>}
              {!gameListing && !importError && (
                <p className="text-outline font-label-data py-space-lg">Scanning game recordings folder…</p>
              )}
              {gameListing && !gameListing.available && (
                <p className="text-outline font-label-data py-space-lg">
                  The game recordings folder was not found on this machine.
                </p>
              )}
              {gameListing?.available && gameListing.recordings.length === 0 && (
                <p className="text-outline font-label-data py-space-lg">
                  No session zip recordings found in that directory.
                </p>
              )}

              {gameListing && gameListing.recordings.length > 0 && (
                <>
                  <div className="flex items-center gap-1 mt-space-md bg-surface-container p-1 rounded w-fit">
                    {(
                      [
                        { id: "all", label: `All (${gameRecordingsAll.length})` },
                        { id: "match", label: `Matches (${gameMatchCount})` },
                        { id: "training", label: `Training (${gameTrainingCount})` },
                      ] as const
                    ).map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setImportKindFilter(tab.id)}
                        className={`px-space-sm py-1 rounded font-label-caps text-[11px] transition-colors ${
                          importKindFilter === tab.id
                            ? "bg-surface-bright text-on-surface font-bold"
                            : "text-outline hover:text-on-surface"
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  {visibleGameRecordings.length === 0 ? (
                    <p className="text-outline font-label-data py-space-lg">
                      No recordings match this filter.
                    </p>
                  ) : (
                    <ul className="divide-y divide-surface-container max-h-96 overflow-y-auto list-none p-0 m-0 mt-space-sm">
                      {visibleGameRecordings.map((rec) => (
                        <li key={rec.name}>
                          <button
                            type="button"
                            disabled={importing !== null}
                            onClick={() => void onImport(rec.name)}
                            className="w-full py-space-sm px-space-xs hover:bg-surface-container transition-colors disabled:opacity-50"
                          >
                            <RecordingCardRow
                              row={rec}
                              notes={[
                                rec.imported ? "in library" : "",
                                importing === rec.name ? "importing…" : "",
                              ]}
                            />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* QUEST 3 SYNC MODAL */}
        {syncOpen && (
          <div
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-start justify-center p-4 sm:p-8 overflow-y-auto"
            role="dialog"
            aria-modal="true"
            aria-labelledby="sync-modal-title"
            onClick={(e) => {
              if (e.target === e.currentTarget) setSyncOpen(false);
            }}
          >
            <div className="bg-surface-container-low border border-surface-variant rounded-xl w-full max-w-2xl p-space-lg shadow-2xl my-8 space-y-space-md">
              <div className="flex items-start justify-between gap-space-md pb-space-md border-b border-surface-container">
                <div>
                  <h2 id="sync-modal-title" className="font-headline-md text-headline-md text-on-surface m-0">
                    Quest 3 Wi-Fi Sync
                  </h2>
                  <p className="font-label-data text-label-data text-outline m-0 mt-1">
                    Pulls new recordings into Steam Spectator and copies them into your Analyzer library.
                  </p>
                </div>
                <button
                  ref={syncCloseRef}
                  type="button"
                  onClick={() => setSyncOpen(false)}
                  className="min-h-[34px] px-space-md py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-data text-label-data"
                >
                  Close
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-space-sm">
                <button
                  type="button"
                  disabled={syncRunning || syncLoading}
                  onClick={() => void runQuestSync()}
                  className="min-h-[36px] flex items-center gap-space-xs px-space-md py-1.5 rounded bg-secondary text-on-secondary-container font-headline-sm text-label-data font-bold hover:opacity-90 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden="true">sync</span>
                  {syncRunning ? "Syncing…" : "Sync Now"}
                </button>
                <button
                  type="button"
                  disabled={syncRunning || syncLoading}
                  onClick={() => void refreshSyncStatus()}
                  className="min-h-[36px] flex items-center gap-space-xs px-space-md py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-data text-label-data disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden="true">refresh</span>
                  {syncLoading ? "Checking…" : "Check Status"}
                </button>
                {syncStatus && (
                  <span
                    className={`px-space-sm py-1 rounded font-label-caps text-[11px] font-bold ${
                      syncStatus.connected_target
                        ? "bg-secondary/20 text-secondary"
                        : syncStatus.error
                          ? "bg-error-container text-error"
                          : "bg-surface-container-high text-outline"
                    }`}
                  >
                    {syncStatus.connected_target
                      ? `CONNECTED ${syncStatus.connected_target}`
                      : syncStatus.sync_in_progress
                        ? "SYNC IN PROGRESS"
                        : syncStatus.error
                          ? "ERROR"
                          : "UNREACHABLE"}
                  </span>
                )}
              </div>

              {syncError && (
                <div className="bg-error-container/30 border border-error/40 text-error p-space-sm rounded font-label-data text-label-data">
                  {syncError}
                </div>
              )}

              {syncStatus?.reboot_hint && (
                <div className="bg-tertiary/15 border border-tertiary/40 text-tertiary p-space-sm rounded font-label-data text-label-data">
                  {syncStatus.reboot_hint}
                </div>
              )}

              {syncResult && (
                <div className="bg-surface-container p-space-md rounded space-y-space-xs">
                  <div className="font-label-caps text-label-caps text-secondary uppercase">
                    Last Sync Result ({syncResult.status})
                  </div>
                  <p className="font-label-data text-label-data text-on-surface m-0">
                    {syncResult.message}
                  </p>
                  {syncResult.pulled.length > 0 && (
                    <ul className="list-none p-0 m-0 pt-space-xs space-y-1">
                      {syncResult.pulled.map((item) => (
                        <li
                          key={item.name}
                          className="flex items-center justify-between gap-2 font-label-data text-[12px] text-on-surface bg-surface-container-low px-space-sm py-1 rounded"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span
                              className={`px-1.5 py-0.5 rounded font-label-caps text-[10px] font-bold shrink-0 ${
                                item.is_training
                                  ? "bg-tertiary/20 text-tertiary"
                                  : "bg-secondary/20 text-secondary"
                              }`}
                            >
                              {item.is_training ? "TRAINING" : "MATCH"}
                            </span>
                            <span className="truncate">{item.name}</span>
                            {item.bout && <span className="text-outline shrink-0">{item.bout}</span>}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-outline">{formatBytesMb(item.size)}</span>
                            {item.copied_to_library && (
                              <button
                                type="button"
                                onClick={() => {
                                  if (item.is_training && kindFilter === "match") {
                                    setKindFilter("training");
                                  } else if (!item.is_training && kindFilter === "training") {
                                    setKindFilter("match");
                                  }
                                  setSelected(item.name);
                                  setReportToken((t) => t + 1);
                                  setSyncOpen(false);
                                }}
                                className="px-2 py-0.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface text-[11px]"
                              >
                                Open
                              </button>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                  {syncResult.errors.length > 0 && (
                    <ul className="list-none p-0 m-0 pt-space-xs space-y-1 text-error font-label-data text-[12px]">
                      {syncResult.errors.map((errMsg, idx) => (
                        <li key={idx}>{errMsg}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {syncLoading && !syncStatus && (
                <p className="text-outline font-label-data py-space-sm">Probing Quest 3 over Wi-Fi…</p>
              )}

              {syncStatus && (
                <div className="space-y-space-sm font-label-data text-[12px]">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-xs bg-surface-container-lowest p-space-sm rounded">
                    <div>
                      <span className="text-outline">Ledger: </span>
                      <span className="text-on-surface">{syncStatus.ledger_count} tracked</span>
                    </div>
                    <div>
                      <span className="text-outline">Remote on Quest: </span>
                      <span className="text-on-surface">
                        {syncStatus.remote_total != null ? `${syncStatus.remote_total} zip(s)` : "—"}
                      </span>
                    </div>
                    <div className="sm:col-span-2 truncate">
                      <span className="text-outline">Spectator: </span>
                      <span className="text-on-surface">{formatPath(syncStatus.dest_dir)}</span>
                    </div>
                    {syncStatus.library_dir && (
                      <div className="sm:col-span-2 truncate">
                        <span className="text-outline">Library: </span>
                        <span className="text-on-surface">{formatPath(syncStatus.library_dir)}</span>
                      </div>
                    )}
                  </div>

                  {syncStatus.pending.length > 0 && (
                    <div className="space-y-1">
                      <div className="font-label-caps text-label-caps text-outline uppercase">
                        Pending Downloads ({syncStatus.pending.length})
                      </div>
                      <ul className="list-none p-0 m-0 divide-y divide-surface-container bg-surface-container-lowest rounded px-space-sm">
                        {syncStatus.pending.map((rec) => (
                          <li key={rec.name} className="py-1.5 flex items-center justify-between gap-2">
                            <span className="text-on-surface truncate">{rec.name}</span>
                            <span className="text-outline shrink-0">{formatBytesMb(rec.size)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {syncStatus.candidates.length > 0 && (
                    <div className="space-y-1">
                      <div className="font-label-caps text-label-caps text-outline uppercase">
                        Discovery Candidates
                      </div>
                      <ul className="list-none p-0 m-0 space-y-1">
                        {syncStatus.candidates.map((cand) => (
                          <li
                            key={`${cand.target}-${cand.source}`}
                            className="flex items-center justify-between text-[11px] bg-surface-container-lowest px-space-sm py-1 rounded"
                          >
                            <span className="text-on-surface">
                              {cand.target} <span className="text-outline">({cand.source})</span>
                            </span>
                            <span
                              className={
                                cand.status === "verified" ? "text-secondary" : "text-outline"
                              }
                            >
                              {cand.status}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* VIEWPORT BODY */}
        <main
          className={`flex-1 w-full px-space-md lg:px-space-gutter-desktop py-space-lg transition-opacity duration-150 ${
            loading && report ? "opacity-60 pointer-events-none" : ""
          }`}
          aria-busy={loading}
        >
          {error && (
            <div className="bg-error-container/30 border border-error/40 text-error p-space-md rounded-lg font-label-data mb-space-md">
              {error}
            </div>
          )}
          {loading && !report && (
            <div className="text-outline font-label-data py-16 text-center">
              Decoding T2SR telemetry streams…
            </div>
          )}
          {!loading && !report && !error && (
            <div className="text-outline font-label-data py-16 text-center">
              Select or import a Thrill of the Fight 2 session zip to inspect telemetry.
            </div>
          )}

          {report && activeView === "fight-summary" && (
            <FightSummaryView
              report={report}
              scope={scope}
              onSelectScope={setScope}
              onNavigate={setActiveView}
            />
          )}
          {report && activeView === "spatial-heatmaps" && (
            <SpatialHeatmapsView report={report} scope={scope} />
          )}
          {report && activeView === "strike-telemetry" && (
            <CombinationsMatrixView report={report} scope={scope} />
          )}
          {report && activeView === "kinetics-force" && (
            <KineticsForceView report={report} scope={scope} onNavigate={setActiveView} />
          )}
          {report && activeView === "force-degradation" && <ForceDegradationView report={report} />}
          {report && activeView === "punch-log" && <PunchLogView report={report} scope={scope} />}
        </main>
      </div>
    </div>
  );
}
