"""Lightweight metadata inspection and training/match classification for TotF2 session zips."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from totf_analyzer.parser.session import COLOR_CORNER

SessionKind = Literal["match", "training"]

TRAINING_ROUNDS = 1
TRAINING_ROUND_DURATION_SEC = 35.0
TRAINING_TYPE_MARKERS = ("training", "defensive")


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _round_score(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def created_utc_iso(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        digits: list[str] = []
        suffix = ""
        for index, char in enumerate(tail):
            if char.isdigit() and not suffix:
                digits.append(char)
            else:
                suffix = tail[index:]
                break
        fraction = "".join(digits)[:6]
        text = f"{head}.{fraction}{suffix}" if fraction else f"{head}{suffix}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    millis = parsed.microsecond // 1000
    return parsed.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def bout_shorthand(rounds: object, round_seconds: object) -> str | None:
    """Boxing card shorthand: scheduled rounds by minutes, as in 3x2, 12x3, or 1x0:35."""
    if isinstance(rounds, bool) or not isinstance(rounds, (int, float)):
        return None
    if isinstance(round_seconds, bool) or not isinstance(round_seconds, (int, float)):
        return None
    count = int(rounds)
    seconds = float(round_seconds)
    if count < 1 or seconds <= 0:
        return None
    if seconds % 60 == 0:
        return f"{count}x{int(seconds // 60)}"
    if seconds.is_integer():
        whole = int(seconds)
        return f"{count}x{whole // 60}:{whole % 60:02d}"
    return f"{count}x{seconds:g}s"


def _boxrec_result(winner: str | None, method: str | None, local: str | None) -> str | None:
    if method == "draw":
        return "D"
    if method not in {"KO", "TKO", "UD"} or winner not in {"red", "blue"}:
        return None
    subject = local if local in {"red", "blue"} else winner
    return f"{'W' if winner == subject else 'L'}-{method}"


def fight_card(meta: dict) -> dict[str, str | None]:
    """Fighter names and a BoxRec result from the local fighter's side.

    The badge is W-KO, L-KO, W-TKO, L-TKO, W-UD, L-UD, or D. A score win is UD.
    """
    card: dict[str, str | None] = {
        "red": None,
        "blue": None,
        "winner": None,
        "method": None,
        "local": None,
        "result": None,
    }
    for track in meta.get("m_tracks") or []:
        if not isinstance(track, dict):
            continue
        corner_id = track.get("m_corner")
        corner = next((name for name, number in COLOR_CORNER.items() if number == corner_id), None)
        if corner is None:
            continue
        card[corner] = _clean_str(track.get("m_boxerName"))
        if track.get("m_isLocalPlayer") is True:
            card["local"] = corner
    scoring = meta.get("m_scoring") if isinstance(meta.get("m_scoring"), dict) else {}
    rounds = scoring.get("m_rounds") if isinstance(scoring.get("m_rounds"), list) else []
    if not rounds:
        return card
    try:
        completed = int(scoring.get("m_completedRoundIndex") or 0)
    except (TypeError, ValueError):
        completed = 0
    knocked: set[str] = set()
    technical: set[str] = set()
    scores = {"red": 0, "blue": 0}
    for index, raw in enumerate(rounds):
        if index > completed or not isinstance(raw, dict):
            continue
        for corner, key in (("red", "m_red"), ("blue", "m_blue")):
            block = raw.get(key) if isinstance(raw.get(key), dict) else {}
            if block.get("m_knockedOut"):
                knocked.add(corner)
            if block.get("m_technicallyKnockedOut"):
                technical.add(corner)
            scores[corner] += _round_score(block.get("m_score"))
    if len(knocked) == 1:
        card["method"] = "KO"
        card["winner"] = "blue" if "red" in knocked else "red"
    elif len(technical) == 1:
        card["method"] = "TKO"
        card["winner"] = "blue" if "red" in technical else "red"
    elif scores["red"] == scores["blue"]:
        card["method"] = "draw"
    else:
        card["method"] = "UD"
        card["winner"] = "red" if scores["red"] > scores["blue"] else "blue"
    card["result"] = _boxrec_result(card["winner"], card["method"], card["local"])
    return card


def classify_session(meta: dict) -> dict[str, Any]:
    """Classify a session as a training drill or a regular/ranked match.

    A session is flagged `training` when scheduled as 1x0:35 (1 round of 35 seconds)
    or when `m_matchType` / `m_activityType` indicates a training/defensive drill.
    """
    match_type = _clean_str(meta.get("m_matchType"))
    activity_type = _clean_str(meta.get("m_activityType"))
    venue = meta.get("m_venue") if isinstance(meta.get("m_venue"), dict) else {}
    rounds = venue.get("m_rounds")
    round_seconds = venue.get("m_roundDurationSeconds")

    is_1x35 = (
        not isinstance(rounds, bool)
        and isinstance(rounds, (int, float))
        and int(rounds) == TRAINING_ROUNDS
        and not isinstance(round_seconds, bool)
        and isinstance(round_seconds, (int, float))
        and abs(float(round_seconds) - TRAINING_ROUND_DURATION_SEC) < 1e-6
    )
    type_text = " ".join(part for part in (match_type, activity_type) if part).lower()
    has_training_type = any(marker in type_text for marker in TRAINING_TYPE_MARKERS)

    is_training = is_1x35 or has_training_type
    session_kind: SessionKind = "training" if is_training else "match"
    return {
        "match_type": match_type,
        "activity_type": activity_type,
        "session_kind": session_kind,
        "is_training": is_training,
    }


def inspect_zip_metadata(path: Path) -> dict[str, Any]:
    """Read summary bout fields and training classification from a session zip."""
    empty: dict[str, Any] = {
        "bout": None,
        "created": None,
        "red": None,
        "blue": None,
        "winner": None,
        "method": None,
        "local": None,
        "result": None,
        "match_type": None,
        "activity_type": None,
        "session_kind": "match",
        "is_training": False,
    }
    try:
        with zipfile.ZipFile(path) as archive:
            meta = json.loads(archive.read("metadata.json"))
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return empty
    if not isinstance(meta, dict):
        return empty
    venue = meta.get("m_venue") if isinstance(meta.get("m_venue"), dict) else {}
    return {
        "bout": bout_shorthand(venue.get("m_rounds"), venue.get("m_roundDurationSeconds")),
        "created": created_utc_iso(meta.get("m_createdUtc")),
        **fight_card(meta),
        **classify_session(meta),
    }
