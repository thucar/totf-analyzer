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

- `list_recordings`
- `analyze_recording` — compact analytics summary (`include_series=False`, `include_punches=False`, `include_moments=False`, `max_patterns=5` by default; pass `True` / `None` for the full report)
- `get_fighter_stats` — one corner (`1` blue, `2` red; `include_punches=False`, `max_patterns=10` by default)
- `get_punches` — per-punch rows for one corner (`1` blue, `2` red), optional `round_index` and `landed_only=True`
- `get_key_moments` — optional `type` (`stun`, `knockdown`, `knockout`, `exchange`, `punishment_spike`, `high_velocity_landed`, `head_drop`, `hurt_event`, `angle_cut`, `duck`, `bob_and_weave`), `corner`, and `round_index` filters
- `get_series` — `punishment_0`, `punishment_1`, `punishment_2`, `guard_up`, `left_guard_up`, `right_guard_up`, `guard_brace`, `guard_friction`, `guard_mass`, `guard_ladder`, `head_speed`, `head_height`, `hips_x`, `hips_z`, `head_slip_lateral`, `fighter_distance`, `blade_angle`, `tangential_speed`, `punch_density`, `stiffness_max`. Optional `round_index` returns that round with time starting at the bell.

## What the numbers mean

| Measure | Definition |
| --- | --- |
| Thrown | `kinematic_thrown` plus `contact_thrown`. A record in `punches.bin` whose byte 9 is `0` is a swing the game detected, with a class and a speed, and always counts. Every other record is a fixed 12-tick glove-contact stamp, which the game also writes for blocks, glove clashes, and pushes. A contact record counts when its glove closed on the opponent's head, chest, spine, or hips at 4.0 m/s or more (3-tick mean) in the 0.15 s before the contact, and it does not fall inside a swing already counted on that hand or within 0.10 s of its end. A slower contact record also counts when an official scored hit that no counted punch explains falls from 0.025 s before to 0.05 s after its contact tick. `discarded_records` is the number left out. An AI opponent's track has contact records only, so its punches that touched nothing are not recorded and its thrown count is a lower bound. |
| Landed | Type-1 events on the defender's track with flag byte 8 set. That count is the defender's official hits taken, and the attacker's landed punches. |
| Accuracy | Landed / thrown |
| Hand | Record byte 10: `0` right, `1` left. Confirmed when that wrist moves more than the other from launch to end. |
| Trajectory | Byte 32: `1` jab, `2` cross, `3` left_hook, `4` right_hook, `6` uppercut. Class `0` is the wrist's launch-to-peak displacement in the opponent frame (forward, up, right). For a contact record that displacement is taken over the 0.15 s before the contact. |
| Speed | Float at punch-record offset 80, treated as m/s |
| Punch row | `launch_sec` is `launch_tick` (offset 12) and `t_sec` is the end tick (offset 0). `impact_sec` is the matched defender scored-hit tick when `landed` is true. `combo_id` (1-based within the offense block), `combo_depth` (`1`..`4`, `5+`), and `countered` use the same launch-gap groups and counter windows as `combinations`. `head_slip_m` is signed `(head - hips)` on the fighter's right at `launch_tick`. `get_punches` also includes `punch_type` as an alias of `trajectory`. |
| Guard up | Both glove centers within 0.38 m below head joint 4 and 0.40 m horizontally. A glove center is the wrist extended along the forearm by half of `m_scaledHandLength` (0.095 m if the snapshot omits it). Fight-level percent uses bell-to-bell ticks only. `left_guard_up_percent`, `right_guard_up_percent`, `both_guard_up_percent`, and `either_guard_up_percent` use that same box per hand. `both_guard_up_percent` is `guard_up_percent`. Each is also reported under fire. |
| Off-hand kept | At a kinematic punch's peak glove extension (byte 9 is 0), the other glove's drop below the head is under 0.28 m and its horizontal distance is under 0.38 m. A glove above the head has drop 0. Reported overall and when throwing left or right. Drop and horizontal flare (median, p90) are split by lead and rear: orthodox lead is left, southpaw lead is right. |
| Retraction | From that peak until the punching glove re-enters the same 0.28 / 0.38 m box, the next same-hand launch, or 800 ms. A glove already in that box at the peak, or a same-hand launch before re-entry, is excluded. `retraction_returned_percent` is returns divided by returns plus misses, kinematic punches only. Time is median, mean, and p90 of returns. Droop is the largest drop of head-relative glove height below the straight chord from peak to re-entry; `sag_over_10cm_percent` is the share of returns whose droop exceeds 0.10 m. Directness is chord length divided by path length, in [0, 1], as median and mean. |
| Footwork | Hips joint 0 from the bell through the end bell. The warning and the time after the end bell are left out. Radial and tangential distances are absolute step lengths on the opponent frame (forward toward the opponent's hips, right is the fighter's right). `total_distance_m` is their sum, and `tangential_share` is tangential divided by that sum. Positive tangential motion is counterclockwise around the opponent when viewed from above. Clinch is under 0.85 m, pocket is 0.85 m through 1.35 m, and outside is beyond 1.35 m. Shoulder blade (joints 6 and 10) and foot blade (joints 15 and 19) are the median absolute angle of that horizontal line against the fighter's right: 0 is square to the opponent and 90 points at the opponent. Square stance is a shoulder angle under 15 degrees. Lead left is a signed shoulder angle of at least 15 degrees. Square while punching uses the shoulder angle at each punch's launch tick. An angle cut merges 0.75 s windows in which this fighter's own hips sweep at least 20 degrees around the opponent while the hips stay under 1.8 m apart. Entry and exit angles use that same sweep. A new punch group starts when launch ticks are more than 0.65 s apart. Entry runs from the first launch to the last punch's end. Exit is the next 0.5 s, stopping at the end bell. Foot blade is inferred because Quest ankle joints are IK-estimated. |
| Under fire | 0.05 s before through 0.30 s after each opponent punch record |
| Head | Skeleton joint 4. `head_lateral_range` is the horizontal extent, hypot(max x − min x, max z − min z). `head_movement` uses frames from the bell through the end bell. Lateral slip is the absolute projection of (head − hips) onto the fighter's right, the same axis as footwork. Off centerline is a slip of at least 0.10 m, reported overall, under fire, and on frames inside this fighter's own launch-to-end punch interval. `head_height_iqr_m` is the interquartile range of head height. `p05_p95_span_m` is the 95th percentile of head height minus the 5th. `pelvis_drop_iqr_m` is the interquartile range of hips height below its 90th percentile. `trunk_bend_iqr_m` is the interquartile range of head height minus hips height. A duck merges 0.8 s windows where head height falls and rises at least 0.15 m around an interior trough. A bob-and-weave merges 1.0 s windows with that shape at 0.12 m and a lateral-slip range of at least 0.12 m. The two counts are independent. Quest hips are the recorded root joint, not an optical measurement. |
| Guard channels | `guard_brace`, `guard_friction`, `guard_mass`, and `guard_ladder` are uint16 samples scaled by the header min/max. Schema 15 ranges are brace [0, 8], friction [0, 4], mass [0, 8], ladder [0, 5]. |
| Biomechanical series | `left_guard_up` and `right_guard_up` are 1.0 s bucket shares in [0, 1] using the same head-relative box as `guard_up`. `hips_x` and `hips_z` are 0.25 s bucket means of world horizontal hip coordinates in meters. `head_slip_lateral`, `fighter_distance`, `blade_angle`, and `tangential_speed` are 0.25 s bucket means on the opponent frame: signed `(head - hips)` on the fighter's right, horizontal hip-to-hip distance, signed shoulder line angle (0 square, positive lead-left), and signed hips speed along the fighter's right on consecutive ticks (positive counterclockwise). |
| Punishment | Three float meters in `punishment.bin`, separate from official received damage |
| Combinations | A new combination starts when launch ticks are more than 0.65 s apart, and a combination does not cross a round. `single_shot_percent` is the share of one-punch combinations. `alternating_hand_percent` is the share of multi-punch combinations whose hands strictly alternate. Depth is the punch's place in the combination (`1`, `2`, `3`, `4`, `5+`): thrown, landed, accuracy, mean speed, and the share countered. A punch is countered when an opponent scored hit falls in that punch's throwing or recovery window. A pattern is the trajectory sequence (`jab-cross-left_hook`). `uppercut`, `overhand`, and `unknown` are prefixed with the hand. `mean_punishment_delta` is the mean, over times that pattern was thrown, of the sum of landed punishment steps in that instance. A miss or a missing step counts as 0. `mean_punishment_delta_landed` is the mean step on punches in the pattern that landed. Those steps are punishment channels 0+1, not official received damage. The table does not rank which pattern suits a fighter. |
| Vulnerability | From each of this fighter's launch ticks: `while_throwing` is within 0.15 s before or after a launch, `post_punch_recovery` is the open interval through 0.60 s after a launch and outside every throwing window, and `neutral_guard` is every other bell-to-bell tick. Each scored hit taken goes to one window. A throwing window wins over recovery, and an overlap goes to the closest launch. `hit_share` and `time_share` are percents. `risk_ratio` is hit share divided by time share. Opponent accuracy uses the opponent's punch launches in that state. |
| Exchange | A run of 1-second bins where each fighter has at least 2 punch records |
| Stun / knockdown / knockout | Event type codes whose counts match that corner's scorecard totals |

`decode_status` on every report marks each field `confirmed`, `inferred`, or `unavailable`.

## CLI

```bash
totf-analyzer analyze Recordings/session.zip
totf-analyzer analyze Recordings/session.zip --json
```
