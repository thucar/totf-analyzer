"""Import session zips from the game's SessionRecordings folder."""

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from totf_analyzer.api.app import bout_shorthand, create_app, fight_card


def test_lists_and_imports_game_recording(tmp_path: Path):
    game = tmp_path / "game"
    library = tmp_path / "library"
    game.mkdir()
    library.mkdir()
    source = game / "session_a.zip"
    source.write_bytes(b"PK\x03\x04not-a-real-zip")
    (game / "session_b.zip").write_bytes(b"PK\x03\x04later")
    (game / "notes.txt").write_text("ignore")

    client = TestClient(create_app(library, game))
    listing = client.get("/api/game-recordings")
    assert listing.status_code == 200
    body = listing.json()
    assert body["available"] is True
    assert body["directory"] == str(game.resolve())
    assert [row["name"] for row in body["recordings"]] == ["session_b.zip", "session_a.zip"]
    assert body["recordings"][0]["imported"] is False
    assert body["recordings"][0]["bout"] is None
    assert body["recordings"][0]["created"] is None

    imported = client.post("/api/sessions/import", json={"name": "session_a.zip"})
    assert imported.status_code == 200
    assert (library / "session_a.zip").read_bytes() == source.read_bytes()
    sessions = client.get("/api/sessions").json()
    assert [row["name"] for row in sessions] == ["session_a.zip"]
    again = client.get("/api/game-recordings").json()
    imported_flags = {row["name"]: row["imported"] for row in again["recordings"]}
    assert imported_flags == {"session_b.zip": False, "session_a.zip": True}


def test_import_rejects_paths_outside_game_folder(tmp_path: Path):
    game = tmp_path / "game"
    library = tmp_path / "library"
    game.mkdir()
    outside = tmp_path / "secret.zip"
    outside.write_bytes(b"nope")
    client = TestClient(create_app(library, game))

    assert client.post("/api/sessions/import", json={"name": "../secret.zip"}).status_code == 400
    assert client.post("/api/sessions/import", json={"name": "notes.txt"}).status_code == 400
    assert client.post("/api/sessions/import", json={"name": "missing.zip"}).status_code == 404
    assert not (library / "secret.zip").exists()


def test_missing_game_folder(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "library", tmp_path / "missing"))
    body = client.get("/api/game-recordings").json()
    assert body["available"] is False
    assert body["recordings"] == []


def test_listing_reads_bout_shorthand_and_time(tmp_path: Path):
    game = tmp_path / "game"
    game.mkdir()
    meta = {
        "m_createdUtc": "2026-11-15T03:48:37.9637340Z",
        "m_matchType": "MatchSingleplayer",
        "m_activityType": "MatchSingleplayer",
        "m_venue": {"m_rounds": 4, "m_roundDurationSeconds": 180},
    }
    training_meta = {
        "m_createdUtc": "2026-11-15T03:52:02.0803340Z",
        "m_matchType": "MatchSingleplayerDefenseTraining",
        "m_activityType": "MatchSingleplayerDefensive",
        "m_venue": {"m_rounds": 1, "m_roundDurationSeconds": 35.0},
    }
    with zipfile.ZipFile(game / "session_custom.zip", "w") as archive:
        archive.writestr("metadata.json", json.dumps(meta))
    with zipfile.ZipFile(game / "session_drill.zip", "w") as archive:
        archive.writestr("metadata.json", json.dumps(training_meta))
    (game / "session_broken.zip").write_bytes(b"PK\x03\x04nope")

    client = TestClient(create_app(tmp_path / "library", game))
    rows = {row["name"]: row for row in client.get("/api/game-recordings").json()["recordings"]}
    assert rows["session_custom.zip"]["bout"] == "4x3"
    assert rows["session_custom.zip"]["created"] == "2026-11-15T03:48:37.963Z"
    assert rows["session_custom.zip"]["session_kind"] == "match"
    assert rows["session_custom.zip"]["is_training"] is False
    assert rows["session_drill.zip"]["bout"] == "1x0:35"
    assert rows["session_drill.zip"]["session_kind"] == "training"
    assert rows["session_drill.zip"]["is_training"] is True
    assert rows["session_broken.zip"]["bout"] is None
    assert rows["session_broken.zip"]["created"] is None
    assert rows["session_broken.zip"]["session_kind"] == "match"


def test_fight_card_names_winner_and_finish():
    def meta(red_flags: dict, blue_flags: dict, red_score: int, blue_score: int) -> dict:
        return {
            "m_tracks": [
                {"m_corner": 1, "m_boxerName": "Blue ", "m_isLocalPlayer": True},
                {"m_corner": 2, "m_boxerName": "Red"},
            ],
            "m_scoring": {
                "m_completedRoundIndex": 0,
                "m_rounds": [{"m_red": {"m_score": red_score, **red_flags}, "m_blue": {"m_score": blue_score, **blue_flags}}],
            },
        }

    knockout = fight_card(meta({"m_knockedOut": True}, {}, 7, 10))
    assert knockout == {
        "red": "Red",
        "blue": "Blue",
        "winner": "blue",
        "method": "KO",
        "local": "blue",
        "result": "W-KO",
    }
    technical = fight_card(meta({"m_technicallyKnockedOut": True}, {}, 8, 9))
    assert technical["result"] == "W-TKO"
    decision = fight_card(meta({}, {}, 28, 27))
    assert decision["winner"] == "red" and decision["method"] == "UD" and decision["result"] == "L-UD"
    draw = fight_card(meta({}, {}, 27, 27))
    assert draw["winner"] is None and draw["method"] == "draw" and draw["result"] == "D"


def test_bout_shorthand_uses_rounds_by_minutes():
    assert bout_shorthand(3, 120) == "3x2"
    assert bout_shorthand(12, 180) == "12x3"
    assert bout_shorthand(3, 90) == "3x1:30"
    assert bout_shorthand(0, 120) is None
    assert bout_shorthand(3, 0) is None


def test_import_is_noop_when_library_is_the_game_folder(tmp_path: Path):
    folder = tmp_path / "both"
    folder.mkdir()
    (folder / "session_a.zip").write_bytes(b"zip")
    client = TestClient(create_app(folder, folder))
    response = client.post("/api/sessions/import", json={"name": "session_a.zip"})
    assert response.status_code == 200
    assert (folder / "session_a.zip").read_bytes() == b"zip"
