import { useEffect, useState } from "react";
import type { FightAnalytics, GameListing, SessionRow } from "./types";
import {
  type ScopeSelection,
  type ViewId,
  clock,
  clockWhole,
  filenameWhen,
  formatWhen,
  getFighter,
  sessionSelectOptionLabel,
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

  const caption = [row.bout, when, ...notes].filter(Boolean).join(" · ");

  return (
    <div className="flex flex-col gap-0.5 w-full text-left">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="font-headline-sm text-body-md font-semibold text-on-surface">
          {lead && other ? `${lead} vs ${other}` : lead ?? other ?? row.name}
        </span>
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

  const [importOpen, setImportOpen] = useState(false);
  const [gameListing, setGameListing] = useState<GameListing | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/sessions")
      .then((res) => res.json())
      .then((rows: SessionRow[]) => {
        setSessions(rows);
        if (rows[0]) setSelected(rows[0].name);
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
    if (!importOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setImportOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [importOpen]);

  function openImport() {
    setImportOpen(true);
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
    const listed = await fetch("/api/sessions");
    if (listed.ok) setSessions(await listed.json());
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

  return (
    <div className="min-h-screen bg-surface text-on-surface">
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
            className="lg:hidden text-outline hover:text-on-surface"
            aria-label="Close navigation"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Bout Selector */}
        <div className="px-space-md py-space-sm bg-surface-container-lowest border-b border-surface-container">
          <label
            htmlFor="bout-select"
            className="font-label-caps text-label-caps text-outline uppercase px-space-xs mb-space-xs block"
          >
            Select Fight Bout ({sessions.length})
          </label>
          <div className="relative">
            <select
              id="bout-select"
              value={selected ?? ""}
              onChange={(e) => setSelected(e.target.value)}
              className="w-full bg-surface-container-high text-on-surface font-label-data text-label-data px-space-sm py-2 pr-7 rounded appearance-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-secondary truncate"
            >
              {sessions.length === 0 && <option value="">No recordings loaded</option>}
              {sessions.map((s) => (
                <option key={s.name} value={s.name}>
                  {sessionSelectOptionLabel(s)}
                </option>
              ))}
            </select>
            <span className="material-symbols-outlined absolute right-2 top-1/2 -translate-y-1/2 text-outline pointer-events-none text-[16px]">
              expand_more
            </span>
          </div>
        </div>

        {/* Analysis Views Navigation */}
        <div className="px-space-lg pt-space-md pb-space-xs">
          <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
            Analysis Views
          </span>
        </div>
        <nav className="px-space-md flex flex-col gap-space-xs">
          {NAV_ITEMS.map((item) => {
            const active = activeView === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setActiveView(item.id);
                  setMobileMenuOpen(false);
                }}
                className={`flex items-center px-space-md py-space-sm rounded transition-colors text-left font-headline-sm text-telemetry-metric-sm ${
                  active
                    ? "bg-surface-container-high text-primary font-bold"
                    : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
                }`}
              >
                <span className="material-symbols-outlined mr-space-sm text-[18px]">{item.icon}</span>
                {item.label}
              </button>
            );
          })}
        </nav>

        {/* Scrollable Session List for Fast Switching */}
        <div className="px-space-lg pt-space-md pb-space-xs">
          <span className="font-label-caps text-label-caps text-outline uppercase tracking-wider">
            Library Recordings
          </span>
        </div>
        <div className="flex-1 overflow-y-auto px-space-md space-y-1 pb-space-sm">
          {sessions.map((s) => {
            const isSel = s.name === selected;
            return (
              <button
                key={s.name}
                type="button"
                onClick={() => {
                  setSelected(s.name);
                  setMobileMenuOpen(false);
                }}
                className={`w-full p-space-xs rounded transition-colors ${
                  isSel
                    ? "bg-surface-container-high ring-1 ring-primary/40"
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
        <header className="sticky top-0 z-40 h-16 bg-surface/95 backdrop-blur-xl border-b border-surface-container px-space-md lg:px-space-gutter-desktop flex items-center justify-between gap-2">
          <div className="flex items-center gap-space-sm min-w-0">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="lg:hidden p-1 rounded bg-surface-container text-on-surface"
              aria-label="Open menu"
            >
              <span className="material-symbols-outlined">menu</span>
            </button>
            <div className="flex items-center gap-space-xs bg-surface-container px-space-md py-space-xs rounded truncate">
              <span className="material-symbols-outlined text-secondary text-[18px]">videocam</span>
              <span className="font-label-caps text-label-caps text-on-surface">BOUT RECORDING</span>
              {report?.session.venue && (
                <span className="font-label-data text-label-data text-outline hidden sm:inline">
                  · {report.session.venue}
                </span>
              )}
            </div>
            {report && (
              <div className="hidden xl:flex items-center gap-space-sm text-outline font-label-data text-label-data">
                <span className="w-2 h-2 rounded-full bg-secondary" />
                <span>Tick Base: {hz} Hz</span>
                <span className="text-surface-variant">|</span>
                <span>{report.session.source}</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-space-xs sm:gap-space-sm shrink-0">
            <button
              type="button"
              onClick={openImport}
              className="flex items-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-space-xs rounded font-label-data text-label-data transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">file_upload</span>
              <span className="hidden sm:inline">Import Recording</span>
            </button>

            <label className="flex items-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-space-xs rounded font-label-data text-label-data transition-colors cursor-pointer">
              <span className="material-symbols-outlined text-[16px]">folder_zip</span>
              <span className="hidden sm:inline">Open Zip</span>
              <input
                type="file"
                accept=".zip"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void onUpload(file);
                }}
              />
            </label>

            {report && (
              <button
                type="button"
                onClick={exportJson}
                className="flex items-center gap-space-xs bg-surface-container-high hover:bg-surface-bright text-on-surface px-space-sm py-space-xs rounded font-label-data text-label-data transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]">ios_share</span>
                <span className="hidden md:inline">Export JSON</span>
              </button>
            )}
          </div>
        </header>

        {/* SUB-HEADER FIGHTER ANCHOR & ROUND BAR */}
        {report && (
          <div className="sticky top-16 z-30 bg-surface-container-low border-b border-surface-container px-space-md lg:px-space-gutter-desktop py-space-sm flex flex-col md:flex-row md:items-center justify-between gap-space-sm shadow-sm">
            <div className="flex items-center gap-space-md flex-wrap">
              {/* Red Fighter */}
              <div className="flex items-center gap-space-sm">
                <span className="w-2.5 h-2.5 rounded bg-primary-container shadow-[0_0_10px_rgba(255,84,81,0.5)]" />
                <div>
                  <div className="flex items-center gap-space-xs">
                    <span className="font-headline-sm text-headline-sm text-on-surface">
                      {red?.name ?? "Red"}
                    </span>
                    <span className="font-label-caps text-label-caps text-primary bg-on-primary-container px-space-xs rounded">
                      RED
                    </span>
                  </div>
                  <span className="font-label-data text-label-data text-outline">
                    {[red?.stance, red?.height_m ? `${red.height_m.toFixed(2)}m` : null]
                      .filter(Boolean)
                      .join(" · ") || "Corner 2"}
                  </span>
                </div>
              </div>

              {/* Verdict Badge */}
              <div className="flex items-center gap-space-xs px-space-md py-space-xs bg-surface-container rounded">
                <span className="font-label-caps text-label-caps text-tertiary font-bold">VERDICT:</span>
                <span className="font-telemetry-metric-sm text-on-surface font-bold">
                  {verdictBadge(report)}
                </span>
              </div>

              {/* Blue Fighter */}
              <div className="flex items-center gap-space-sm">
                <div className="md:text-right">
                  <div className="flex items-center md:justify-end gap-space-xs">
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
                <span className="w-2.5 h-2.5 rounded bg-secondary shadow-[0_0_10px_rgba(76,215,246,0.5)]" />
              </div>
            </div>

            {/* Global Round Slice Selector */}
            <div className="flex items-center bg-surface-container p-space-xs rounded gap-space-xs overflow-x-auto">
              <button
                type="button"
                onClick={() => setScope("all")}
                className={`px-space-sm py-space-xs rounded font-label-data text-label-data whitespace-nowrap transition-colors ${
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
                  onClick={() => setScope(r.index)}
                  className={`px-space-sm py-space-xs rounded font-label-data text-label-data whitespace-nowrap transition-colors ${
                    scope === r.index
                      ? "bg-surface-bright text-on-surface font-semibold"
                      : "text-outline hover:text-on-surface hover:bg-surface-container-high"
                  }`}
                >
                  Round {r.index + 1}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* IMPORT MODAL */}
        {importOpen && (
          <div
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-start justify-center p-4 sm:p-8 overflow-y-auto"
            role="dialog"
            aria-label="Import recording"
          >
            <div className="bg-surface-container-low border border-surface-variant rounded-xl w-full max-w-2xl p-space-lg shadow-2xl my-8">
              <div className="flex items-start justify-between gap-space-md pb-space-md border-b border-surface-container">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface m-0">
                    Import Game Session Recording
                  </h2>
                  <p className="font-label-data text-label-data text-outline m-0 mt-1 break-all">
                    {formatPath(gameListing?.directory ?? "Steam Proton SessionRecordings folder")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setImportOpen(false)}
                  className="px-space-sm py-space-xs rounded bg-surface-container-high hover:bg-surface-bright text-on-surface font-label-data text-label-data"
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
                <ul className="divide-y divide-surface-container max-h-96 overflow-y-auto list-none p-0 m-0 mt-space-sm">
                  {gameListing.recordings.map((rec) => (
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
            </div>
          </div>
        )}

        {/* VIEWPORT BODY */}
        <main className="flex-1 w-full px-space-md lg:px-space-gutter-desktop py-space-lg">
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
            <SpatialHeatmapsView report={report} scope={scope} onSelectScope={setScope} />
          )}
          {report && activeView === "strike-telemetry" && (
            <CombinationsMatrixView report={report} scope={scope} onSelectScope={setScope} />
          )}
          {report && activeView === "kinetics-force" && (
            <KineticsForceView
              report={report}
              scope={scope}
              onSelectScope={setScope}
              onNavigate={setActiveView}
            />
          )}
          {report && activeView === "force-degradation" && <ForceDegradationView report={report} />}
          {report && activeView === "punch-log" && (
            <PunchLogView report={report} scope={scope} onSelectScope={setScope} />
          )}
        </main>
      </div>
    </div>
  );
}
