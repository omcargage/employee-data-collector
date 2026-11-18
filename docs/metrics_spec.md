# EDC Metrics Specification (v0.1 draft)

This file is the contract between the collector and the ML model. It is meant to be placed at `docs/metrics_spec.md` and used as the content for Prompt 1. Review it, change anything you disagree with, and only then let the coding agent implement it.

Feasibility tags: **DIRECT** (computed from input events), **PROXY** (indirect; says what it really measures), **CONFIG** (needs a per-person setting), **EXTERNAL** (needs another data source), **EXCLUDED** (not available).

---

## 1. Conventions

**Time**
- All timestamps are stored in UTC. Local time is derived using the employee's configured IANA timezone (default `Asia/Kolkata`).
- **Logical day:** a day runs for 12 hours from IST 07:00 AM to 06:59 PM (18:59:59 IST) of the same day. All `day`, `day_of_week` and daily rollups use this logical day.
- `day_of_week`: 0 = Monday ... 6 = Sunday. `is_weekend`: day_of_week in {5, 6}, unless overridden in the employee's config.

**Windows**
- 15-minute windows are aligned to :00, :15, :30, :45 local time. Daily rollups cover one logical day.
- Every rollup carries `coverage_ratio` = covered_seconds / window_seconds, where covered time is time the agent was running **and** received a heartbeat from the input hooks.
- Windows with `coverage_ratio < 0.5` are stored but flagged `low_coverage = true` and excluded from training by default.

**Gap types** (a gap = time between two consecutive input events)
- `idle`: agent running, system awake, no input.
- `away`: the OS reported lock, sleep or suspend during the gap. Counts as a valid break when it falls between two sessions in the logical day and is <= `break_max_s`.
- `unknown`: agent not running or crashed. This is **missing data**, never a break, never zero activity.

**Null rule:** if a statistic lacks enough observations (thresholds in section 2), store `null`. Never store 0 as a stand-in for "not enough data".

**Privacy rule:** events are reduced at capture to a class (`char`, `backspace`, `delete`, `modifier`, `other`) plus timestamp. No key identity is stored at any layer.

---

## 2. Thresholds (all in config, per-person overridable)

| Name | Default | Used for |
|---|---|---|
| `typing_gap_max_ms` | 2000 | Flight times above this are pauses, not typing flow |
| `idle_threshold_s` | 60 | Input gap that counts as idle |
| `session_break_gap_s` | 300 | A gap this long ends a session and counts as a break |
| `break_max_s` | 10800 (3 h) | Longer gaps are "long absence", not counted in average break length |
| `min_session_s` | 120 | Sessions shorter than this are ignored in session stats |
| `extended_session_min` | 90 | Session counts as "extended" at or above this |
| `stretch_break_gap_s` | 600 | A gap this long ends a "continuous stretch" (more tolerant than a session) |
| `focus_gap_s` | 120 | Gap that interrupts a focus block |
| `focus_block_min` | 10 | Minimum length of a focus block |
| `deep_work_min` | 25 | Minimum length of a deep-work block |
| `burst_min_keys` | 5 | Keys in a typing burst |
| `burst_max_flight_ms` | 500 | Max flight time inside a burst |
| `long_silence_s` | 5 | Silence after a burst that counts as "long" |
| `backspace_burst_min` | 3 | Backspaces in a run to count as a burst |
| `backspace_burst_gap_ms` | 500 | Max gap inside a correction run |
| `min_flight_intervals` | 10 | Needed to report flight-time mean/std |
| `min_keystrokes` | 30 | Needed to report WPM and ratios |
| `min_clicks` | 5 | Needed to report click-interval stats |
| `double_click_ms` | OS setting | Read from the OS, default 500 |
| `double_click_px` | 4 | Max pointer movement between the two clicks |
| `rapid_click_n` / `rapid_click_s` | 3 / 1.0 | Rapid repeated clicking |
| `mouse_bin_ms` | 100 | Pointer sampling bin for speed/acceleration |
| `mouse_jump_px` | 3000 | Per-bin jumps above this (monitor switch, remote desktop) are dropped |
| `shift_start` / `shift_end` | 09:00 / 18:00 | Per-person config |
| `lunch_window` | 12:00-14:00 | Per-person config |
| `late_night_window` | 22:00-05:00 | Late-night definition |
| `after_hours_day_min` | 30 | Active minutes after hours for the day to count as an after-hours day |
| `late_night_min` | 10 | Active minutes in the late-night window to set the flag |
| `no_lunch_break_min` | 15 | Longest lunch-window gap below this means no real lunch break detected |

**Active minute:** a calendar minute containing at least one keyboard or mouse input event (not counting modifier-only events).

---

## 3. Per-window building blocks (stored, so metrics can be recomputed and merged exactly)

For each 15-minute window, store raw counts and sufficient statistics, not only final metrics.

- Counts: `n_char`, `n_backspace`, `n_delete`, `n_other_key`, `n_clicks`, `n_double_clicks`, `n_rapid_click_runs`, `n_scroll_ticks_abs`, `n_scroll_reversals`.
- Flight times (ms, gaps <= `typing_gap_max_ms`): `n`, `sum`, `sum_sq`, plus a histogram with fixed bins (0-100, 100-200, 200-300, 300-500, 500-1000, 1000-2000).
- Click intervals (s, gaps <= 5 s): `n`, `sum`, `sum_sq`.
- Pointer: `n_moving_bins`, `sum_speed`, `n_accel_samples`, `sum_abs_accel`.
- Time: `covered_s`, `active_typing_s`, `active_minutes`, `idle_s`.
- Bursts: `n_bursts`, `sum_burst_len`, `n_long_silences_after_burst`.
- Corrections: `n_correction_runs`, `n_backspace_bursts`, `sum_pause_before_correction_ms` (pauses capped at 10 s).
- Dwell (only if capability `key_dwell` is true): `n`, `sum`, `sum_sq`.

Merging windows means adding counts and sums. Mean = sum/n. Sample standard deviation = sqrt((sum_sq - sum^2/n) / (n - 1)).

---

## 4. Keyboard metrics (15-minute window)

| Column | Definition | Tag |
|---|---|---|
| `day_of_week`, `is_weekend` | From logical day | DIRECT |
| `hour_of_day` | Local hour of window start | DIRECT |
| `decimal_hour` | hour + minute/60 of window start | DIRECT |
| `session_index_in_day` | 1-based index of the session in which the window starts; null if the window has no active session | DIRECT |
| `total_keystrokes` | `n_char + n_backspace + n_delete + n_other_key` (modifier-only presses excluded; held-key auto-repeat of `char`/`other` keys counted once) | DIRECT |
| `char_keystrokes` | `n_char` | DIRECT |
| `backspace_count`, `delete_count` | Counts. Auto-repeat of a held Backspace/Delete **is** counted, since it is a real correction | DIRECT |
| `total_correction_keys` | `backspace_count + delete_count` | DIRECT |
| `repeated_backspace_bursts` | Number of runs of >= `backspace_burst_min` backspaces with gaps <= `backspace_burst_gap_ms` | DIRECT |
| `mean_flight_time_ms` | Mean of flight times (time between consecutive non-modifier key presses, <= `typing_gap_max_ms`); null if n < `min_flight_intervals` | DIRECT |
| `flight_time_std_ms` | Sample std of the same; null if n < `min_flight_intervals` | DIRECT |
| `active_typing_ratio` | `active_typing_s / covered_s`, where `active_typing_s` is the sum of valid flight times | DIRECT |
| `gross_wpm` | `(char_keystrokes / 5) / (active_typing_s / 60)`; null if `total_keystrokes < min_keystrokes` | DIRECT |
| `net_wpm` | `max(0, char_keystrokes - total_correction_keys) / 5 / (active_typing_s / 60)`; same null rule. Approximation: each correction key removes about one character | PROXY |
| `backspace_ratio` | `backspace_count / total_keystrokes` | DIRECT |
| `correction_ratio` | `total_correction_keys / total_keystrokes` | DIRECT |
| `error_correction_efficiency` | `max(0, char_keystrokes - total_correction_keys) / char_keystrokes`. Fraction of typed characters surviving corrections. Open decision, see section 9 | PROXY |
| `pause_before_correction_ms` | Mean over correction runs of the gap between the previous keystroke and the first correction key (gaps > 10 s excluded). Correction run = correction keys with gaps <= `backspace_burst_gap_ms` | DIRECT |

**Additional columns beyond the original spec** (cheap to compute, relevant to "burst typing followed by long silences"):
`n_bursts`, `mean_burst_len`, `n_long_silences_after_burst`, `burst_to_silence_ratio` (= `n_bursts / max(1, n_long_silences_after_burst)`).

**Keystroke timing block (Unified Names)**

| Column | Definition |
|---|---|
| `total_keystrokes` | Total count of key events (unified canonical name; `keystroke_count` dropped as alias) |
| `keystrokes_per_second` | `total_keystrokes / covered_s` |
| `mean_flight_time_ms` | Mean of flight times in ms (unified canonical name; `average_keystroke_interval_seconds` dropped as redundant alias) |
| `flight_time_std_ms` | Sample std of flight times in ms (unified canonical name; `keystroke_interval_stdev_seconds` dropped as redundant alias) |
| `keystroke_coefficient_of_variation` | `flight_time_std_ms / mean_flight_time_ms` |

**Typing speed drift from baseline** is **not computed on the device.** It is derived in the ML pipeline as a z-score against the person's own rolling median and spread, so it always uses the latest baseline.

**Dwell time (key hold duration):** PROXY/optional. Only reported if the platform provider declares `key_dwell: true` and key-up events are verified in testing. Otherwise the columns are null and the capability is recorded as unavailable.

---

## 5. Mouse metrics (15-minute window)

| Column | Definition | Tag |
|---|---|---|
| `timestamp` | Window start (UTC) | DIRECT |
| `click_count` | Button-down events (left, right, middle) | DIRECT |
| `clicks_per_second` | `click_count / covered_s` | DIRECT |
| `average_interval_seconds` | Mean time between consecutive clicks, gaps <= 5 s; null if n < `min_clicks` | DIRECT |
| `click_interval_stdev_seconds` | Sample std of the same | DIRECT |
| `coefficient_of_variation` | std / mean of click intervals | DIRECT |
| `average_speed_px_s` | Mean speed over bins where the pointer moved, in logical pixels per second. Bins with jumps > `mouse_jump_px` are dropped. The display scale factor is recorded alongside | DIRECT |
| `average_abs_accel_px_s2` | Mean `abs(delta speed / delta t)` across consecutive moving bins | DIRECT |
| `total_abs_scroll_ticks` | Sum of absolute scroll ticks | DIRECT |
| `average_abs_scroll_ticks_s` | `total_abs_scroll_ticks / covered_s` | DIRECT |

**Additional columns:** `double_click_count`, `rapid_click_runs`, `scroll_reversal_count` (direction changes within 5 s; proxy for "aimless" scrolling), `pointer_idle_s` (seconds with no mouse input).

**Excluded:** click force / hard taps (EXCLUDED, not available through standard mouse APIs).

**"Staring at the screen" (combined input idle):** PROXY. The collector does not read window or app state. It reports `short_idle_total_s` = total of combined keyboard AND mouse input silence gaps between `idle_threshold_s` and `session_break_gap_s`, meaning idle moments that did not end the session.

---

## 6. Session, break, stretch, lunch and focus metrics (daily)

**Definitions**
- **Session:** a run of input events where consecutive gaps are < `session_break_gap_s`. Duration = last event - first event. Sessions shorter than `min_session_s` are ignored.
- **Break:** a gap >= `session_break_gap_s` and <= `break_max_s`, located between two sessions within the same logical day, and of type `idle` or `away`. `unknown` gaps are never breaks.
- **Continuous stretch:** a run of events where gaps are < `stretch_break_gap_s`. Because it tolerates micro-breaks up to 10 minutes, it differs from a session and is not redundant with `max_session_duration_mins`.
- **Focus block:** a run where gaps are < `focus_gap_s`, lasting >= `focus_block_min`. A **deep-work block** lasts >= `deep_work_min`.

| Column | Definition | Tag |
|---|---|---|
| `day`, `is_weekend` | Logical day | DIRECT |
| `avg_session_duration_mins` | Mean session duration | DIRECT |
| `max_session_duration_mins` | Longest session | DIRECT |
| `total_breaks_count` | Number of breaks | DIRECT |
| `avg_break_duration_mins` | Mean break length (breaks > `break_max_s` excluded); null if no breaks | DIRECT |
| `extended_sessions_count` | Sessions >= `extended_session_min` | DIRECT |
| `longest_stretch_duration_mins` | Longest continuous stretch | DIRECT |
| `stretch_start_hour` | Local decimal hour when that stretch began | DIRECT |
| `post_stretch_break_mins` | Length of the gap following that stretch; null if the day ended | DIRECT |
| `stretch_intensity_pct` | `100 * active_minutes_in_stretch / stretch_minutes` | PROXY |
| `stretch_to_total_work_ratio` | `longest_stretch_minutes / total_work_minutes`, where total work = sum of session durations | DIRECT |
| `lunch_active_mins` | Active minutes inside `lunch_window` | DIRECT |
| `longest_lunch_break_mins` | Longest input gap overlapping `lunch_window`, clipped to the window; null if the window is mostly `unknown` | DIRECT |
| `lunch_work_ratio` | `lunch_active_mins / lunch_window_minutes` | DIRECT |
| `lunch_skipped_flag` | True if `longest_lunch_break_mins < no_lunch_break_min`. **Reports "no lunch break detected"**, not a fact about eating | PROXY |
| `desk_dining_flag` | Dropped per user decision (redundant with `lunch_skipped_flag`) | EXCLUDED |
| `avg_focus_block_mins` | Mean focus-block duration; null if none | PROXY |
| `max_focus_block_mins` | Longest focus block | PROXY |
| `deep_work_blocks_count` | Number of deep-work blocks | PROXY |
| `total_focus_time_hours` | Sum of focus-block durations / 60 | PROXY |
| `focus_fragmentation_ratio` | `1 - total_focus_time / total_work_time`, bounded 0-1. Higher means more fragmented | PROXY |

Focus metrics are behavioural proxies. They show uninterrupted input, not concentration, because the collector does not know which application the person is using.

---

## 7. Work-hours and after-hours metrics (daily)

| Column | Definition | Tag |
|---|---|---|
| `day_of_week`, `is_weekend` | As in section 1 | DIRECT |
| `shift_start`, `shift_end` | From the employee's config (default 09:00-18:00) | CONFIG |
| `after_hours_active_minutes` | Active minutes outside `[shift_start, shift_end]`, or all active minutes on non-working days | DIRECT |
| `after_hours_ratio` | `after_hours_active_minutes / total_active_minutes`; null if total is 0 | DIRECT |
| `late_night_flag` | True if active minutes in `late_night_window` >= `late_night_min` | DIRECT |
| `after_hours_ratio_7d_avg` | Mean of `after_hours_ratio` over the last 7 logical days with `coverage_ratio >= 0.5`; null if fewer than 4 valid days | DIRECT |
| `consecutive_after_hours_days` | Count of consecutive days ending today with `after_hours_active_minutes >= after_hours_day_min` | DIRECT |

---

## 8. Not computable by the keyboard/mouse collector

| Columns | Reason | Tag |
|---|---|---|
| `total_msgs_sent`, `msgs_sent_after_hours`, `msgs_sent_late_night`, `first_msg_time`, `last_msg_time` | Computed via Option 2 desktop process heuristic (monitoring foreground communication applications: Slack, Teams, Outlook, etc.) | DIRECT |
| Click force / hard taps | No standard API | EXCLUDED |
| `profile` | A person identifier. Join at export time; never a feature | n/a |
| `state` | A label (e.g. self-reported stress). Join at export time from the self-report table; never computed on the device | n/a |

---

## 9. Decisions and Resolutions

1. **Logical day boundary:** Runs for 12 hours from IST 07:00 AM to 06:59 PM (18:59:59 IST) of the same day.
2. **`error_correction_efficiency`:** Fraction of typed characters surviving corrections: `max(0, char_keystrokes - total_correction_keys) / char_keystrokes`.
3. **Sleep/lock gaps:** Count as valid breaks when falling between two sessions in the logical day and duration <= `break_max_s`.
4. **`desk_dining_flag`:** Dropped (subsumed by `lunch_skipped_flag`).
5. **Default thresholds:** Retained (5-minute break, 10-minute stretch gap, 90-minute extended session, 2-second typing gap).
6. **Extra columns:** Retained (bursts, double clicks, scroll reversals, short idle time).
7. **Keystroke timing column naming:** Unified canonical names used (`total_keystrokes`, `mean_flight_time_ms`, `flight_time_std_ms`, `keystroke_coefficient_of_variation`).
8. **Short idle scope:** Combined keyboard AND mouse input silence.
9. **Daily session aggregation:** Daily rollups compute directly from session/stretch runs tracked across the logical day in SQLite.

