"""Wi-Fi-only sync engine for Thrill of the Fight 2 recordings (Quest 3 -> Spectator + Library).

Discovers a Quest 3 over Wi-Fi (mDNS, DHCP leases, ARP, or existing ADB sessions),
verifies the device serial (when configured) or Quest hardware identity, atomically
pulls new SessionRecordings/*.zip files into the Steam Spectator folder, validates zip
integrity, classifies training drills vs. matches, optionally auto-copies into the
TotF Analyzer Recordings library, and tracks synced filenames in an XDG state ledger
so recordings deleted locally are not re-downloaded.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import shutil
import socket
import subprocess
import time
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from totf_analyzer.parser.metadata import inspect_zip_metadata

DEFAULT_REMOTE_DIR = (
    "/sdcard/Android/data/com.HalfbrickStudios.TheThrilloftheFight2/files/SessionRecordings"
)
DEFAULT_DEST_DIR = (
    Path.home()
    / ".local/share/Steam/steamapps/compatdata/3279600/pfx/drive_c/users/steamuser"
    / "AppData/LocalLow/Halfbrick Studios/The Thrill of the Fight 2/SessionRecordings"
)
DEFAULT_LEASE_FILE = Path("/run/quest3-dhcp/dnsmasq.leases")
DEFAULT_ADB_PORT = 5555
DEFAULT_MIN_AGE_SECS = 15

TCP_PROBE_TIMEOUT_SECS = 1.0
ADB_CMD_TIMEOUT_SECS = 15.0
ADB_PULL_TIMEOUT_SECS = 300.0
REBOOT_HINT_COOLDOWN_SECS = 3600

QUEST_MODEL_MARKERS = ("quest", "oculus", "meta", "eureka")


def default_state_dir() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state).expanduser() if xdg_state else Path.home() / ".local/state"
    return base / "totf2-sync"


def default_config_env_file() -> Path:
    override = os.environ.get("TOTF_SYNC_ENV_FILE")
    if override:
        return Path(override).expanduser()
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    return base / "totf-analyzer/sync.env"


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file (ignoring comments and blank lines)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        key = key.strip()
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def _env_truthy(raw: str | None, *, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class SyncConfig:
    adb_bin: str | None = None
    serial: str | None = None
    host: str | None = None
    remote_dir: str = DEFAULT_REMOTE_DIR
    dest_dir: Path = field(default_factory=lambda: DEFAULT_DEST_DIR)
    library_dir: Path | None = None
    state_dir: Path = field(default_factory=default_state_dir)
    lease_file: Path = DEFAULT_LEASE_FILE
    wifi_iface: str | None = None
    subnet_prefix: str = ""
    port: int = DEFAULT_ADB_PORT
    min_age: int = DEFAULT_MIN_AGE_SECS

    @classmethod
    def from_env(
        cls,
        *,
        env_file: Path | None = None,
        adb_bin: str | None = None,
        serial: str | None = None,
        host: str | None = None,
        remote_dir: str | None = None,
        dest_dir: Path | str | None = None,
        library_dir: Path | str | None = None,
        copy_to_library: bool | None = None,
        state_dir: Path | str | None = None,
        lease_file: Path | str | None = None,
        wifi_iface: str | None = None,
        subnet_prefix: str | None = None,
        port: int | None = None,
        min_age: int | None = None,
    ) -> SyncConfig:
        file_vars = load_env_file(env_file or default_config_env_file())

        def get_var(name: str, *fallbacks: str) -> str | None:
            for key in (name, *fallbacks):
                val = os.environ.get(key)
                if val is not None and val != "":
                    return val
            for key in (name, *fallbacks):
                val = file_vars.get(key)
                if val is not None and val != "":
                    return val
            return None

        resolved_adb = adb_bin or get_var("TOTF_SYNC_ADB_BIN", "TOTF2_ADB_BIN")
        resolved_serial = serial if serial is not None else get_var("TOTF_SYNC_QUEST_SERIAL")
        if resolved_serial is not None:
            resolved_serial = resolved_serial.strip() or None
        resolved_host = host if host is not None else get_var("TOTF_SYNC_HOST")
        if resolved_host is not None:
            resolved_host = resolved_host.strip() or None
        resolved_remote = remote_dir or get_var("TOTF_SYNC_REMOTE_DIR") or DEFAULT_REMOTE_DIR

        if dest_dir is not None:
            resolved_dest = Path(dest_dir).expanduser()
        else:
            raw_dest = get_var("TOTF_SYNC_DEST_DIR", "TOTF_GAME_RECORDINGS")
            resolved_dest = Path(raw_dest).expanduser() if raw_dest else DEFAULT_DEST_DIR

        should_copy = (
            copy_to_library
            if copy_to_library is not None
            else _env_truthy(get_var("TOTF_SYNC_COPY_TO_LIBRARY"), default=True)
        )
        if not should_copy:
            resolved_library: Path | None = None
        elif library_dir is not None:
            resolved_library = Path(library_dir).expanduser()
        else:
            raw_lib = get_var("TOTF_SYNC_LIBRARY_DIR", "TOTF_RECORDINGS")
            resolved_library = Path(raw_lib).expanduser() if raw_lib else None

        if state_dir is not None:
            resolved_state = Path(state_dir).expanduser()
        else:
            raw_state = get_var("TOTF_SYNC_STATE_DIR")
            resolved_state = Path(raw_state).expanduser() if raw_state else default_state_dir()

        if lease_file is not None:
            resolved_lease = Path(lease_file).expanduser()
        else:
            raw_lease = get_var("TOTF_SYNC_LEASE_FILE")
            resolved_lease = Path(raw_lease).expanduser() if raw_lease else DEFAULT_LEASE_FILE

        resolved_iface = wifi_iface if wifi_iface is not None else get_var("TOTF_SYNC_WIFI_IFACE")
        if resolved_iface is not None:
            resolved_iface = resolved_iface.strip() or None

        resolved_subnet = (
            subnet_prefix
            if subnet_prefix is not None
            else (get_var("TOTF_SYNC_SUBNET_PREFIX") or "")
        ).strip()

        raw_port = get_var("TOTF_SYNC_ADB_PORT")
        resolved_port = port if port is not None else (int(raw_port) if raw_port else DEFAULT_ADB_PORT)

        raw_min_age = get_var("TOTF_SYNC_MIN_AGE")
        resolved_min_age = (
            min_age if min_age is not None else (int(raw_min_age) if raw_min_age else DEFAULT_MIN_AGE_SECS)
        )

        return cls(
            adb_bin=resolved_adb,
            serial=resolved_serial,
            host=resolved_host,
            remote_dir=resolved_remote,
            dest_dir=resolved_dest,
            library_dir=resolved_library,
            state_dir=resolved_state,
            lease_file=resolved_lease,
            wifi_iface=resolved_iface,
            subnet_prefix=resolved_subnet,
            port=resolved_port,
            min_age=resolved_min_age,
        )


@dataclass(frozen=True)
class WifiCandidate:
    ip: str
    port: int
    source: str

    @property
    def target(self) -> str:
        return f"{self.ip}:{self.port}"


@dataclass(frozen=True)
class RemoteRecording:
    name: str
    remote_path: str
    size: int
    mtime: int


@dataclass(frozen=True)
class CandidateDiagnostic:
    ip: str
    port: int
    target: str
    source: str
    status: str


@dataclass(frozen=True)
class PendingRecording:
    name: str
    size: int
    mtime: int


@dataclass(frozen=True)
class SyncedRecording:
    name: str
    size: int
    elapsed_sec: float
    session_kind: str = "match"
    is_training: bool = False
    match_type: str | None = None
    bout: str | None = None
    copied_to_library: bool = False


@dataclass
class SyncStatusResult:
    adb_available: bool
    adb_bin: str | None
    serial_expected: str | None
    dest_dir: str
    library_dir: str | None
    ledger_path: str
    ledger_count: int
    sync_in_progress: bool = False
    candidates: list[CandidateDiagnostic] = field(default_factory=list)
    connected_target: str | None = None
    connected_serial: str | None = None
    reboot_hint: str | None = None
    remote_total: int | None = None
    pending: list[PendingRecording] = field(default_factory=list)
    already_local: int = 0
    skipped_ledger: int = 0
    deferred_recent: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncRunResult:
    status: str
    connected_target: str | None = None
    connected_serial: str | None = None
    pulled: list[SyncedRecording] = field(default_factory=list)
    would_pull: list[PendingRecording] = field(default_factory=list)
    recorded_existing: int = 0
    skipped_ledger: int = 0
    deferred_recent: int = 0
    remote_total: int = 0
    missing_resync: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reboot_hint: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeedResult:
    added: int
    ledger_count: int
    seeded: list[str] = field(default_factory=list)
    dry_run: bool = False
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackfillResult:
    copied: int
    skipped: int
    dry_run: bool = False
    entries: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnableTcpipResult:
    ok: bool
    target: str | None = None
    serial: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def format_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def iso_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_adb_bin(override: str | None = None) -> str:
    if override:
        expanded = str(Path(override).expanduser())
        if Path(expanded).is_file():
            return expanded
        found_override = shutil.which(override)
        if found_override:
            return found_override
        raise FileNotFoundError(f"adb binary not found: {override}")

    for env_key in ("TOTF_SYNC_ADB_BIN", "TOTF2_ADB_BIN"):
        env_adb = os.environ.get(env_key)
        if env_adb:
            expanded = str(Path(env_adb).expanduser())
            if Path(expanded).is_file():
                return expanded
            found_env = shutil.which(env_adb)
            if found_env:
                return found_env

    found = shutil.which("adb")
    if found:
        return found

    sdk_adb = Path.home() / "Android/Sdk/platform-tools/adb"
    if sdk_adb.is_file():
        return str(sdk_adb)

    raise FileNotFoundError(
        "adb binary not found in PATH or ~/Android/Sdk/platform-tools/adb "
        "(set TOTF_SYNC_ADB_BIN or pass --adb)"
    )


def run_adb(
    adb_bin: str,
    args: list[str],
    *,
    timeout: float = ADB_CMD_TIMEOUT_SECS,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [adb_bin, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def parse_host_arg(host_arg: str, default_port: int = DEFAULT_ADB_PORT) -> WifiCandidate:
    host_arg = host_arg.strip()
    if ":" in host_arg:
        ip_part, port_part = host_arg.rsplit(":", 1)
        return WifiCandidate(ip=ip_part, port=int(port_part), source="explicit")
    return WifiCandidate(ip=host_arg, port=default_port, source="explicit")


def _matches_subnet(ip: str, subnet_prefix: str) -> bool:
    return not subnet_prefix or ip.startswith(subnet_prefix)


def discover_mdns_candidates(adb_bin: str, subnet_prefix: str) -> list[WifiCandidate]:
    candidates: list[WifiCandidate] = []
    try:
        proc = run_adb(adb_bin, ["mdns", "services"], timeout=5.0)
    except (OSError, subprocess.TimeoutExpired):
        return candidates
    if proc.returncode != 0:
        return candidates

    pattern = re.compile(r"(\d+\.\d+\.\d+\.\d+):(\d+)")
    for line in proc.stdout.splitlines():
        if "_adb-tls-connect._tcp" not in line and "_adb._tcp" not in line:
            continue
        match = pattern.search(line)
        if not match:
            continue
        ip, port_str = match.group(1), match.group(2)
        if _matches_subnet(ip, subnet_prefix):
            candidates.append(WifiCandidate(ip=ip, port=int(port_str), source="mdns"))
    return candidates


def discover_dhcp_lease_candidates(
    lease_file: Path, subnet_prefix: str, port: int
) -> list[WifiCandidate]:
    if not lease_file.is_file():
        return []
    leases: list[tuple[int, str]] = []
    try:
        for line in lease_file.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            expiry_raw, _mac, ip = parts[0], parts[1], parts[2]
            if not _matches_subnet(ip, subnet_prefix):
                continue
            try:
                expiry = int(expiry_raw)
            except ValueError:
                expiry = 0
            leases.append((expiry, ip))
    except OSError:
        return []

    leases.sort(key=lambda item: item[0], reverse=True)
    return [WifiCandidate(ip=ip, port=port, source="dhcp-lease") for _, ip in leases]


def discover_arp_candidates(
    wifi_iface: str | None, subnet_prefix: str, port: int
) -> list[WifiCandidate]:
    if not wifi_iface and not subnet_prefix:
        return []
    cmd = ["ip", "-4", "neigh", "show"]
    if wifi_iface:
        cmd.extend(["dev", wifi_iface])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []

    state_rank = {"REACHABLE": 0, "DELAY": 1, "PROBE": 2, "STALE": 3}
    entries: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        ip = parts[0]
        if not _matches_subnet(ip, subnet_prefix):
            continue
        state = parts[-1] if len(parts) >= 2 else ""
        if state in {"FAILED", "INCOMPLETE"}:
            continue
        entries.append((state_rank.get(state, 9), ip))

    entries.sort(key=lambda item: item[0])
    return [WifiCandidate(ip=ip, port=port, source="arp") for _, ip in entries]


def discover_existing_adb_wifi_candidates(
    adb_bin: str, subnet_prefix: str
) -> list[WifiCandidate]:
    candidates: list[WifiCandidate] = []
    try:
        proc = run_adb(adb_bin, ["devices"], timeout=5.0)
    except (OSError, subprocess.TimeoutExpired):
        return candidates
    if proc.returncode != 0:
        return candidates

    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if state == "device" and ":" in serial:
            ip, port_str = serial.rsplit(":", 1)
            if port_str.isdigit() and _matches_subnet(ip, subnet_prefix):
                candidates.append(
                    WifiCandidate(ip=ip, port=int(port_str), source="adb-connected")
                )
    return candidates


def discover_wifi_candidates(
    adb_bin: str,
    *,
    explicit_host: str | None,
    lease_file: Path,
    wifi_iface: str | None,
    subnet_prefix: str,
    default_port: int,
) -> list[WifiCandidate]:
    if explicit_host:
        return [parse_host_arg(explicit_host, default_port)]

    raw: list[WifiCandidate] = []
    raw.extend(discover_mdns_candidates(adb_bin, subnet_prefix))
    raw.extend(discover_dhcp_lease_candidates(lease_file, subnet_prefix, default_port))
    raw.extend(discover_arp_candidates(wifi_iface, subnet_prefix, default_port))
    raw.extend(discover_existing_adb_wifi_candidates(adb_bin, subnet_prefix))

    seen: set[tuple[str, int]] = set()
    unique: list[WifiCandidate] = []
    for cand in raw:
        key = (cand.ip, cand.port)
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    return unique


def probe_tcp(ip: str, port: int, timeout: float = TCP_PROBE_TIMEOUT_SECS) -> str:
    """Return 'open', 'refused', or 'unreachable'."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        return "open"
    except ConnectionRefusedError:
        return "refused"
    except TimeoutError:
        return "unreachable"
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            return "refused"
        return "unreachable"
    finally:
        sock.close()


def cleanup_stale_wifi_adb_entries(
    adb_bin: str, subnet_prefix: str, keep_target: str | None = None
) -> None:
    """Disconnect offline or stale Quest-subnet ADB endpoints without touching other devices."""
    if not subnet_prefix:
        return
    try:
        proc = run_adb(adb_bin, ["devices"], timeout=5.0)
    except (OSError, subprocess.TimeoutExpired):
        return
    if proc.returncode != 0:
        return

    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if not serial.startswith(subnet_prefix) or ":" not in serial:
            continue
        if serial == keep_target and state == "device":
            continue
        if state in {"offline", "unauthorized"} or (keep_target and serial != keep_target):
            try:
                run_adb(adb_bin, ["disconnect", serial], timeout=5.0)
            except (OSError, subprocess.TimeoutExpired):
                pass


def _is_quest_device(adb_bin: str, target: str) -> bool:
    try:
        proc = run_adb(
            adb_bin,
            [
                "-s",
                target,
                "shell",
                "getprop ro.product.model; getprop ro.product.manufacturer; getprop ro.product.name",
            ],
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = proc.stdout.lower()
    return any(marker in text for marker in QUEST_MODEL_MARKERS)


def connect_and_verify_wifi_quest(
    adb_bin: str,
    candidates: list[WifiCandidate],
    expected_serial: str | None,
    subnet_prefix: str,
) -> tuple[WifiCandidate | None, str | None, list[CandidateDiagnostic]]:
    """Probe candidates, connect via ADB, and verify serial (or Quest identity)."""
    diagnostics: list[CandidateDiagnostic] = []

    for cand in candidates:
        probe_result = probe_tcp(cand.ip, cand.port)
        if probe_result != "open":
            diagnostics.append(
                CandidateDiagnostic(cand.ip, cand.port, cand.target, cand.source, probe_result)
            )
            continue

        try:
            conn_proc = run_adb(adb_bin, ["connect", cand.target], timeout=10.0)
        except (OSError, subprocess.TimeoutExpired):
            diagnostics.append(
                CandidateDiagnostic(
                    cand.ip, cand.port, cand.target, cand.source, "adb-connect-timeout"
                )
            )
            continue

        if conn_proc.returncode != 0:
            diagnostics.append(
                CandidateDiagnostic(
                    cand.ip,
                    cand.port,
                    cand.target,
                    cand.source,
                    f"adb-connect-failed: {conn_proc.stdout.strip()}",
                )
            )
            continue

        try:
            state_proc = run_adb(adb_bin, ["-s", cand.target, "get-state"], timeout=8.0)
        except (OSError, subprocess.TimeoutExpired):
            diagnostics.append(
                CandidateDiagnostic(
                    cand.ip, cand.port, cand.target, cand.source, "adb-state-timeout"
                )
            )
            continue

        state = state_proc.stdout.strip()
        if state != "device":
            err = (state_proc.stderr or state_proc.stdout).strip()
            diagnostics.append(
                CandidateDiagnostic(
                    cand.ip, cand.port, cand.target, cand.source, f"adb-state:{state or err}"
                )
            )
            continue

        try:
            serial_proc = run_adb(
                adb_bin,
                ["-s", cand.target, "shell", "getprop", "ro.serialno"],
                timeout=8.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            diagnostics.append(
                CandidateDiagnostic(
                    cand.ip, cand.port, cand.target, cand.source, "serial-check-timeout"
                )
            )
            continue

        actual_serial = serial_proc.stdout.strip()
        if expected_serial:
            if actual_serial != expected_serial:
                diagnostics.append(
                    CandidateDiagnostic(
                        cand.ip,
                        cand.port,
                        cand.target,
                        cand.source,
                        f"serial-mismatch:{actual_serial or 'empty'}",
                    )
                )
                try:
                    run_adb(adb_bin, ["disconnect", cand.target], timeout=5.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                continue
        elif not _is_quest_device(adb_bin, cand.target):
            diagnostics.append(
                CandidateDiagnostic(
                    cand.ip, cand.port, cand.target, cand.source, "not-a-quest-device"
                )
            )
            continue

        cleanup_stale_wifi_adb_entries(adb_bin, subnet_prefix, keep_target=cand.target)
        diagnostics.append(
            CandidateDiagnostic(cand.ip, cand.port, cand.target, cand.source, "verified")
        )
        return cand, actual_serial or None, diagnostics

    cleanup_stale_wifi_adb_entries(adb_bin, subnet_prefix, keep_target=None)
    return None, None, diagnostics


def list_remote_recordings(
    adb_bin: str, target: str, remote_dir: str
) -> tuple[int, list[RemoteRecording]]:
    """Return (remote_now_epoch, sorted list of RemoteRecording)."""
    shell_cmd = (
        f'date +%s; '
        f'for f in "{remote_dir}"/*.zip; do '
        f'[ -f "$f" ] && stat -c "%s %Y %n" "$f"; '
        f'done'
    )
    proc = run_adb(adb_bin, ["-s", target, "shell", shell_cmd], timeout=20.0)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to list remote recordings on {target}: {proc.stderr.strip() or proc.stdout.strip()}"
        )

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Empty response listing remote recordings on {target}")

    try:
        remote_now = int(lines[0])
    except ValueError as exc:
        raise RuntimeError(f"Unexpected remote clock output: {lines[0]!r}") from exc

    recordings: list[RemoteRecording] = []
    for line in lines[1:]:
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        size_str, mtime_str, remote_path = parts
        try:
            size = int(size_str)
            mtime = int(mtime_str)
        except ValueError:
            continue
        name = Path(remote_path).name
        if not name.lower().endswith(".zip"):
            continue
        recordings.append(
            RemoteRecording(
                name=name,
                remote_path=remote_path,
                size=size,
                mtime=mtime,
            )
        )

    recordings.sort(key=lambda rec: (rec.mtime, rec.name))
    return remote_now, recordings


def load_ledger(ledger_path: Path) -> dict[str, Any]:
    if not ledger_path.is_file():
        return {"version": 1, "files": {}}
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to parse ledger {ledger_path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"version": 1, "files": {}}
    return data


def save_ledger(ledger_path: Path, ledger: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ledger_path.with_suffix(".json.tmp")
    payload = json.dumps(ledger, indent=2, sort_keys=True) + "\n"
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, ledger_path)


def get_staging_dir(dest_dir: Path, state_dir: Path) -> Path:
    """Prefer a hidden sibling dir on the same filesystem as dest_dir for atomic os.replace()."""
    sibling = dest_dir.parent / ".totf2-sync-staging"
    try:
        sibling.mkdir(parents=True, exist_ok=True)
        return sibling
    except OSError:
        fallback = state_dir / "staging"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _atomic_replace(src_tmp: Path, dest_dir: Path, dest_path: Path) -> None:
    try:
        os.replace(src_tmp, dest_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        fallback_tmp = dest_dir / f".{dest_path.name}.{os.getpid()}.part"
        try:
            shutil.copy2(src_tmp, fallback_tmp)
            os.replace(fallback_tmp, dest_path)
        finally:
            if fallback_tmp.exists():
                fallback_tmp.unlink()


def atomic_copy_zip(
    source_path: Path, target_dir: Path, filename: str, state_dir: Path, mtime: int | None = None
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = get_staging_dir(target_dir, state_dir)
    tmp_path = staging_dir / f"{filename}.{os.getpid()}.copy.part"
    dest_path = target_dir / filename
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        shutil.copy2(source_path, tmp_path)
        if mtime is not None:
            os.utime(tmp_path, (mtime, mtime))
        _atomic_replace(tmp_path, target_dir, dest_path)
        return dest_path
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        try:
            staging_dir.rmdir()
        except OSError:
            pass


def pull_and_install_recording(
    adb_bin: str,
    target: str,
    rec: RemoteRecording,
    dest_dir: Path,
    state_dir: Path,
    library_dir: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = get_staging_dir(dest_dir, state_dir)
    tmp_path = staging_dir / f"{rec.name}.{os.getpid()}.part"
    dest_path = dest_dir / rec.name

    try:
        if tmp_path.exists():
            tmp_path.unlink()

        proc = run_adb(
            adb_bin,
            ["-s", target, "pull", rec.remote_path, str(tmp_path)],
            timeout=ADB_PULL_TIMEOUT_SECS,
        )
        if proc.returncode != 0 or not tmp_path.is_file():
            detail = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"adb pull failed for {rec.name}: {detail}")

        actual_size = tmp_path.stat().st_size
        if actual_size != rec.size:
            raise RuntimeError(
                f"Size mismatch for {rec.name}: expected {rec.size} bytes, got {actual_size}"
            )

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                if not zf.infolist():
                    raise RuntimeError(f"Empty zip archive: {rec.name}")
                bad_member = zf.testzip()
                if bad_member is not None:
                    raise RuntimeError(
                        f"Corrupt zip member {bad_member!r} in {rec.name}"
                    )
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"Invalid zip file {rec.name}: {exc}") from exc

        meta = inspect_zip_metadata(tmp_path)
        os.utime(tmp_path, (rec.mtime, rec.mtime))
        _atomic_replace(tmp_path, dest_dir, dest_path)

        copied_path: Path | None = None
        if library_dir is not None:
            resolved_dest = dest_dir.expanduser().resolve()
            resolved_lib = library_dir.expanduser().resolve()
            if resolved_lib != resolved_dest:
                copied_path = atomic_copy_zip(
                    dest_path, resolved_lib, rec.name, state_dir, mtime=rec.mtime
                )
            else:
                copied_path = dest_path

        return dest_path, copied_path, meta
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        try:
            staging_dir.rmdir()
        except OSError:
            pass


def should_emit_reboot_hint(state_dir: Path) -> bool:
    hint_file = state_dir / "last_reboot_hint.txt"
    now = time.time()
    try:
        last = float(hint_file.read_text(encoding="utf-8").strip())
        if (now - last) < REBOOT_HINT_COOLDOWN_SECS:
            return False
    except (OSError, ValueError):
        pass
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        hint_file.write_text(f"{now:.0f}\n", encoding="utf-8")
    except OSError:
        pass
    return True


def clear_reboot_hint(state_dir: Path) -> None:
    hint_file = state_dir / "last_reboot_hint.txt"
    try:
        if hint_file.exists():
            hint_file.unlink()
    except OSError:
        pass


def send_desktop_notification(pulled: list[SyncedRecording]) -> None:
    if not pulled or not shutil.which("notify-send"):
        return
    count = len(pulled)
    matches = sum(1 for item in pulled if not item.is_training)
    training = count - matches
    if matches and training:
        summary = f"Synced {count} recordings ({matches} match, {training} training)"
    elif training == count:
        summary = f"Synced {count} training recording" if count == 1 else f"Synced {count} training recordings"
    else:
        summary = f"Synced {count} new recording" if count == 1 else f"Synced {count} new recordings"
    names = [item.name for item in pulled]
    body = ", ".join(names[:3])
    if count > 3:
        body += f" (+{count - 3} more)"
    try:
        subprocess.run(
            ["notify-send", "-a", "TOTF Analyzer Sync", summary, body],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


@contextmanager
def _sync_lock(state_dir: Path) -> Iterator[bool]:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "sync.lock"
    lock_file = lock_path.open("w", encoding="utf-8")
    acquired = False
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        try:
            if acquired:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def _is_sync_locked(state_dir: Path) -> bool:
    lock_path = state_dir / "sync.lock"
    if not lock_path.exists():
        return False
    try:
        with lock_path.open("r+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def _plan_recordings(
    recordings: list[RemoteRecording],
    *,
    remote_now: int,
    dest_dir: Path,
    files_map: dict[str, Any],
    min_age: int,
    ignore_age: bool,
    ignore_ledger: bool,
    resync_set: set[str],
) -> tuple[
    list[RemoteRecording],
    list[RemoteRecording],
    list[RemoteRecording],
    list[RemoteRecording],
    list[str],
]:
    to_pull: list[RemoteRecording] = []
    existing_to_record: list[RemoteRecording] = []
    skipped_ledger: list[RemoteRecording] = []
    skipped_recent: list[RemoteRecording] = []

    for rec in recordings:
        if resync_set and rec.name not in resync_set:
            continue

        age = remote_now - rec.mtime
        if not ignore_age and age < min_age:
            skipped_recent.append(rec)
            continue

        forcing = rec.name in resync_set
        local_path = dest_dir / rec.name
        if not forcing and local_path.is_file() and local_path.stat().st_size == rec.size:
            if rec.name not in files_map:
                existing_to_record.append(rec)
            continue

        if not forcing and not ignore_ledger and rec.name in files_map:
            skipped_ledger.append(rec)
            continue

        to_pull.append(rec)

    missing_resync: list[str] = []
    if resync_set:
        found_names = {rec.name for rec in recordings}
        missing_resync = sorted(resync_set - found_names)

    return to_pull, existing_to_record, skipped_ledger, skipped_recent, missing_resync


def _reboot_hint_text(target_ip: str, port: int) -> str:
    return (
        f"Quest 3 is reachable on Wi-Fi ({target_ip}) but ADB port {port} refused connection "
        "(headset likely rebooted). Connect USB once and run: totf-analyzer sync --enable-tcpip"
    )


def get_sync_status(
    config: SyncConfig,
    *,
    ignore_ledger: bool = False,
    ignore_age: bool = False,
    resync: list[str] | None = None,
) -> SyncStatusResult:
    state_dir = config.state_dir.expanduser()
    dest_dir = config.dest_dir.expanduser()
    library_dir = config.library_dir.expanduser() if config.library_dir else None
    ledger_path = state_dir / "synced.json"

    try:
        ledger = load_ledger(ledger_path)
    except RuntimeError as exc:
        return SyncStatusResult(
            adb_available=False,
            adb_bin=config.adb_bin,
            serial_expected=config.serial,
            dest_dir=str(dest_dir),
            library_dir=str(library_dir) if library_dir else None,
            ledger_path=str(ledger_path),
            ledger_count=0,
            sync_in_progress=_is_sync_locked(state_dir),
            error=str(exc),
        )

    files_map: dict[str, Any] = ledger["files"]
    try:
        adb_bin = resolve_adb_bin(config.adb_bin)
    except FileNotFoundError as exc:
        return SyncStatusResult(
            adb_available=False,
            adb_bin=None,
            serial_expected=config.serial,
            dest_dir=str(dest_dir),
            library_dir=str(library_dir) if library_dir else None,
            ledger_path=str(ledger_path),
            ledger_count=len(files_map),
            sync_in_progress=_is_sync_locked(state_dir),
            error=str(exc),
        )

    candidates = discover_wifi_candidates(
        adb_bin,
        explicit_host=config.host,
        lease_file=config.lease_file,
        wifi_iface=config.wifi_iface,
        subnet_prefix=config.subnet_prefix,
        default_port=config.port,
    )
    verified, actual_serial, diagnostics = connect_and_verify_wifi_quest(
        adb_bin, candidates, config.serial, config.subnet_prefix
    )

    result = SyncStatusResult(
        adb_available=True,
        adb_bin=adb_bin,
        serial_expected=config.serial,
        dest_dir=str(dest_dir),
        library_dir=str(library_dir) if library_dir else None,
        ledger_path=str(ledger_path),
        ledger_count=len(files_map),
        sync_in_progress=_is_sync_locked(state_dir),
        candidates=diagnostics,
        connected_target=verified.target if verified else None,
        connected_serial=actual_serial,
    )

    if verified is None:
        refused = [diag for diag in diagnostics if diag.status == "refused"]
        if refused:
            result.reboot_hint = _reboot_hint_text(refused[0].ip, refused[0].port)
        return result

    try:
        remote_now, recordings = list_remote_recordings(adb_bin, verified.target, config.remote_dir)
    except RuntimeError as exc:
        result.error = str(exc)
        return result

    to_pull, existing_to_record, skipped_ledger, skipped_recent, _ = _plan_recordings(
        recordings,
        remote_now=remote_now,
        dest_dir=dest_dir,
        files_map=files_map,
        min_age=config.min_age,
        ignore_age=ignore_age,
        ignore_ledger=ignore_ledger,
        resync_set=set(resync or []),
    )
    result.remote_total = len(recordings)
    result.pending = [PendingRecording(rec.name, rec.size, rec.mtime) for rec in to_pull]
    result.already_local = len(existing_to_record)
    result.skipped_ledger = len(skipped_ledger)
    result.deferred_recent = len(skipped_recent)
    return result


def run_sync(
    config: SyncConfig,
    *,
    dry_run: bool = False,
    ignore_ledger: bool = False,
    ignore_age: bool = False,
    resync: list[str] | None = None,
    notify: bool = True,
    quiet: bool = False,
) -> SyncRunResult:
    state_dir = config.state_dir.expanduser()
    dest_dir = config.dest_dir.expanduser()
    library_dir = config.library_dir.expanduser() if config.library_dir else None
    ledger_path = state_dir / "synced.json"

    try:
        adb_bin = resolve_adb_bin(config.adb_bin)
    except FileNotFoundError as exc:
        return SyncRunResult(status="error", errors=[str(exc)], message=str(exc))

    with _sync_lock(state_dir) as acquired:
        if not acquired:
            return SyncRunResult(
                status="locked",
                message="Another Quest sync instance is already running; skipping.",
            )

        try:
            ledger = load_ledger(ledger_path)
        except RuntimeError as exc:
            return SyncRunResult(status="error", errors=[str(exc)], message=str(exc))

        files_map: dict[str, Any] = ledger["files"]
        candidates = discover_wifi_candidates(
            adb_bin,
            explicit_host=config.host,
            lease_file=config.lease_file,
            wifi_iface=config.wifi_iface,
            subnet_prefix=config.subnet_prefix,
            default_port=config.port,
        )
        verified, actual_serial, diagnostics = connect_and_verify_wifi_quest(
            adb_bin, candidates, config.serial, config.subnet_prefix
        )

        if verified is None:
            refused = [diag for diag in diagnostics if diag.status == "refused"]
            if refused:
                hint = _reboot_hint_text(refused[0].ip, refused[0].port)
                emit_hint = (not quiet) or should_emit_reboot_hint(state_dir)
                return SyncRunResult(
                    status="unreachable",
                    reboot_hint=hint if emit_hint else None,
                    message=hint,
                )
            if not candidates:
                msg = "Quest 3 not detected on Wi-Fi (no mDNS/DHCP/ARP candidate)."
            else:
                tried = ", ".join(f"{diag.target}={diag.status}" for diag in diagnostics)
                msg = f"Quest 3 unreachable over Wi-Fi ({tried})."
            return SyncRunResult(status="unreachable", message=msg)

        clear_reboot_hint(state_dir)

        try:
            remote_now, recordings = list_remote_recordings(
                adb_bin, verified.target, config.remote_dir
            )
        except RuntimeError as exc:
            return SyncRunResult(
                status="error",
                connected_target=verified.target,
                connected_serial=actual_serial,
                errors=[str(exc)],
                message=str(exc),
            )

        resync_set = set(resync or [])
        to_pull, existing_to_record, skipped_ledger, skipped_recent, missing_resync = (
            _plan_recordings(
                recordings,
                remote_now=remote_now,
                dest_dir=dest_dir,
                files_map=files_map,
                min_age=config.min_age,
                ignore_age=ignore_age,
                ignore_ledger=ignore_ledger,
                resync_set=resync_set,
            )
        )

        if existing_to_record and not dry_run:
            for rec in existing_to_record:
                meta = inspect_zip_metadata(dest_dir / rec.name)
                files_map[rec.name] = {
                    "size": rec.size,
                    "mtime": rec.mtime,
                    "synced_at": iso_now_utc(),
                    "source": "existing",
                    "session_kind": meta["session_kind"],
                    "is_training": meta["is_training"],
                    "match_type": meta["match_type"],
                    "bout": meta["bout"],
                }
            save_ledger(ledger_path, ledger)

        if not to_pull:
            return SyncRunResult(
                status="up_to_date",
                connected_target=verified.target,
                connected_serial=actual_serial,
                recorded_existing=len(existing_to_record),
                skipped_ledger=len(skipped_ledger),
                deferred_recent=len(skipped_recent),
                remote_total=len(recordings),
                missing_resync=missing_resync,
                message=(
                    f"Up to date via {verified.target} "
                    f"({len(recordings)} on Quest, {len(skipped_ledger)} skipped via ledger, "
                    f"{len(skipped_recent)} deferred)."
                ),
            )

        if dry_run:
            return SyncRunResult(
                status="dry_run",
                connected_target=verified.target,
                connected_serial=actual_serial,
                would_pull=[PendingRecording(rec.name, rec.size, rec.mtime) for rec in to_pull],
                recorded_existing=len(existing_to_record),
                skipped_ledger=len(skipped_ledger),
                deferred_recent=len(skipped_recent),
                remote_total=len(recordings),
                missing_resync=missing_resync,
                message=f"[dry-run] Would pull {len(to_pull)} recording(s) from {verified.target}.",
            )

        pulled: list[SyncedRecording] = []
        errors: list[str] = []
        for rec in to_pull:
            try:
                t0 = time.monotonic()
                _dest_path, copied_path, meta = pull_and_install_recording(
                    adb_bin,
                    verified.target,
                    rec,
                    dest_dir,
                    state_dir,
                    library_dir=library_dir,
                )
                elapsed = round(time.monotonic() - t0, 2)
                copied_to_library = copied_path is not None
                files_map[rec.name] = {
                    "size": rec.size,
                    "mtime": rec.mtime,
                    "synced_at": iso_now_utc(),
                    "source": "wifi",
                    "session_kind": meta["session_kind"],
                    "is_training": meta["is_training"],
                    "match_type": meta["match_type"],
                    "bout": meta["bout"],
                    "copied_to_library": copied_to_library,
                }
                save_ledger(ledger_path, ledger)
                pulled.append(
                    SyncedRecording(
                        name=rec.name,
                        size=rec.size,
                        elapsed_sec=elapsed,
                        session_kind=meta["session_kind"],
                        is_training=bool(meta["is_training"]),
                        match_type=meta["match_type"],
                        bout=meta["bout"],
                        copied_to_library=copied_to_library,
                    )
                )
            except Exception as exc:
                errors.append(f"Error syncing {rec.name}: {exc}")

        if pulled and notify:
            send_desktop_notification(pulled)

        status = "error" if errors and not pulled else "synced"
        message = (
            f"Synced {len(pulled)} recording(s) via {verified.target}"
            + (f" ({len(errors)} error(s))" if errors else ".")
        )
        return SyncRunResult(
            status=status,
            connected_target=verified.target,
            connected_serial=actual_serial,
            pulled=pulled,
            recorded_existing=len(existing_to_record),
            skipped_ledger=len(skipped_ledger),
            deferred_recent=len(skipped_recent),
            remote_total=len(recordings),
            missing_resync=missing_resync,
            errors=errors,
            message=message,
        )


def seed_existing(config: SyncConfig, *, dry_run: bool = False) -> SeedResult:
    state_dir = config.state_dir.expanduser()
    dest_dir = config.dest_dir.expanduser()
    ledger_path = state_dir / "synced.json"

    with _sync_lock(state_dir) as acquired:
        if not acquired:
            return SeedResult(
                added=0,
                ledger_count=0,
                dry_run=dry_run,
                error="Another Quest sync instance is already running.",
            )
        if not dest_dir.is_dir():
            return SeedResult(
                added=0,
                ledger_count=0,
                dry_run=dry_run,
                error=f"Destination directory does not exist: {dest_dir}",
            )

        ledger = load_ledger(ledger_path)
        files_map: dict[str, Any] = ledger["files"]
        seeded: list[str] = []

        for path in sorted(dest_dir.glob("*.zip")):
            if not path.is_file() or path.name in files_map:
                continue
            st = path.stat()
            meta = inspect_zip_metadata(path)
            files_map[path.name] = {
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "synced_at": iso_now_utc(),
                "source": "existing",
                "session_kind": meta["session_kind"],
                "is_training": meta["is_training"],
                "match_type": meta["match_type"],
                "bout": meta["bout"],
            }
            seeded.append(path.name)

        if seeded and not dry_run:
            save_ledger(ledger_path, ledger)
        return SeedResult(
            added=len(seeded),
            ledger_count=len(files_map),
            seeded=seeded,
            dry_run=dry_run,
            message=(
                f"{'[dry-run] Would seed' if dry_run else 'Seeded'} {len(seeded)} existing "
                f"local recording(s); ledger has {len(files_map)} entries."
            ),
        )


def seed_remote(config: SyncConfig, *, dry_run: bool = False) -> SeedResult:
    state_dir = config.state_dir.expanduser()
    ledger_path = state_dir / "synced.json"

    try:
        adb_bin = resolve_adb_bin(config.adb_bin)
    except FileNotFoundError as exc:
        return SeedResult(added=0, ledger_count=0, dry_run=dry_run, error=str(exc))

    with _sync_lock(state_dir) as acquired:
        if not acquired:
            return SeedResult(
                added=0,
                ledger_count=0,
                dry_run=dry_run,
                error="Another Quest sync instance is already running.",
            )

        ledger = load_ledger(ledger_path)
        files_map: dict[str, Any] = ledger["files"]
        candidates = discover_wifi_candidates(
            adb_bin,
            explicit_host=config.host,
            lease_file=config.lease_file,
            wifi_iface=config.wifi_iface,
            subnet_prefix=config.subnet_prefix,
            default_port=config.port,
        )
        verified, _, _ = connect_and_verify_wifi_quest(
            adb_bin, candidates, config.serial, config.subnet_prefix
        )
        if verified is None:
            return SeedResult(
                added=0,
                ledger_count=len(files_map),
                dry_run=dry_run,
                error="Quest 3 unreachable over Wi-Fi.",
            )

        _, recordings = list_remote_recordings(adb_bin, verified.target, config.remote_dir)
        seeded: list[str] = []
        for rec in recordings:
            if rec.name in files_map:
                continue
            files_map[rec.name] = {
                "size": rec.size,
                "mtime": rec.mtime,
                "synced_at": iso_now_utc(),
                "source": "seeded",
            }
            seeded.append(rec.name)

        if seeded and not dry_run:
            save_ledger(ledger_path, ledger)
        return SeedResult(
            added=len(seeded),
            ledger_count=len(files_map),
            seeded=seeded,
            dry_run=dry_run,
            message=(
                f"{'[dry-run] Would seed' if dry_run else 'Seeded'} {len(seeded)} remote "
                f"recording(s); ledger has {len(files_map)} entries."
            ),
        )


def backfill_library(
    config: SyncConfig, *, dry_run: bool = False, matches_only: bool = False
) -> BackfillResult:
    """Copy local Steam Spectator recordings missing from the analyzer library."""
    state_dir = config.state_dir.expanduser()
    dest_dir = config.dest_dir.expanduser()
    library_dir = config.library_dir.expanduser() if config.library_dir else None

    if library_dir is None:
        return BackfillResult(
            copied=0,
            skipped=0,
            dry_run=dry_run,
            error="No library directory configured (set TOTF_RECORDINGS or pass --library-dir).",
        )
    if not dest_dir.is_dir():
        return BackfillResult(
            copied=0,
            skipped=0,
            dry_run=dry_run,
            error=f"Spectator directory does not exist: {dest_dir}",
        )

    with _sync_lock(state_dir) as acquired:
        if not acquired:
            return BackfillResult(
                copied=0,
                skipped=0,
                dry_run=dry_run,
                error="Another Quest sync instance is already running.",
            )

        resolved_dest = dest_dir.resolve()
        resolved_lib = library_dir.resolve()
        if resolved_dest == resolved_lib:
            return BackfillResult(
                copied=0,
                skipped=0,
                dry_run=dry_run,
                message="Spectator and library directories are identical; nothing to backfill.",
            )

        copied = 0
        skipped = 0
        entries: list[dict[str, Any]] = []
        for path in sorted(resolved_dest.glob("*.zip")):
            if not path.is_file():
                continue
            target = resolved_lib / path.name
            meta = inspect_zip_metadata(path)
            if matches_only and meta["is_training"]:
                skipped += 1
                continue
            if target.is_file() and target.stat().st_size == path.stat().st_size:
                skipped += 1
                continue
            if not dry_run:
                atomic_copy_zip(path, resolved_lib, path.name, state_dir, mtime=int(path.stat().st_mtime))
            copied += 1
            entries.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "session_kind": meta["session_kind"],
                    "is_training": meta["is_training"],
                    "bout": meta["bout"],
                }
            )
        return BackfillResult(
            copied=copied,
            skipped=skipped,
            dry_run=dry_run,
            entries=entries,
            message=(
                f"{'[dry-run] Would backfill' if dry_run else 'Backfilled'} {copied} recording(s) "
                f"into {resolved_lib} ({skipped} skipped)."
            ),
        )


def enable_tcpip(config: SyncConfig) -> EnableTcpipResult:
    state_dir = config.state_dir.expanduser()
    try:
        adb_bin = resolve_adb_bin(config.adb_bin)
    except FileNotFoundError as exc:
        return EnableTcpipResult(ok=False, message=str(exc))

    with _sync_lock(state_dir) as acquired:
        if not acquired:
            return EnableTcpipResult(
                ok=False, message="Another Quest sync instance is already running."
            )

        target_args = ["-s", config.serial] if config.serial else ["-d"]
        state_proc = run_adb(adb_bin, [*target_args, "get-state"], timeout=10.0)
        if state_proc.returncode != 0 or state_proc.stdout.strip() != "device":
            detail = (state_proc.stderr or state_proc.stdout).strip()
            label = config.serial or "USB Quest 3"
            return EnableTcpipResult(
                ok=False,
                serial=config.serial,
                message=f"Quest 3 USB device ({label}) is not ready: {detail}",
            )

        serial_proc = run_adb(
            adb_bin, [*target_args, "shell", "getprop", "ro.serialno"], timeout=8.0
        )
        actual_serial = serial_proc.stdout.strip() or config.serial

        ip_proc = run_adb(
            adb_bin,
            [*target_args, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
            timeout=10.0,
        )
        ip_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", ip_proc.stdout)
        quest_ip = ip_match.group(1) if ip_match else None

        tcpip_proc = run_adb(
            adb_bin, [*target_args, "tcpip", str(config.port)], timeout=15.0
        )
        if tcpip_proc.returncode != 0:
            detail = (tcpip_proc.stderr or tcpip_proc.stdout).strip()
            return EnableTcpipResult(
                ok=False,
                serial=actual_serial,
                message=f"adb tcpip {config.port} failed: {detail}",
            )

        deadline = time.monotonic() + 8.0
        explicit_host = f"{quest_ip}:{config.port}" if quest_ip else None
        while time.monotonic() < deadline:
            time.sleep(1.0)
            candidates = discover_wifi_candidates(
                adb_bin,
                explicit_host=explicit_host,
                lease_file=config.lease_file,
                wifi_iface=config.wifi_iface,
                subnet_prefix=config.subnet_prefix,
                default_port=config.port,
            )
            verified, verified_serial, _ = connect_and_verify_wifi_quest(
                adb_bin, candidates, actual_serial, config.subnet_prefix
            )
            if verified is not None:
                return EnableTcpipResult(
                    ok=True,
                    target=verified.target,
                    serial=verified_serial or actual_serial,
                    message=(
                        f"Verified Wi-Fi ADB ready at {verified.target} "
                        f"(serial {verified_serial or actual_serial}). You can now unplug USB."
                    ),
                )

        return EnableTcpipResult(
            ok=False,
            serial=actual_serial,
            message=(
                f"adb tcpip {config.port} succeeded, but Wi-Fi verification timed out"
                + (f" for {quest_ip}:{config.port}" if quest_ip else "")
                + ". Run `totf-analyzer sync --status` to check."
            ),
        )
