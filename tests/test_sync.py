"""Unit tests for Quest 3 Wi-Fi sync, training classification, API sync routes, and MCP sync tools."""

from __future__ import annotations

import fcntl
import json
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from totf_analyzer.api.app import create_app
from totf_analyzer.parser.metadata import classify_session, inspect_zip_metadata
from totf_analyzer.sync import quest


def _make_session_zip(
    path: Path,
    *,
    rounds: int = 3,
    round_seconds: float = 120.0,
    match_type: str = "MatchSingleplayer",
    activity_type: str = "MatchSingleplayer",
    red_name: str = "Red Fighter",
    blue_name: str = "Blue Fighter",
) -> Path:
    meta = {
        "m_createdUtc": "2026-11-24T04:01:57.3348830Z",
        "m_matchType": match_type,
        "m_activityType": activity_type,
        "m_venue": {"m_rounds": rounds, "m_roundDurationSeconds": round_seconds},
        "m_tracks": [
            {"m_corner": 1, "m_boxerName": blue_name, "m_isLocalPlayer": True},
            {"m_corner": 2, "m_boxerName": red_name, "m_isLocalPlayer": False},
        ],
        "m_scoring": {
            "m_completedRoundIndex": 0,
            "m_rounds": [{"m_red": {"m_score": 9}, "m_blue": {"m_score": 10}}],
        },
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(meta))
    return path


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["adb"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_classify_session_flags_1x35_and_training_types():
    drill_by_type = classify_session(
        {
            "m_matchType": "MatchSingleplayerDefenseTraining",
            "m_activityType": "MatchSingleplayerDefensive",
            "m_venue": {"m_rounds": 1, "m_roundDurationSeconds": 35.0},
        }
    )
    assert drill_by_type["session_kind"] == "training"
    assert drill_by_type["is_training"] is True
    assert drill_by_type["match_type"] == "MatchSingleplayerDefenseTraining"

    drill_by_duration_only = classify_session(
        {"m_matchType": "Custom", "m_venue": {"m_rounds": 1, "m_roundDurationSeconds": 35}}
    )
    assert drill_by_duration_only["session_kind"] == "training"
    assert drill_by_duration_only["is_training"] is True

    regular_match = classify_session(
        {
            "m_matchType": "MatchSingleplayer",
            "m_activityType": "MatchSingleplayer",
            "m_venue": {"m_rounds": 3, "m_roundDurationSeconds": 120.0},
        }
    )
    assert regular_match["session_kind"] == "match"
    assert regular_match["is_training"] is False


def test_config_from_env_uses_sync_env_and_has_no_personal_defaults(tmp_path: Path, monkeypatch):
    for key in (
        "TOTF_SYNC_QUEST_SERIAL",
        "TOTF_SYNC_ADB_BIN",
        "TOTF_SYNC_WIFI_IFACE",
        "TOTF_SYNC_SUBNET_PREFIX",
        "TOTF_SYNC_HOST",
        "TOTF_SYNC_COPY_TO_LIBRARY",
        "TOTF_SYNC_ENV_FILE",
        "TOTF_RECORDINGS",
        "TOTF_GAME_RECORDINGS",
        "TOTF2_ADB_BIN",
    ):
        monkeypatch.delenv(key, raising=False)

    empty_env = tmp_path / "missing.env"
    generic = quest.SyncConfig.from_env(env_file=empty_env)
    assert generic.serial is None
    assert generic.wifi_iface is None
    assert generic.subnet_prefix == ""
    assert generic.adb_bin is None

    env_file = tmp_path / "sync.env"
    env_file.write_text(
        "# comment\n"
        "TOTF_SYNC_QUEST_SERIAL=TESTSERIAL123\n"
        "TOTF_SYNC_WIFI_IFACE='wlan9'\n"
        'TOTF_SYNC_SUBNET_PREFIX="192.168.99."\n'
        "TOTF_SYNC_ADB_PORT=5566\n",
        encoding="utf-8",
    )
    loaded = quest.SyncConfig.from_env(env_file=env_file)
    assert loaded.serial == "TESTSERIAL123"
    assert loaded.wifi_iface == "wlan9"
    assert loaded.subnet_prefix == "192.168.99."
    assert loaded.port == 5566

    monkeypatch.setenv("TOTF_SYNC_QUEST_SERIAL", "ENVOVERRIDE")
    overridden = quest.SyncConfig.from_env(env_file=env_file, port=5577)
    assert overridden.serial == "ENVOVERRIDE"
    assert overridden.port == 5577


def test_discover_wifi_candidates_deduplicates_and_filters_subnet(tmp_path: Path):
    leases = tmp_path / "dnsmasq.leases"
    leases.write_text(
        "200 aa:bb:cc:dd:ee:01 192.168.77.20 quest3 *\n"
        "100 aa:bb:cc:dd:ee:02 192.168.32.202 tv *\n",
        encoding="utf-8",
    )

    def fake_run_adb(_adb_bin, args, timeout=15.0):
        if args == ["mdns", "services"]:
            return _completed(
                "List of discovered mdns services\n"
                "adb-quest\t_adb._tcp\t192.168.77.20:5555\n"
                "adb-tv\t_adb._tcp\t192.168.32.202:5555\n"
            )
        if args == ["devices"]:
            return _completed(
                "List of devices attached\n"
                "192.168.77.25:5555\tdevice\n"
                "192.168.32.202:5555\tdevice\n"
            )
        return _completed()

    def fake_arp_run(*_args, **_kwargs):
        return _completed(
            "192.168.77.20 lladdr aa:bb REACHABLE\n"
            "192.168.77.30 lladdr cc:dd STALE\n"
            "192.168.77.31 lladdr ee:ff FAILED\n"
        )

    with (
        patch.object(quest, "run_adb", side_effect=fake_run_adb),
        patch.object(quest.subprocess, "run", side_effect=fake_arp_run),
    ):
        cands = quest.discover_wifi_candidates(
            "/usr/bin/adb",
            explicit_host=None,
            lease_file=leases,
            wifi_iface="wlp9s0",
            subnet_prefix="192.168.77.",
            default_port=5555,
        )

    assert [(c.target, c.source) for c in cands] == [
        ("192.168.77.20:5555", "mdns"),
        ("192.168.77.30:5555", "arp"),
        ("192.168.77.25:5555", "adb-connected"),
    ]


def test_connect_and_verify_rejects_wrong_serial_and_non_quest():
    cands = [
        quest.WifiCandidate("192.168.77.10", 5555, "dhcp-lease"),
        quest.WifiCandidate("192.168.77.20", 5555, "dhcp-lease"),
    ]
    disconnected: list[str] = []

    def fake_run_adb(_adb_bin, args, timeout=15.0):
        if args[:1] == ["connect"]:
            return _completed("connected")
        if args[:1] == ["disconnect"]:
            disconnected.append(args[1])
            return _completed("disconnected")
        if args[2:] == ["get-state"]:
            return _completed("device\n")
        if args[2:] == ["shell", "getprop", "ro.serialno"]:
            return _completed("WRONG\n" if args[1].startswith("192.168.77.10") else "QUESTSERIAL\n")
        if args == ["devices"]:
            return _completed("List of devices attached\n192.168.77.20:5555\tdevice\n")
        return _completed()

    with (
        patch.object(quest, "probe_tcp", return_value="open"),
        patch.object(quest, "run_adb", side_effect=fake_run_adb),
    ):
        verified, serial, diags = quest.connect_and_verify_wifi_quest(
            "/usr/bin/adb", cands, "QUESTSERIAL", "192.168.77."
        )

    assert verified is not None and verified.target == "192.168.77.20:5555"
    assert serial == "QUESTSERIAL"
    assert disconnected == ["192.168.77.10:5555"]
    assert [d.status for d in diags] == ["serial-mismatch:WRONG", "verified"]


def test_run_sync_pulls_classifies_copies_to_library_and_respects_ledger(tmp_path: Path):
    remote_store = tmp_path / "quest_remote"
    remote_store.mkdir()
    match_zip = _make_session_zip(
        remote_store / "session_match.zip",
        rounds=3,
        round_seconds=120.0,
        match_type="MatchSingleplayer",
        activity_type="MatchSingleplayer",
    )
    train_zip = _make_session_zip(
        remote_store / "session_drill.zip",
        rounds=1,
        round_seconds=35.0,
        match_type="MatchSingleplayerDefenseTraining",
        activity_type="MatchSingleplayerDefensive",
    )

    dest_dir = tmp_path / "spectator"
    library_dir = tmp_path / "library"
    state_dir = tmp_path / "state"
    fake_adb = tmp_path / "adb"
    fake_adb.write_text("#!/bin/sh\n", encoding="utf-8")

    remote_now = 1_800_000_100
    old_mtime = remote_now - 120

    def fake_run_adb(_adb_bin, args, timeout=15.0):
        if args[:1] == ["connect"]:
            return _completed("connected")
        if args == ["devices"]:
            return _completed("List of devices attached\n192.168.77.20:5555\tdevice\n")
        if args[2:] == ["get-state"]:
            return _completed("device\n")
        if args[2:] == ["shell", "getprop", "ro.serialno"]:
            return _completed("QUEST123\n")
        if args[2:3] == ["shell"] and "stat -c" in args[3]:
            return _completed(
                f"{remote_now}\n"
                f"{match_zip.stat().st_size} {old_mtime} /sdcard/SessionRecordings/{match_zip.name}\n"
                f"{train_zip.stat().st_size} {old_mtime} /sdcard/SessionRecordings/{train_zip.name}\n"
            )
        if args[2:3] == ["pull"]:
            src_name = Path(args[3]).name
            dst_path = Path(args[4])
            dst_path.write_bytes((remote_store / src_name).read_bytes())
            return _completed("pulled")
        return _completed()

    cfg = quest.SyncConfig(
        adb_bin=str(fake_adb),
        serial="QUEST123",
        host="192.168.77.20:5555",
        dest_dir=dest_dir,
        library_dir=library_dir,
        state_dir=state_dir,
        subnet_prefix="192.168.77.",
    )

    with (
        patch.object(quest, "probe_tcp", return_value="open"),
        patch.object(quest, "run_adb", side_effect=fake_run_adb),
    ):
        first = quest.run_sync(cfg, notify=False)

    assert first.status == "synced"
    assert len(first.pulled) == 2
    by_name = {item.name: item for item in first.pulled}
    assert by_name["session_match.zip"].session_kind == "match"
    assert by_name["session_match.zip"].is_training is False
    assert by_name["session_match.zip"].copied_to_library is True
    assert by_name["session_drill.zip"].session_kind == "training"
    assert by_name["session_drill.zip"].is_training is True
    assert by_name["session_drill.zip"].bout == "1x0:35"
    assert by_name["session_drill.zip"].copied_to_library is True

    assert (dest_dir / "session_match.zip").is_file()
    assert (library_dir / "session_match.zip").is_file()
    assert (dest_dir / "session_drill.zip").is_file()
    assert (library_dir / "session_drill.zip").is_file()

    # Deleting from Spectator must NOT cause re-download because ledger tracks it.
    (dest_dir / "session_drill.zip").unlink()
    with (
        patch.object(quest, "probe_tcp", return_value="open"),
        patch.object(quest, "run_adb", side_effect=fake_run_adb),
    ):
        second = quest.run_sync(cfg, notify=False)
    assert second.status == "up_to_date"
    assert second.skipped_ledger == 1
    assert not (dest_dir / "session_drill.zip").exists()

    # --resync forces re-download of the deleted file.
    with (
        patch.object(quest, "probe_tcp", return_value="open"),
        patch.object(quest, "run_adb", side_effect=fake_run_adb),
    ):
        resynced = quest.run_sync(cfg, resync=["session_drill.zip"], notify=False)
    assert resynced.status == "synced"
    assert [item.name for item in resynced.pulled] == ["session_drill.zip"]
    assert (dest_dir / "session_drill.zip").is_file()


def test_corrupt_zip_pull_does_not_pollute_destinations(tmp_path: Path):
    dest_dir = tmp_path / "spectator"
    library_dir = tmp_path / "library"
    state_dir = tmp_path / "state"
    rec = quest.RemoteRecording(
        name="broken.zip",
        remote_path="/sdcard/SessionRecordings/broken.zip",
        size=10,
        mtime=1_800_000_000,
    )

    def fake_pull(_adb_bin, args, timeout=300.0):
        Path(args[4]).write_bytes(b"0123456789")
        return _completed("pulled")

    with patch.object(quest, "run_adb", side_effect=fake_pull):
        try:
            quest.pull_and_install_recording(
                "/usr/bin/adb", "192.168.77.20:5555", rec, dest_dir, state_dir, library_dir
            )
        except RuntimeError as exc:
            assert "Invalid zip file" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError for corrupt zip")

    assert not (dest_dir / "broken.zip").exists()
    assert not (library_dir / "broken.zip").exists()


def test_run_sync_reports_locked_when_lock_held(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    fake_adb = tmp_path / "adb"
    fake_adb.write_text("#!/bin/sh\n", encoding="utf-8")

    lock_file = (state_dir / "sync.lock").open("w", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        cfg = quest.SyncConfig(adb_bin=str(fake_adb), state_dir=state_dir)
        result = quest.run_sync(cfg, notify=False)
        assert result.status == "locked"
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def test_backfill_library_respects_matches_only(tmp_path: Path):
    dest_dir = tmp_path / "spectator"
    library_dir = tmp_path / "library"
    state_dir = tmp_path / "state"
    dest_dir.mkdir()
    _make_session_zip(dest_dir / "match.zip", rounds=3, round_seconds=120.0)
    _make_session_zip(
        dest_dir / "training.zip",
        rounds=1,
        round_seconds=35.0,
        match_type="MatchSingleplayerDefenseTraining",
        activity_type="MatchSingleplayerDefensive",
    )

    cfg = quest.SyncConfig(dest_dir=dest_dir, library_dir=library_dir, state_dir=state_dir)
    only_matches = quest.backfill_library(cfg, matches_only=True)
    assert only_matches.copied == 1
    assert (library_dir / "match.zip").is_file()
    assert not (library_dir / "training.zip").exists()

    all_rest = quest.backfill_library(cfg, matches_only=False)
    assert all_rest.copied == 1
    assert (library_dir / "training.zip").is_file()
    assert inspect_zip_metadata(library_dir / "training.zip")["is_training"] is True


def test_api_sync_endpoints_and_kind_filtering(tmp_path: Path):
    library = tmp_path / "library"
    game = tmp_path / "game"
    state = tmp_path / "state"
    library.mkdir()
    game.mkdir()

    _make_session_zip(library / "bout_match.zip", rounds=3, round_seconds=120.0)
    _make_session_zip(
        library / "bout_train.zip",
        rounds=1,
        round_seconds=35.0,
        match_type="MatchSingleplayerDefenseTraining",
        activity_type="MatchSingleplayerDefensive",
    )
    _make_session_zip(game / "bout_train.zip", rounds=1, round_seconds=35.0)

    fake_adb = tmp_path / "adb"
    fake_adb.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg = quest.SyncConfig(
        adb_bin=str(fake_adb),
        host="192.168.77.20:5555",
        dest_dir=game,
        library_dir=library,
        state_dir=state,
    )

    client = TestClient(create_app(library, game, sync_config=cfg))
    matches = client.get("/api/sessions?kind=match").json()
    assert [row["name"] for row in matches] == ["bout_match.zip"]
    assert matches[0]["session_kind"] == "match"
    assert matches[0]["is_training"] is False

    training = client.get("/api/sessions?kind=training").json()
    assert [row["name"] for row in training] == ["bout_train.zip"]
    assert training[0]["session_kind"] == "training"
    assert training[0]["is_training"] is True
    assert training[0]["bout"] == "1x0:35"

    assert client.get("/api/sessions?kind=bogus").status_code == 400
    assert client.post("/api/sync/run", json={"resync": ["../escape.zip"]}).status_code == 400

    with patch.object(quest, "probe_tcp", return_value="refused"):
        status_resp = client.get("/api/sync/status")
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["connected_target"] is None
        assert status_body["reboot_hint"] is not None

        run_resp = client.post("/api/sync/run", json={"dry_run": True})
        assert run_resp.status_code == 200
        assert run_resp.json()["status"] == "unreachable"


def test_mcp_list_recordings_kind_filter_and_sync_tools(tmp_path: Path):
    from totf_analyzer.mcp_server import server

    library = tmp_path / "library"
    game = tmp_path / "game"
    library.mkdir()
    game.mkdir()
    _make_session_zip(library / "match.zip", rounds=3, round_seconds=120.0)
    _make_session_zip(
        library / "drill.zip",
        rounds=1,
        round_seconds=35.0,
        match_type="MatchSingleplayerDefenseTraining",
        activity_type="MatchSingleplayerDefensive",
    )

    prev_rec, prev_game = server._recordings, server._game_recordings
    try:
        server.configure(library, game)
        all_rows = server.list_recordings()
        assert len(all_rows) == 2
        assert [r["name"] for r in server.list_recordings(kind="match")] == ["match.zip"]
        drill_rows = server.list_recordings(kind="training")
        assert [r["name"] for r in drill_rows] == ["drill.zip"]
        assert drill_rows[0]["is_training"] is True
        assert drill_rows[0]["bout"] == "1x0:35"

        mock_status = quest.SyncStatusResult(
            adb_available=True,
            adb_bin="/usr/bin/adb",
            serial_expected="TEST",
            dest_dir=str(game),
            library_dir=str(library),
            ledger_path=str(tmp_path / "synced.json"),
            ledger_count=2,
        )
        mock_run = quest.SyncRunResult(status="up_to_date", message="Up to date")
        with (
            patch.object(server, "get_sync_status", return_value=mock_status),
            patch.object(server, "run_sync", return_value=mock_run),
        ):
            assert server.quest_sync_status()["ledger_count"] == 2
            assert server.sync_quest_recordings(dry_run=True)["status"] == "up_to_date"
    finally:
        server.configure(prev_rec, prev_game)
