"""Local HTTP API for session analytics."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from totf_analyzer.analytics.metrics import build_analytics
from totf_analyzer.models.analytics import FightAnalytics
from totf_analyzer.parser.metadata import bout_shorthand, fight_card, inspect_zip_metadata
from totf_analyzer.parser.session import load_session
from totf_analyzer.sync.quest import (
    DEFAULT_DEST_DIR as DEFAULT_GAME_RECORDINGS,
    SyncConfig,
    get_sync_status,
    run_sync,
)


def recordings_root() -> Path:
    return Path(os.environ.get("TOTF_RECORDINGS", "Recordings")).resolve()


def game_recordings_root() -> Path:
    raw = os.environ.get("TOTF_GAME_RECORDINGS")
    return Path(raw).expanduser() if raw else DEFAULT_GAME_RECORDINGS


class AnalyzeRequest(BaseModel):
    path: str


class ImportRequest(BaseModel):
    name: str


class SyncRunRequest(BaseModel):
    dry_run: bool = False
    ignore_ledger: bool = False
    ignore_age: bool = False
    resync: list[str] | None = None
    copy_to_library: bool = True


def _cache_key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def resolve_zip(path_str: str, root: Path | None = None) -> Path:
    raw = Path(path_str)
    root = (root or recordings_root()).resolve()
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        candidate = (root / raw).resolve()
        if not candidate.is_file():
            candidate = raw.resolve()
    if candidate.suffix.lower() != ".zip" or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"session zip not found: {path_str}")
    return candidate


def analyze_path(path: Path, cache: dict | None = None) -> FightAnalytics:
    key = _cache_key(path)
    if cache is not None and key in cache:
        return cache[key]
    try:
        report = build_analytics(load_session(path))
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if cache is not None:
        cache[key] = report
    return report


def _session_row(path: Path, imported: bool | None = None) -> dict:
    stat = path.stat()
    row = {"name": path.name, "size": stat.st_size, "modified": stat.st_mtime, **inspect_zip_metadata(path)}
    if imported is not None:
        row["imported"] = imported
    return row


def _filter_kind(rows: list[dict], kind: str | None) -> list[dict]:
    if kind is None or kind == "" or kind == "all":
        return rows
    if kind not in {"match", "training"}:
        raise HTTPException(status_code=400, detail="kind must be 'match', 'training', or 'all'")
    return [row for row in rows if row.get("session_kind") == kind]


def list_game_zips(game_root: Path, library: Path, kind: str | None = None) -> dict:
    root = game_root.expanduser().resolve()
    imported = {path.name for path in library.glob("*.zip")} if library.is_dir() else set()
    rows: list[dict] = []
    if root.is_dir():
        paths = [path for path in root.glob("*.zip") if path.is_file()]
        for path in sorted(paths, key=lambda item: item.name, reverse=True):
            rows.append(_session_row(path, path.name in imported))
    rows = _filter_kind(rows, kind)
    return {"directory": str(root), "available": root.is_dir(), "recordings": rows}


def import_game_zip(name: str, game_root: Path, library: Path) -> Path:
    if Path(name).name != name or not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="name must be a session zip file name")
    source_root = game_root.expanduser().resolve()
    source = (source_root / name).resolve()
    if not source.is_relative_to(source_root):
        raise HTTPException(status_code=400, detail="recording is outside the game folder")
    if not source.is_file():
        raise HTTPException(status_code=404, detail=f"session zip not found: {name}")
    library.mkdir(parents=True, exist_ok=True)
    library = library.resolve()
    dest = (library / name).resolve()
    if not dest.is_relative_to(library):
        raise HTTPException(status_code=400, detail="invalid destination")
    try:
        shutil.copy2(source, dest)
    except shutil.SameFileError:
        pass
    return dest


def _validate_resync_names(names: list[str] | None) -> list[str] | None:
    if names is None:
        return None
    for name in names:
        if Path(name).name != name or not name.lower().endswith(".zip"):
            raise HTTPException(
                status_code=400, detail=f"resync name must be a session zip file name: {name}"
            )
    return names


def create_app(
    recordings: Path | None = None,
    game_recordings: Path | None = None,
    sync_config: SyncConfig | None = None,
) -> FastAPI:
    root = (recordings or recordings_root()).resolve()
    game_root = game_recordings or game_recordings_root()
    app = FastAPI(title="TotF Analyzer", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.recordings = root
    app.state.cache = {}

    def _resolve_sync_config(*, copy_to_library: bool = True) -> SyncConfig:
        if sync_config is not None:
            if copy_to_library:
                return sync_config
            return SyncConfig(
                adb_bin=sync_config.adb_bin,
                serial=sync_config.serial,
                host=sync_config.host,
                remote_dir=sync_config.remote_dir,
                dest_dir=sync_config.dest_dir,
                library_dir=None,
                state_dir=sync_config.state_dir,
                lease_file=sync_config.lease_file,
                wifi_iface=sync_config.wifi_iface,
                subnet_prefix=sync_config.subnet_prefix,
                port=sync_config.port,
                min_age=sync_config.min_age,
            )
        return SyncConfig.from_env(
            dest_dir=game_root,
            library_dir=root if copy_to_library else None,
            copy_to_library=copy_to_library,
        )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "recordings": str(root)}

    @app.get("/api/sessions")
    def list_sessions(kind: str | None = None) -> list[dict]:
        root.mkdir(parents=True, exist_ok=True)
        rows = [_session_row(path) for path in sorted(root.glob("*.zip")) if path.is_file()]
        return _filter_kind(rows, kind)

    @app.get("/api/game-recordings")
    def game_recordings(kind: str | None = None) -> dict:
        return list_game_zips(game_root, root, kind=kind)

    @app.get("/api/sync/status")
    def sync_status() -> dict:
        return get_sync_status(_resolve_sync_config()).to_dict()

    @app.post("/api/sync/run")
    def sync_run(body: SyncRunRequest | None = None) -> dict:
        req = body or SyncRunRequest()
        resync = _validate_resync_names(req.resync)
        cfg = _resolve_sync_config(copy_to_library=req.copy_to_library)
        return run_sync(
            cfg,
            dry_run=req.dry_run,
            ignore_ledger=req.ignore_ledger,
            ignore_age=req.ignore_age,
            resync=resync,
            notify=True,
        ).to_dict()

    @app.post("/api/sessions/import")
    def import_session(body: ImportRequest) -> dict:
        path = import_game_zip(body.name, game_root, root)
        return _session_row(path)

    @app.post("/api/sessions/analyze")
    def analyze(body: AnalyzeRequest) -> FightAnalytics:
        path = resolve_zip(body.path, root)
        return analyze_path(path, app.state.cache)

    @app.get("/api/sessions/{name}/report")
    def report(name: str) -> FightAnalytics:
        path = resolve_zip(name, root)
        return analyze_path(path, app.state.cache)

    @app.post("/api/sessions/upload")
    async def upload(file: UploadFile) -> FightAnalytics:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="upload a .zip session recording")
        data = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        try:
            return analyze_path(temp_path, app.state.cache)
        finally:
            temp_path.unlink(missing_ok=True)

    dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    index = dist / "index.html"
    assets = dist / "assets"
    if index.is_file() and assets.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def index_page() -> FileResponse:
            return FileResponse(index)

    return app


app = create_app()
