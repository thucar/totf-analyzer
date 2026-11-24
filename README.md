# TOTF Analyzer

Factual analytics for Thrill of the Fight 2 session recordings. Drop a session zip in `Recordings/`, then read punch counts, accuracy, speed, guard, head movement, and timestamped moments in the local dashboard or over MCP.

The tool does not rate fighters or recommend what to fix. Measurement definitions are listed below so a coach can interpret the numbers.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
./totf.sh
```

`./totf.sh` opens a menu. It can run the dashboard and MCP server in the foreground, install them as systemd user services, or uninstall those services. Session zips live in `Recordings/` (override with `TOTF_RECORDINGS`).

## Web dashboard

```bash
systemctl --user enable --now totf-analyzer-web.service
```

With lingering enabled the unit starts at boot as the installing user, binds `127.0.0.1:8000`, and reads this project's `Recordings/` directory. `totf-analyzer serve` starts the same server in the foreground.

For the React UI during development:

```bash
cd web
npm install
npm run dev
```

Vite serves `http://127.0.0.1:5173` and proxies `/api` to the Python server. `npm run build` writes `web/dist`; `totf-analyzer serve` then serves that UI at `/`.

## MCP

The MCP server listens on Streamable HTTP and reads session zips itself. Cursor connects to that URL, so the agent does not need permission to open `Recordings/`.

```bash
systemctl --user enable --now totf-analyzer-mcp.service
```

The unit runs as the installing user, binds `127.0.0.1:8010`, and sets `TOTF_RECORDINGS` to this project's `Recordings/` directory.

```json
{
  "mcpServers": {
    "totf-analyzer": {
      "url": "http://127.0.0.1:8010/mcp"
    }
  }
}
```

Tools:

- `list_recordings` — lists recordings with `bout`, `session_kind` (`"match"` or `"training"`), `is_training`, `match_type`, fighter names, and `result` (optional `kind="match"` or `kind="training"` filter)
- `quest_sync_status` — checks Quest 3 Wi-Fi discovery, ADB reachability, sync ledger count, and pending recordings
- `sync_quest_recordings` — pulls new Quest 3 recordings over Wi-Fi into Steam Spectator and `Recordings/` (`dry_run`, `ignore_ledger`, `resync`)
- `analyze_recording` — compact analytics summary (`include_series=False`, `include_punches=False`, `include_moments=False`, `include_context=False`, `max_patterns=5` by default; pass `True` / `None` for the full report)
- `get_fighter_stats` — one corner (`1` blue, `2` red; includes fight-level `context`, `include_round_context=False`, `include_punches=False`, `max_patterns=10` by default)
- `get_context_stats` — situational context breakdowns (`by_stun_state`, `by_punishment_state`, `by_range_zone`, `by_engagement_state`) with optional `corner` and `round_index` filters
- `get_punches` — per-punch rows for one corner (`1` blue, `2` red), optional `round_index` and `landed_only=True`; includes outcome `hit_kind` and launch-state context tags
- `get_key_moments` — optional `type` (`stun`, `punishment_stun`, `knockdown`, `knockout`, `exchange`, `punishment_spike`, `high_velocity_landed`, `head_drop`, `angle_cut`, `duck`, `bob_and_weave`), `corner`, and `round_index` filters
- `get_series` — `punishment_0`, `punishment_1`, `punishment_2`, `punishment_ratio`, `stunned`, `guard_up`, `left_guard_up`, `right_guard_up`, `guard_brace`, `guard_friction`, `guard_mass`, `guard_ladder`, `head_speed`, `head_height`, `hips_x`, `hips_z`, `head_slip_lateral`, `fighter_distance`, `blade_angle`, `tangential_speed`, `punch_density`, `stiffness_max`. Optional `round_index` returns that round with time starting at the bell.

## Quest 3 Wi-Fi Sync

`totf-analyzer sync` discovers a Quest 3 over Wi-Fi (ADB mDNS, DHCP leases, ARP neighbors, or active ADB Wi-Fi sessions), verifies the configured device serial (or Quest hardware identity), atomically pulls new `SessionRecordings/*.zip` files into Steam Spectator (`TOTF_GAME_RECORDINGS`), verifies zip CRC integrity, and auto-copies them into `Recordings/` (`TOTF_RECORDINGS`). Already-synced filenames are recorded in `~/.local/state/totf2-sync/synced.json` so locally deleted recordings are not re-downloaded.

Machine-local sync settings live outside git in `~/.config/totf-analyzer/sync.env`:

```bash
TOTF_SYNC_QUEST_SERIAL=<your-quest-serial>
TOTF_SYNC_ADB_BIN=/path/to/adb
TOTF_SYNC_WIFI_IFACE=wlan0
TOTF_SYNC_SUBNET_PREFIX=192.168.77.
TOTF_SYNC_LEASE_FILE=/run/quest3-dhcp/dnsmasq.leases
```

```bash
# Check Wi-Fi discovery, ADB state, ledger count, and pending zips
totf-analyzer sync --status

# Dry-run or pull now (copies to Steam Spectator + Recordings/)
totf-analyzer sync --dry-run
totf-analyzer sync

# Re-enable Wi-Fi ADB once over USB after a full Quest 3 reboot
totf-analyzer sync --enable-tcpip

# Enable the 60-second background user timer (also installed by ./totf.sh)
systemctl --user enable --now totf-analyzer-sync.timer
```

## What the numbers mean

| Measure | Definition |
| --- | --- |
| Thrown | `kinematic_thrown` plus `contact_thrown`. A record in `punches.bin` whose byte 9 is `0` is a swing the game detected, with a punch class, and always counts. Every other record is a fixed 12-tick glove-contact stamp, which the game also writes for blocks, glove clashes, and pushes. A contact record counts when its glove closed on the opponent's head, chest, spine, or hips at 4.0 m/s or more (3-tick mean) in the 0.15 s before the contact, and it does not fall inside a swing already counted on that hand, within 0.10 s of its end, or within 0.10 s before a kinematic launch on that hand. A slower contact record also counts when a hit event stores its contact point, or when a hit that no counted punch explains falls from 0.025 s before to 0.05 s after its contact tick. `discarded_records` is the number left out. An AI opponent's track has contact records only, so its punches that touched nothing are not recorded and its thrown count is a lower bound. |
| Landed | Every hit the defender took. A type-1 event on a track is a hit taken by that fighter, and byte 8 is its kind: `1` an ordinary hit, `6` a stun, `7` a punishment stun, `2` a punishment knockdown, `3` a flash knockdown, `4` a TKO stoppage blow, and `5` a KO stoppage blow. `official_hits` is the scorecard's `m_hits`, which counts kind `1` only, so `landed` is higher by the stuns and knockdown/stoppage blows. |
| Accuracy | Landed / thrown |
| Hand | Record byte 10: `0` right, `1` left. Confirmed when that wrist moves more than the other from launch to end. |
| Trajectory | Byte 32: `1` jab, `2` cross, `3` left_hook, `4` right_hook, `6` uppercut. Class `0` is the wrist's launch-to-peak displacement in the opponent frame (forward, up, right). For a contact record that displacement is taken over the 0.15 s before the contact. |
| Speed | Peak speed of the punching glove center in m/s, from `skeleton.bin`, as a 3-tick mean. It runs from launch to end for a kinematic record and over the 0.15 s before the contact for a contact record. The punch record has no speed field: the float at offset 80 does not follow wrist speed. |
| Punch row | `launch_sec` is `launch_tick` (offset 12) and `t_sec` is the end tick (offset 0). `impact_sec` is the tick of the hit event paired with the punch, `damage` is that event's damage (float at byte 13; per round those sum to the defender's `m_receivedDamage`), and `hit_kind` labels the hit event kind (`hit`, `stun`, `punishment_stun`, `knockdown`, `punishment_knockdown`, `tko`, `knockout`). A hit event and its punch record store the same contact point (event bytes 37–48, punch bytes 91–102), which pairs them exactly; a hit with no such record goes to the closest free punch whose launch-to-end window holds it. `combo_id` (1-based within the offense block), `combo_depth` (`1`..`4`, `5+`), and `countered` use the same launch-gap groups and counter windows as `combinations`. `head_slip_m` is signed `(head - hips)` on the fighter's right at `launch_tick`. Launch-state context flags (`self_stunned`, `opponent_stunned`, `self_hurt`, `opponent_hurt`, `range_zone`, `fighter_distance_m`, `under_fire`, `in_exchange`) are sampled at `launch_tick`. `get_punches` also includes `punch_type` as an alias of `trajectory`. |
| Guard up | Both glove centers within 0.38 m below head joint 4 and 0.40 m horizontally. A glove center is the wrist extended along the forearm by half of `m_scaledHandLength` (0.095 m if the snapshot omits it). Fight-level percent uses bell-to-bell ticks only. `left_guard_up_percent`, `right_guard_up_percent`, `both_guard_up_percent`, and `either_guard_up_percent` use that same box per hand. `both_guard_up_percent` is `guard_up_percent`. Each is also reported under fire. |
| Off-hand kept | At a kinematic punch's peak glove extension (byte 9 is 0), the other glove's drop below the head is under 0.28 m and its horizontal distance is under 0.38 m. A glove above the head has drop 0. Reported overall and when throwing left or right. Drop and horizontal flare (median, p90) are split by lead and rear: orthodox lead is left, southpaw lead is right. |
| Retraction | From that peak until the punching glove re-enters the same 0.28 / 0.38 m box, the next same-hand launch, or 800 ms. A glove already in that box at the peak, or a same-hand launch before re-entry, is excluded. `retraction_returned_percent` is returns divided by returns plus misses, kinematic punches only. Time is median, mean, and p90 of returns. Droop is the largest drop of head-relative glove height below the straight chord from peak to re-entry; `sag_over_10cm_percent` is the share of returns whose droop exceeds 0.10 m. Directness is chord length divided by path length, in [0, 1], as median and mean. |
| Footwork | Hips joint 0 from the bell through the end bell. The warning and the time after the end bell are left out. Radial and tangential distances are absolute step lengths on the opponent frame (forward toward the opponent's hips, right is the fighter's right). `total_distance_m` is their sum, and `tangential_share` is tangential divided by that sum. Positive tangential motion is counterclockwise around the opponent when viewed from above. Clinch is under 0.85 m, pocket is 0.85 m through 1.35 m, and outside is beyond 1.35 m. Shoulder blade (joints 6 and 10) and foot blade (joints 15 and 19) are the median absolute angle of that horizontal line against the fighter's right: 0 is square to the opponent and 90 points at the opponent. Square stance is a shoulder angle under 15 degrees. Lead left is a signed shoulder angle of at least 15 degrees. Square while punching uses the shoulder angle at each punch's launch tick. An angle cut merges 0.75 s windows in which this fighter's own hips sweep at least 20 degrees around the opponent while the hips stay under 1.8 m apart. Entry and exit angles use that same sweep. A new punch group starts when launch ticks are more than 0.65 s apart. Entry runs from the first launch to the last punch's end. Exit is the next 0.5 s, stopping at the end bell. Foot blade is inferred because Quest ankle joints are IK-estimated. |
| Under fire | 0.05 s before through 0.30 s after each opponent punch record |
| Head | Skeleton joint 4. `head_lateral_range` is the horizontal extent, hypot(max x − min x, max z − min z). `head_movement` uses frames from the bell through the end bell. Lateral slip is the absolute projection of (head − hips) onto the fighter's right, the same axis as footwork. Off centerline is a slip of at least 0.10 m, reported overall, under fire, and on frames inside this fighter's own launch-to-end punch interval. `head_height_iqr_m` is the interquartile range of head height. `p05_p95_span_m` is the 95th percentile of head height minus the 5th. `pelvis_drop_iqr_m` is the interquartile range of hips height below its 90th percentile. `trunk_bend_iqr_m` is the interquartile range of head height minus hips height. A duck merges 0.8 s windows where head height falls and rises at least 0.15 m around an interior trough. A bob-and-weave merges 1.0 s windows with that shape at 0.12 m and a lateral-slip range of at least 0.12 m. The two counts are independent. Quest hips are the recorded root joint, not an optical measurement. |
| Guard channels | Not decoded. `guard_brace`, `guard_friction`, `guard_mass`, and `guard_ladder` read the 48-byte payload as four channels of six uint16 samples, but the payload repeats on a 17-byte period and does not have that layout. Treat the four series as raw bytes, not guard levels. |
| Biomechanical series | `left_guard_up` and `right_guard_up` are 1.0 s bucket shares in [0, 1] using the same head-relative box as `guard_up`. `hips_x` and `hips_z` are 0.25 s bucket means of world horizontal hip coordinates in meters. `head_slip_lateral`, `fighter_distance`, `blade_angle`, and `tangential_speed` are 0.25 s bucket means on the opponent frame: signed `(head - hips)` on the fighter's right, horizontal hip-to-hip distance, signed shoulder line angle (0 square, positive lead-left), and signed hips speed along the fighter's right on consecutive ticks (positive counterclockwise). |
| Punishment | Three float meters in `punishment.bin`. Channel 0 rises on a hit and decays to zero. They are not damage: per-punch `damage` comes from the hit event. |
| Combinations | A new combination starts when launch ticks are more than 0.65 s apart, and a combination does not cross a round. `single_shot_percent` is the share of one-punch combinations. `alternating_hand_percent` is the share of multi-punch combinations whose hands strictly alternate. Depth is the punch's place in the combination (`1`, `2`, `3`, `4`, `5+`): thrown, landed, accuracy, mean speed, and the share countered. A punch is countered when a hit by the opponent falls in that punch's throwing or recovery window. A pattern is the trajectory sequence (`jab-cross-left_hook`). `uppercut`, `overhand`, and `unknown` are prefixed with the hand. `mean_damage` is the mean, over times that pattern was thrown, of the summed damage of its landed punches. A miss counts as 0. `mean_damage_landed` is the mean damage of punches in the pattern that landed. The table does not rank which pattern suits a fighter. |
| Vulnerability | From each of this fighter's launch ticks: `while_throwing` is within 0.15 s before or after a launch, `post_punch_recovery` is the open interval through 0.60 s after a launch and outside every throwing window, and `neutral_guard` is every other bell-to-bell tick. Each hit taken goes to one window. A throwing window wins over recovery, and an overlap goes to the closest launch. `hit_share` and `time_share` are percents. `risk_ratio` is hit share divided by time share. Opponent accuracy uses the opponent's punch launches in that state. |
| Situational context | `context` (fight-level and per completed round) partitions bell-to-bell time, punches (at `launch_tick`), and hits taken (at `event.tick`) across four mutually exclusive state dimensions, reporting time, share, pace (PPM), landed/thrown/accuracy/speed/damage dealt, guard/off-hand/off-centerline/square-stance percentages, hits/damage/stuns taken, and countered rate per bucket: `by_stun_state` (4.0 s strictly after a `stun` or `punishment_stun` blow, clipped to active fighting spans, verified against AI `stiffness.bin` recovery at +4.00 s: `neutral`, `opponent_stunned`, `self_stunned`, and `both_stunned` when present), `by_punishment_state` (causal `punishment_0 / MidPunishmentSettings.MeterCapacity` meeting or exceeding that track's `CriticalThreshold`: `neutral`, `opponent_hurt`, `self_hurt`, and `both_hurt` when present), `by_range_zone` (`outside` > 1.35 m, `pocket` 0.85–1.35 m, `clinch` < 0.85 m), and `by_engagement_state` (combining attacking from launch through end + 0.30 s with `under_fire` into `neutral`, `leading`, `under_fire`, and `exchange`). The `stunned` and `punishment_ratio` 0.25 s series expose the underlying per-corner masks over time. |
| Exchange | A run of 1-second bins where each fighter has at least 2 punch records |
| Stun / knockdown / knockout | `stun` is a hit taken whose byte 8 is `6`, and `punishment_stun` one whose byte 8 is `7`. `knockdown` is timed at the blow that starts the count (byte 8 is `2` punishment knockdown, `3` flash knockdown, `4` TKO stoppage blow, or `5` KO stoppage blow). `knockout` and `tko` stoppage moments are timed at the fight-over phase marker on the corner the scorecard flags knocked out or technically knocked out. |
| Fight time | A type-5 event marks a change of match phase (byte 9: `2` warning, `4` fight, `3` round end, `5`/`6` knockdown count, `9` fight over, `10` end of recording). A round ends at its first round-end or fight-over marker, so a stoppage ends it there. `duration_sec` and punches per minute use fighting time: bell to end, less the knockdown counts. Frame-based measures leave out the samples inside a count. |
| Session kind | Sessions scheduled as `1x0:35` (1 round of 35 s) or carrying training/defensive markers in `m_matchType` / `m_activityType` (e.g. `MatchSingleplayerDefenseTraining`) are flagged `session_kind="training"` (`is_training=true`). All other bouts are flagged `session_kind="match"`. |

`decode_status` on every report marks each field `confirmed`, `inferred`, or `unavailable`.

## CLI

```bash
totf-analyzer analyze Recordings/session.zip
totf-analyzer analyze Recordings/session.zip --json
totf-analyzer sync --status
totf-analyzer sync
```
