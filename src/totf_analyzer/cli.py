"""Command line entry points for the local analyzer."""

from __future__ import annotations

import argparse
import json
import os
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

    args = parser.parse_args()
    args.func(args)
