"""Command line entry points for the local analyzer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _recordings(value: str | None) -> Path:
    return Path(value or os.environ.get("TOTF_RECORDINGS", "Recordings"))


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from totf_analyzer.api.app import create_app

    os.environ["TOTF_RECORDINGS"] = str(_recordings(args.recordings).resolve())
    uvicorn.run(
        create_app(_recordings(args.recordings)),
        host=args.host,
        port=args.port,
    )


def _cmd_mcp(args: argparse.Namespace) -> None:
    from totf_analyzer.mcp_server.server import configure, main

    os.environ["TOTF_RECORDINGS"] = str(_recordings(args.recordings).resolve())
    configure(_recordings(args.recordings))
    main(host=args.host, port=args.port)


def _cmd_analyze(args: argparse.Namespace) -> None:
    from totf_analyzer.analytics.metrics import build_analytics
    from totf_analyzer.parser.session import load_session

    report = build_analytics(load_session(args.path))
    payload = report.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload))
        return
    session = payload["session"]
    print(f"{session['name']}  {session['venue']}  {session['duration_sec']:.1f}s  {session['method']}")
    print(
        f"score red {session['red_total_score']}  blue {session['blue_total_score']}"
        f"  winner corner {session['winner_corner']}"
    )
    for offense in payload["offense"]:
        defense = next(item for item in payload["defense"] if item["corner"] == offense["corner"])
        discipline = defense["guard_discipline"]
        print(
            f"corner {offense['corner']}: thrown {offense['thrown']}  landed {offense['landed']}"
            f"  official {offense['official_hits']}  accuracy {offense['accuracy']}"
            f"  guard_up {defense['guard_up_percent']}  guard_up_under_fire {defense['guard_up_percent_under_fire']}"
        )
        print(
            f"  offhand_kept {discipline['offhand_guard_kept_percent']}"
            f"  retraction_returned {discipline['retraction_returned_percent']}"
        )
        combos = offense["combinations"]
        length = combos["mean_combo_length"]
        length_text = "n/a" if length is None else f"{length:.2f}"
        top = combos["patterns"][0] if combos["patterns"] else None
        top_text = ""
        if top is not None:
            top_text = (
                f"  top {top['pattern']} x{top['count']}"
                f"  accuracy {top['accuracy']}  damage {top['mean_damage']}"
            )
        print(f"  combos {combos['combo_count']}  mean_length {length_text}{top_text}")
    for rnd in payload["rounds"]:
        if not rnd["completed"] or not rnd["offense"]:
            continue
        print(
            f"round {rnd['index'] + 1}: {rnd['duration_sec']}s"
            f"  score {rnd['red']['score']}-{rnd['blue']['score']}"
            f"  hits {rnd['red']['hits']}-{rnd['blue']['hits']}"
        )
        for offense in rnd["offense"]:
            defense = next(item for item in rnd["defense"] if item["corner"] == offense["corner"])
            print(
                f"  corner {offense['corner']}: thrown {offense['thrown']}  landed {offense['landed']}"
                f"  accuracy {offense['accuracy']}  guard_up {defense['guard_up_percent']}"
            )
    print(f"key moments {len(payload['key_moments'])}")


def _cmd_sync(args: argparse.Namespace) -> None:
    from totf_analyzer.sync.quest import (
        SyncConfig,
        backfill_library,
        enable_tcpip,
        format_mb,
        get_sync_status,
        run_sync,
        seed_existing,
        seed_remote,
    )

    library_dir = None if args.no_library else _recordings(args.library_dir)
    config = SyncConfig.from_env(
        adb_bin=args.adb,
        serial=args.serial,
        host=args.host,
        remote_dir=args.remote_dir,
        dest_dir=args.dest_dir,
        library_dir=library_dir,
        copy_to_library=False if args.no_library else None,
        state_dir=args.state_dir,
        lease_file=args.lease_file,
        wifi_iface=args.wifi_iface,
        subnet_prefix=args.subnet_prefix,
        port=args.port,
        min_age=args.min_age,
    )

    if args.enable_tcpip:
        res = enable_tcpip(config)
        if args.json:
            print(json.dumps(res.to_dict()))
        else:
            print(res.message, file=sys.stdout if res.ok else sys.stderr)
        sys.exit(0 if res.ok else 1)

    if args.seed_existing:
        res = seed_existing(config, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(res.to_dict()))
        elif res.error:
            print(res.error, file=sys.stderr)
        else:
            for name in res.seeded:
                print(f"{'[dry-run] would seed' if args.dry_run else 'seeded'} {name}")
            print(res.message)
        sys.exit(1 if res.error else 0)

    if args.seed_remote:
        res = seed_remote(config, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(res.to_dict()))
        elif res.error:
            print(res.error, file=sys.stderr)
        else:
            for name in res.seeded:
                print(f"{'[dry-run] would seed' if args.dry_run else 'seeded'} {name}")
            print(res.message)
        sys.exit(1 if res.error else 0)

    if args.backfill_library:
        res = backfill_library(config, dry_run=args.dry_run, matches_only=args.matches_only)
        if args.json:
            print(json.dumps(res.to_dict()))
        elif res.error:
            print(res.error, file=sys.stderr)
        else:
            for item in res.entries:
                tag = "TRAINING" if item["is_training"] else "MATCH"
                bout = f" {item['bout']}" if item.get("bout") else ""
                print(
                    f"{'[dry-run] would copy' if args.dry_run else 'copied'} "
                    f"[{tag}{bout}] {item['name']} ({format_mb(item['size'])})"
                )
            print(res.message)
        sys.exit(1 if res.error else 0)

    if args.status:
        status = get_sync_status(
            config,
            ignore_ledger=args.ignore_ledger,
            ignore_age=args.ignore_age,
            resync=args.resync,
        )
        if args.json:
            print(json.dumps(status.to_dict()))
            sys.exit(1 if status.error and not status.adb_available else 0)
        print(f"Destination:   {status.dest_dir}")
        print(f"Library:       {status.library_dir or '(disabled)'}")
        print(f"Ledger:        {status.ledger_path} ({status.ledger_count} entries)")
        if status.sync_in_progress:
            print("Sync lock:     active (another sync is currently running)")
        if status.error:
            print(f"Error:         {status.error}", file=sys.stderr)
        if not status.candidates:
            print("Wi-Fi Quest 3: no candidates found in mDNS, DHCP leases, or ARP")
            sys.exit(0)
        print("Candidates:")
        for cand in status.candidates:
            print(f"  - {cand.target} ({cand.source}): {cand.status}")
        if status.reboot_hint:
            print(f"Hint: {status.reboot_hint}")
        if status.connected_target is None:
            sys.exit(0)
        serial_note = f" (serial {status.connected_serial})" if status.connected_serial else ""
        print(f"Connected:     {status.connected_target}{serial_note}")
        print(f"Remote files:  {status.remote_total or 0} total")
        print(f"  Pending:     {len(status.pending)}")
        for rec in status.pending:
            print(f"    + {rec.name} ({format_mb(rec.size)})")
        if status.already_local:
            print(f"  Already local (not yet in ledger): {status.already_local}")
        if status.skipped_ledger:
            print(f"  Skipped (already in ledger / deleted locally): {status.skipped_ledger}")
        if status.deferred_recent:
            print(f"  Deferred (modified < {config.min_age}s ago): {status.deferred_recent}")
        sys.exit(0)

    result = run_sync(
        config,
        dry_run=args.dry_run,
        ignore_ledger=args.ignore_ledger,
        ignore_age=args.ignore_age,
        resync=args.resync,
        notify=not args.no_notify,
        quiet=args.quiet,
    )
    if args.json:
        print(json.dumps(result.to_dict()))
        sys.exit(1 if result.errors else 0)

    if result.status == "locked":
        if not args.quiet:
            print(result.message)
        sys.exit(0)

    if result.status == "unreachable":
        if result.reboot_hint:
            print(result.reboot_hint, file=sys.stderr)
        elif not args.quiet:
            print(result.message)
        sys.exit(0)

    for missing_name in result.missing_resync:
        print(
            f"Warning: requested --resync file not found on Quest 3: {missing_name}",
            file=sys.stderr,
        )

    if result.recorded_existing and not args.quiet:
        prefix = "[dry-run] Would record" if args.dry_run else "Recorded"
        print(f"{prefix} {result.recorded_existing} already-present recording(s) in ledger.")

    if result.status == "dry_run":
        print(result.message)
        for rec in result.would_pull:
            print(f"  + {rec.name} ({format_mb(rec.size)})")
        sys.exit(0)

    if result.status == "up_to_date":
        if not args.quiet:
            print(result.message)
        sys.exit(0)

    for item in result.pulled:
        tag = "TRAINING" if item.is_training else "MATCH"
        bout = f" {item.bout}" if item.bout else ""
        lib_note = " + library" if item.copied_to_library else ""
        print(
            f"Synced [{tag}{bout}] {item.name} ({format_mb(item.size)}) "
            f"in {item.elapsed_sec:.1f}s via {result.connected_target}{lib_note}"
        )

    for err in result.errors:
        print(err, file=sys.stderr)

    sys.exit(1 if result.errors else 0)


def main() -> None:
    parser = argparse.ArgumentParser(prog="totf-analyzer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="start the local web API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--recordings", default=None)
    serve.set_defaults(func=_cmd_serve)

    mcp = sub.add_parser("mcp", help="run the MCP server over Streamable HTTP")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8010)
    mcp.add_argument("--recordings", default=None)
    mcp.set_defaults(func=_cmd_mcp)

    analyze = sub.add_parser("analyze", help="print analytics for one session zip")
    analyze.add_argument("path")
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(func=_cmd_analyze)

    sync = sub.add_parser(
        "sync",
        help="sync Thrill of the Fight 2 recordings from Quest 3 over Wi-Fi",
    )
    sync.add_argument("--status", action="store_true", help="inspect discovery, ADB state, and pending recordings")
    sync.add_argument("--dry-run", action="store_true", help="show what would be synced without downloading")
    sync.add_argument("--quiet", action="store_true", help="suppress routine output when unreachable or up to date")
    sync.add_argument("--no-notify", action="store_true", help="disable desktop notifications")
    sync.add_argument("--json", action="store_true", help="print structured JSON output")
    sync.add_argument("--resync", nargs="+", metavar="FILENAME", help="force re-pulling specific filename(s)")
    sync.add_argument("--ignore-ledger", action="store_true", help="pull files missing locally even if in ledger")
    sync.add_argument("--ignore-age", action="store_true", help="do not defer recently modified remote files")
    sync.add_argument("--seed-existing", action="store_true", help="record local Spectator zips in the ledger")
    sync.add_argument("--seed-remote", action="store_true", help="record current Quest 3 zips in the ledger without pulling")
    sync.add_argument("--enable-tcpip", action="store_true", help="enable Wi-Fi ADB over USB after a Quest reboot")
    sync.add_argument("--backfill-library", action="store_true", help="copy existing Spectator zips missing from Recordings/")
    sync.add_argument("--matches-only", action="store_true", help="with --backfill-library, skip training drills")
    sync.add_argument("--no-library", action="store_true", help="sync to Steam Spectator only, skip copying to Recordings/")
    sync.add_argument("--host", default=None, help="explicit Quest 3 Wi-Fi IP or IP:PORT")
    sync.add_argument("--serial", default=None, help="expected Quest 3 ro.serialno")
    sync.add_argument("--remote-dir", default=None, help="remote SessionRecordings directory on Quest 3")
    sync.add_argument("--dest-dir", default=None, help="local Steam Spectator SessionRecordings directory")
    sync.add_argument("--library-dir", default=None, help="TotF Analyzer Recordings library directory")
    sync.add_argument("--state-dir", default=None, help="directory for sync lock and synced.json ledger")
    sync.add_argument("--adb", default=None, help="path to adb binary")
    sync.add_argument("--port", type=int, default=None, help="default Wi-Fi ADB TCP port")
    sync.add_argument("--min-age", type=int, default=None, help="skip remote files modified less than N seconds ago")
    sync.add_argument("--wifi-iface", default=None, help="Wi-Fi interface name for ARP neighbor discovery")
    sync.add_argument("--subnet-prefix", default=None, help="IPv4 prefix filter for Quest Wi-Fi subnet")
    sync.add_argument("--lease-file", default=None, help="DHCP leases file for Quest AP discovery")
    sync.set_defaults(func=_cmd_sync)

    args = parser.parse_args()
    args.func(args)
