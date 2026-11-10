---
title: "Real-time fNIRS neurofeedback (NIRx/Aurora + PsychoPy) — Technical documentation"
lang: en
---

# Real-time fNIRS neurofeedback (NIRx/Aurora + PsychoPy) — Technical documentation

Research tool for real-time fNIRS neurofeedback (NIRSport2 + Aurora), with PsychoPy presentation.

Conventions: "TBC (to be confirmed)" = the code does not allow a statement, or the item depends on field verification. Everything else describes what the code does (review of the scripts in the project folder).

Regarding its modular architecture (separate threads/windows for stream, processing and visualization), the system was inspired by a reference EEG neurofeedback system (repository `Neurofeedback-with-MNE-and-PsychoPy`). No code from it is copied into this project; its signal layer (ASR/ICA, PSD) does not apply to fNIRS and was replaced.

Portuguese original: [pt-BR/DOCUMENTACAO_TECNICA.md](pt-BR/DOCUMENTACAO_TECNICA.md).

## 1. Overview and architecture

### 1.1 The 5 layers

| # | Layer | Implementation |
|---|---|---|
| 1 | Paradigm / markers | Phases controlled by `nfb_process.py` (baseline → regulation → stop); markers published on the LSL stream `Trigger` |
| 2 | Acquisition | `acquisition.py` (`pylsl`, column mapping from the metadata) |
| 3 | Processing | `processing.py` (`FeaturePipeline`) |
| 4 | Visualization | `trail_display.py` (`TrailDisplay`, PsychoPy) |
| 5 | Log | `nf_logger.py` (`Logger`, CSV + metadata JSON) |

The file `Fingertapping_LSL.psyexp` (synchronization test, PsychoPy Builder) is the reference for how the trigger is emitted; it is not part of the code in this folder and is not the final task.

### 1.2 The two processes

```
 PROCESS A                                    PROCESS B
 control_panel.py (tkinter)                   nfb_process.py (PsychoPy)
 floating panel, 2nd monitor                  neurofeedback window
        |                                            |
        |   run/nfb_command.json  (commands)         |
        |  ------------------------------------->   |  reads at 30 Hz
        |                                            |
        |   run/nfb_state.json    (state)            |
        |  <-------------------------------------   |  writes every tick
        |  reads every 300 ms                        |
        +----------- session_ipc.py -----------------+
         (atomic write tmp + os.replace, retry)
```

The panel (A) talks LSL directly only in the Configurações (Settings) tab ("Detectar canais"), with an inlet independent of the one process B opens during the session. The whole session is driven by commands (`CONFIGURE`, `SYNC`, `PLAY`, `START_NFB`, `STOP`) sent through a file.

### 1.3 End-to-end data flow

```
 NIRSport2 -> Aurora --(LSL Data Out, name "Aurora")--> acquisition.py
                                                          |  StreamMap (columns from metadata)
                                                          |  Acquisition.pull/drain (drops NaN)
                                                          v
                                          SignalWorker (thread, run_neurofeedback.py)
                                                          |  add_sample(device_time, ROI HbO)
                                                          v
                                          processing.py  FeaturePipeline
                                       ROI mean -> window -> z-score(baseline) -> clip -> EMA
                                                          |  altitude (ALTITUDE_RANGE units)
                                                          v
                                          trail_display.py  TrailDisplay
                                          (progress 0-1 on the trail, extra smoothing)
                                                          |
                                          nf_logger.py <--+  one row per tick (~30 Hz)

 nfb_process.py --(LSL, StreamOutlet "Trigger", type Markers, int32)--> Aurora (Trigger In)
   codes: 1 = baseline start | 2 = regulation start | 3 = stop
```

`Trigger` is published by `nfb_process.py` from the moment `NfbSession` is created (not only at PLAY), so that the SYNC step finds a `Markers` stream without depending on another process.

## 2. Scripts

Format: purpose; inputs/outputs; main classes and functions; callers; dependencies.

### 2.1 Core

#### `nf_config.py`
- **Purpose:** central parameters. No logic.
- **Inputs/outputs:** constants read by almost every module. Defines `BASE_DIR`, `LOG_DIR` (`logs/`), `RUN_DIR` (`run/`).
- **Callers:** all. **Dependencies:** `os`.
- Full table in section 3.

#### `acquisition.py` (Layer 2)
- **Purpose:** connect to the LSL Data Out stream and map columns from the metadata (never by fixed index).
- **Inputs:** stream name (`cfg.STREAM_NAME` or argument), list of `(source, detector)` pairs of the ROI. **Outputs:** tuples `(lsl_ts, device_ts, ROI_HbO_vector)`.
- `_translate_type(raw_type, wavelength)` — translates the real metadata `type` (`nirs_hbo` → `HbO`, etc.; `nirs_raw` + `wavelength` → `raw760`/`raw850`).
- `_parse_source_detector(custom_name, label)` — extracts `S{n}`/`D{n}` from `custom_name`, with fallback to `label`.
- `StreamMap` — column index built from `StreamInfo`; methods `columns`, `pfc_hbo_columns`, `short_hbo_columns`, `timestamp_column`. Raises `RuntimeError` if ROI channels are missing or the metadata is incomplete.
- `Acquisition` — resolves the stream by name (`resolve_byprop("name", ...)`), creates the inlet (`max_buflen=60`, `recover=False`); `pull`, `drain`, `close`. A sample with any NaN/Inf in the ROI channels is discarded (`n_invalid`) and never overwrites the last valid one.
- **Callers:** `nfb_process.py`, `run_neurofeedback.py`, `control_panel.py` (only `StreamMap`), tests. **Dependencies:** `pylsl`, `numpy`, `nf_config`.

#### `processing.py` (Layer 3)
- **Purpose:** feature = mean HbO of the ROI channels → sliding window → baseline z-score → clipping → exponential smoothing.
- `FeaturePipeline` — internal states `baseline`, `baseline_ready` (only if `manual_gate=True`), `running`, `failsafe`. Methods: `add_sample(t, pfc_hbo)`, `begin_regulation()`, `update_display(now)`, `mark_sample_received(wall_time)`, `snapshot()`.
- **Callers:** `SignalWorker`, `NfbSession`. **Dependencies:** `numpy`, `nf_config`.

#### `trail_display.py` (Layer 4)
- **Purpose:** explorer on a mountain trail; progress (0–1) derived from the pipeline altitude.
- `position_on_trail(progress, points)` — linear interpolation between the 6 waypoints (`TRAIL_POINTS_NORMALIZED`, converted from top-left-origin coordinates to the PsychoPy centered system).
- `TrailDisplay` — window (`visual.Window`, 1280×720 by default), background `trail_bg.png`, sprite `hiker_sprite.png` anchored at the feet (`bottom-center`), status and warning text; `draw(altitude, snap, dt)`, `should_quit()` (Esc key), `close()`. Applies additional smoothing to the progress (`SMOOTHING_SPEED = 1.2`).
- **Callers:** `NfbSession.ensure_display`, `run_neurofeedback.run`. **Dependencies:** `psychopy`, `PIL`, `nf_config`. The PNGs are read from the same folder as the script.

#### `nf_logger.py` (Layer 5)
- **Purpose:** one CSV per session + a metadata JSON.
- `Logger(prefix, meta, log_dir)` — creates `logs/<prefix>_<YYYY-MM-DD_HHMMSS>.csv` and `..._meta.json`; `write(...)` writes a row; `close()`.
- CSV columns: `wall_iso, wall_unix, lsl_time, device_time, state, raw_feature_hbo, windowed_hbo, normalized, smoothed, altitude, valid, n_valid, n_invalid, marker`. `lsl_time`/`device_time` allow reconciliation with the Aurora `*_lsl.tri` (reconciliation procedure: TBC).
- **Callers:** `NfbSession`, `run_neurofeedback.run`, tests. **Dependencies:** `csv`, `json`, `datetime`.

### 2.2 Production application (two processes)

#### `nfb_process.py` (Process B)
- **Purpose:** neurofeedback window, session orchestration, `Trigger` publication.
- `NfbSession` — per-phase state machine (section 5). `handle_command`, `_do_sync`, `_do_play`, `_do_start_nfb`, `_do_stop`, `_emit_marker`, `tick`, `_publish_state`, `run_forever(poll_hz=30)`. The logic is isolated from the display (accepts `display_factory`), allowing tests with a fake display.
- Constant `PLAUSIBLE_HBO_ABS_MAX = 200.0` µmol/L (quality check at SYNC).
- When run as a script: `ipc.reset()` and `NfbSession().run_forever()`.
- **Dependencies:** `pylsl`, `session_ipc`, `acquisition`, `processing`, `nf_logger`, `run_neurofeedback.SignalWorker`, `trail_display` (deferred import).

#### `control_panel.py` (Process A)
- **Purpose:** tkinter panel (Principal and Configurações tabs).
- `ControlPanel` — settings: stream name, "Detectar canais" (thread with `resolve_byprop` + `StreamMap`, lists pairs of type `HbO`), ROI selection by checkboxes (pre-checked: `PFC_CHANNELS`), participant ID and session, "Salvar configuracao" (sends `CONFIGURE`). Main: buttons Sincronizar / PLAY / Iniciar NFB (with confirmation) / STOP, `trigger`/`aurora`/`channels` indicators, per-channel quality, failsafe alert banner, session summary. State polling every 300 ms.
- **Dependencies:** `tkinter`, `pylsl`, `session_ipc`, `acquisition.StreamMap`. Interface text is in Portuguese without accents.

#### `session_ipc.py`
- **Purpose:** IPC through local JSON files (`run/nfb_state.json`, `run/nfb_command.json`).
- `write_state`, `read_state`, `send_command(cmd_id, cmd, payload)`, `read_command`, `reset`; `_atomic_write` (temporary file + `os.replace`, up to 6 attempts with increasing wait to absorb a momentary OneDrive lock); `_read_json` treats a missing/corrupted file as "nothing new".
- **Callers:** `control_panel.py`, `nfb_process.py`, tests.

#### `run_neurofeedback.py`
- **Purpose (dual):** (a) defines `SignalWorker`, used by the production application; (b) is the standalone runner of Layers 2–5, without the panel (inherited from the replay phase).
- `SignalWorker(threading.Thread)` — Layers 2+3 in its own thread: `acq.drain` → `pipeline.add_sample` under `lock`; optional listening to a markers stream (`pending_markers`, `take_markers`); `stop`.
- `run(duration, display, stream_name, log_prefix, fps, quiet)` — main loop of the standalone runner. Command-line arguments: `--duration`, `--no-display`, `--stream`, `--prefix`.
- In the production flow, `take_markers()` is not called by `NfbSession`; the log markers come from `_pending_log_marker`.

### 2.3 Mocks and replay utilities

#### `mock_aurora_lsl.py`
- **Purpose:** LSL replay server that imitates the Aurora Data Out from the cache `replay_hb.npz` (derived from the test `.nirs`, another task, whole-head montage). **Old** schema (anatomical labels in `source`/`detector`, `type` = `HbO`/`raw760`...).
- Functions: `build_stream_info`, `load_cache`, `run(speed, stop_after, loop, name, markers, verbose)`. CLI: `--speed`, `--stop-after`, `--loop`, `--name`, `--no-markers`.
- Also publishes a `Trigger` stream (Markers) with the `.nirs` events (by default).
- **Dependencies:** `numpy`, `pylsl`, `nf_config`; requires `replay_hb.npz`.

#### `mock_aurora_lsl_synthetic.py`
- **Purpose:** continuous-replay mock with synthetic data (AR(1) noise + slow sinusoidal drift; not physiological) already in the **real schema** (`nirs_hbo`/`nirs_hbr`/`nirs_raw`+`wavelength`/`nirs_frame`, `custom_name` `S{n}-D{n}`, empty `source`/`detector`). 8 sources, 15 detectors, 24 pairs (16 long + 8 short), 97 channels (4×24 + 1).
- On import, validates that the pairs of `PFC_CHANNELS` and `SHORT_CHANNELS_FRONTAL` exist in the synthetic topology (`RuntimeError` otherwise).
- Functions: `build_stream_info`, `_ChannelNoise`, `run(...)`. CLI same as `mock_aurora_lsl.py` (`--loop` is accepted but has no effect, generation is infinite). Publishes `Trigger` with value `1` every ~5 s of data, by default.
- **Dependencies:** `pylsl`, `nf_config`. Does not use `mne`.

#### `nirs_to_hb.py`
- **Purpose:** converts the test `.nirs` (Homer2) to HbO/HbR (modified Beer-Lambert, coefficients from `cfg.EXTINCTION`, `cfg.DPF`) and writes the cache `replay_hb.npz`.
- Functions: `load_nirs`, `channel_table`, `intensity_to_od`, `od_to_conc`, `convert`. Used only by the old mock and by the tests that use it. The `.nirs` file referenced in `cfg.NIRS_FILE` is not in the project folder (availability TBC; the cache `replay_hb.npz` is).
- **Dependencies:** `numpy`, `scipy`, `nf_config`.

### 2.4 Tests

Details and coverage in section 7.

| Script | Function |
|---|---|
| `test_acceptance.py` | end-to-end replay acceptance against `mock_aurora_lsl.py` (no display) |
| `test_live_connection.py` | "live" path of `Acquisition` (stream absent / present) |
| `test_session_state_machine.py` | `NfbSession` state machine and IPC, against the synthetic mock |
| `test_real_schema.py` | `StreamMap`, `Acquisition`, panel channel detection and marker publication against synthetic metadata in the real schema |

### 2.5 Other files

- `iniciar_mock.bat` / `iniciar_neurofeedback.bat` — Windows shortcuts that call `C:\Program Files\PsychoPy\python.exe` (path fixed in the `.bat`) for `mock_aurora_lsl.py` and `run_neurofeedback.py --duration 90`. The latter is the legacy standalone runner; **there is no `.bat` for the production application** (`control_panel.py` + `nfb_process.py`).
- `INSTRUCOES_PERSONAGEM_TRILHA.md` — reference document (pygame) from which the trail logic was ported.
- `Psychopy_TrialTypes.xlsx` — not analyzed in this documentation (use TBC).
- `trail_bg.png`, `hiker_sprite.png` — visual assets (in the project root).

## 3. `nf_config.py` parameters

Status: **calibrated** = value validated with real data; **placeholder** = initial value adopted, not calibrated in a pilot; **informative** = does not affect the computation. The classification was derived from the "Pendências" (pending items) section of `CLAUDE.md` and from the code; where there is no evidence, TBC.

| Parameter | Current value | Meaning | Status |
|---|---|---|---|
| `REPLAY_MODE` | `True` | Informative label written to log/metadata; not a code gate | informative |
| `BASE_DIR` / `LOG_DIR` / `RUN_DIR` | script folder / `logs` / `run` | Working directories | — |
| `NIRS_FILE` | `2025-07-09_003.nirs` in the project folder | Test `.nirs` for `nirs_to_hb.py` (file absent from the folder; `CLAUDE.md` cites `2025-04-02_004.nirs`) | TBC |
| `HB_CACHE` | `replay_hb.npz` | HbO/HbR cache for the old mock | — |
| `STREAM_NAME` | `"Aurora"` | Data Out stream name | calibrated (confirmed on the Aurora screen, per `CLAUDE.md`); the "PENDENCIA" comment in the code is outdated |
| `STREAM_TYPE` | `"NIRS"` | Type of the stream published by the mocks | informative |
| `STREAM_SOURCE_ID` | `"mock_aurora_replay"` | `source_id` of the mocks | informative |
| `SERIAL_NUMBER` | `"MOCK-NSP2-0000"` | Fictitious serial number of the mocks | informative |
| `SOURCE_LABELS` / `DETECTOR_LABELS` | 10-20 labels from the test `.nirs` | Used only by `nirs_to_hb.py` (old mock) | informative |
| `PFC_CHANNELS` | `S1-D1, S1-D2, S2-D1, S2-D2, S3-D3, S3-D4, S4-D3, S4-D4` | Pre-selection of the ROI (8 channels). Chosen by geometry; **not anatomically confirmed** | placeholder (pre-selection; final selection is manual in the panel) |
| `SHORT_CHANNELS_FRONTAL` | `S1-D8, S2-D9, S3-D10, S4-D11` | Frontal short channels. Not used in the feedback; used only in the validation of the synthetic mock | placeholder |
| `EXTINCTION` | `{760: (1486.5865, 3843.707), 850: (2526.391, 1798.643)}` | Coefficients (HbO, HbR) used in `nirs_to_hb.py` | informative (offline conversion for the old mock) |
| `DPF` | `6.0` / `6.0` | Differential pathlength factor (old mock) | informative |
| `SHORT_CHANNEL_MAX_CM` | `1.5` | Distance limit to classify a short channel (old mock) | informative |
| `BASELINE_S` | `30.0` | Baseline duration (s), in device time | placeholder |
| `FEATURE_WINDOW_S` | `4.0` | Sliding window of the HbO mean (s) | placeholder |
| `SMOOTH_TAU_S` | `1.5` | Time constant of the exponential smoothing (s) | placeholder |
| `NORM_CLIP` | `3.0` | z-score clipping at ±3 | placeholder (saturation observed in testing; reassess with real data) |
| `FAILSAFE_TIMEOUT_S` | `1.0` | Time without a valid sample (wall clock) to trigger the failsafe | placeholder |
| `GLIDE_TAU_S` | `2.0` | Time constant of the "glide" during the failsafe | placeholder |
| `TRIGGER_SOURCE_ID` | `"nfb_process_trigger"` | `source_id` of the `Trigger` outlet | — |
| `MARKER_BASELINE_START` / `MARKER_REGULATION_START` / `MARKER_STOP` | `1` / `2` / `3` | Marker codes | — |
| `ALTITUDE_RANGE` | `(-0.75, 0.75)` | Internal range of the pipeline output (name inherited from the previous airplane metaphor); rescaled to 0–1 in `trail_display.py` | — |
| `PLANE_X_SPEED` | `0.0` | Not referenced by any script (leftover from the previous metaphor) | informative |
| `WINDOW_SIZE` / `FULLSCREEN` | `(1280, 720)` / `False` | PsychoPy window | — |

Constants outside `nf_config.py`: `SMOOTHING_SPEED = 1.2` and `HIKER_HEIGHT_NORM = 0.48` (`trail_display.py`, additional smoothing and sprite size); `PLAUSIBLE_HBO_ABS_MAX = 200.0` (`nfb_process.py`); `POLL_MS = 300` (`control_panel.py`); `poll_hz = 30` (`NfbSession.run_forever`).

## 4. Real Aurora metadata schema and its interpretation by `StreamMap`

Confirmed by a field diagnostic and in the Aurora fNIRS manual 2025.2.5, section 8.1.1 (per `CLAUDE.md`): 97 channels = 8 sources, 15 detectors, 24 pairs (16 long + 8 short); columns in the order `[24 raw 760 nm] + [24 raw 850 nm] + [24 HbO] + [24 HbR] + [1 frame/timestamp]`. Aurora delivers HbO/HbR already computed (µmol/L); the pipeline does not reprocess them.

| Metadata field (per channel) | Real value | Interpretation in `StreamMap` |
|---|---|---|
| `type` | `nirs_hbo` / `nirs_hbr` / `nirs_raw` / `nirs_frame` | translated to `HbO` / `HbR` / `raw`(`760`/`850`) / `timestamp` |
| `wavelength` | `760.0` / `850.0` (only in `nirs_raw`) | decides `raw760` vs `raw850` |
| `custom_name` | `S{n}-D{n}` | regex `S(\d+)-D(\d+)` → `source="S{n}"`, `detector="D{n}"` |
| `label` | `{src}-{det}:{idx}` | fallback (regex `(\d+)-(\d+):\d+`) when `custom_name` is absent |
| `source`, `detector` | empty | if empty, filled from `custom_name`/`label` |
| `short_channel` | `"true"` / `"false"` | `short=True` if `"true"` |
| `unit` | `umol/L` etc. | stored in `unit`, not used in the computation |

ROI selection: `pfc_hbo_columns(pairs)` looks, for each `(S, D)` pair, for **exactly one** `HbO` column; if any pair is not found, it raises `RuntimeError("canais PFC ausentes na metadata: ...")`. Time column: `timestamp_column()` returns the first `nirs_frame` column.

**TBC:** `Acquisition.pull` uses the value of the `nirs_frame` column as `device_ts`, and the pipeline measures `baseline_s` and `window_s` on that axis. The code assumes this value is in seconds. If in the real Aurora this column is a frame counter (not seconds), the windows would be in sample units. The synthetic mock writes seconds. Verify with a real session (`device_time` in the CSV should grow ≈ 1 per second).

Raw `StreamMap` output used in the session meta: `stream_name`, `stream_sfreq`, `n_stream_channels`, `pfc_pairs`, `pfc_hbo_columns`, `pfc_labels`.

## 5. Session state machine

There are two levels: the **phase** (`NfbSession.phase`, published through IPC and shown in the panel) and the **pipeline state** (`FeaturePipeline.state`, written to the `state` column of the CSV).

```
  idle --SYNC (all checks OK)--> synced --PLAY--> baseline --START_NFB--> regulation
    ^         |                                      |                         |
    +--SYNC (fail) returns/stays idle                +----------STOP-----------+--> stopped
```

- `SYNC`: verifies (1) a `Markers` stream resolved within 2 s; (2) the Data Out stream resolved within 3 s and with a sample within 3 s; (3) ROI channels present in the metadata, with a simple quality check (`|value| < 200 µmol/L` and not NaN, on a single sample). If all OK → `synced`; otherwise → `idle`.
- `PLAY` (only in `synced`): creates `Acquisition`, `FeaturePipeline(manual_gate=True)`, `Logger`, starts the `SignalWorker`, emits marker `1` and enters `baseline`.
- `START_NFB` (only in `baseline`): calls `pipeline.begin_regulation()`, changes the phase to `regulation` and emits marker `2`.
- `STOP` (any phase): emits marker `3`, stops the worker, closes acquisition and log, produces the summary and goes to `stopped`.
- Esc in the PsychoPy window also performs the stop.

Pipeline state: `baseline` → (after `BASELINE_S` of data) `baseline_ready` → (after `begin_regulation`) `running` ↔ `failsafe`. **`baseline_ready` is not a phase** of `NfbSession`; it appears only in the CSV, the snapshot and the published `state`.

**Role of the manual gate:** with `manual_gate=True`, when the baseline completes the pipeline does **not** advance by itself; it stays in `baseline_ready` (the trail remains still) until `begin_regulation()`. In the standalone runner (`run_neurofeedback.py`) the gate is off (`manual_gate=False`) and the pipeline goes straight to `running`.

**Attention (see limitations):** the "Iniciar NFB" button is enabled throughout the `baseline` phase, not only in `baseline_ready`; `_do_start_nfb` switches the phase to `regulation` and emits marker `2` even if the pipeline is still collecting the baseline (in that case `begin_regulation()` has no effect).

### 5.1 Failsafe

In `update_display`, if there has been no valid sample for longer than `FAILSAFE_TIMEOUT_S` (wall clock) and the pipeline is not in `baseline`/`baseline_ready`, the state becomes `failsafe`: smoothing stops (`smoothed` is frozen) and the altitude "glides" toward the frozen value (`GLIDE_TAU_S`). The trail keeps the last valid position and shows the warning "SINAL PERDIDO - mantendo posicao". When samples return, `add_sample` returns the state to `running`. The panel shows a persistent banner if the failsafe was triggered in the session. During the baseline there is no failsafe: if the signal stops, the baseline simply stops advancing.

## 6. How to run

Always use the Python embedded in PsychoPy (where `pylsl`, PsychoPy, PIL, numpy are installed), not the system Python. Below, `PSY` = `"C:\Program Files\PsychoPy\python.exe"` (default install path; adjust if different). From the project folder:

```
# Production application (two terminals/processes)
PSY nfb_process.py          # Process B: neurofeedback window (resets the run/ folder on start)
PSY control_panel.py        # Process A: control panel

# Synthetic mock (real schema), no hardware
PSY mock_aurora_lsl_synthetic.py --speed 1 [--stop-after 20] [--no-markers]

# Old mock (needs replay_hb.npz; generate with nirs_to_hb.py if absent)
PSY nirs_to_hb.py
PSY mock_aurora_lsl.py --speed 1 [--loop] [--stop-after N] [--no-markers]

# Standalone runner (no panel)
PSY run_neurofeedback.py --duration 90 [--no-display] [--stream NAME] [--prefix PREFIX]
```

Order for a real session: start `nfb_process.py` first (it zeroes `run/`), then `control_panel.py`; Aurora with the Data Out stream active → Configurações tab: "Detectar canais", check the ROI, fill in ID/session, "Salvar configuracao" → Principal tab: Sincronizar (3 indicators OK) → PLAY → wait for the end of the baseline → Iniciar NFB (confirm) → STOP. Operational checklist for connecting to the equipment: TBC (kept outside the code, per `CLAUDE.md`).

For mock + application: run `mock_aurora_lsl_synthetic.py` and then `nfb_process.py`/`control_panel.py`; use `--no-markers` on the mock so as not to create a second `Trigger` stream (see Troubleshooting).

## 7. Tests

All use the PsychoPy Python (`PSY test_name.py`) and return exit code 0/1 with `[OK]`/`[FALHA]` lines. Tests that start their own mock do so as a subprocess. **Do not run two tests (or a test and a manual mock) at the same time.**

| Test | Mock used | Coverage | Status |
|---|---|---|---|
| `test_session_state_machine.py` | `mock_aurora_lsl_synthetic.py` | CONFIGURE via IPC with the real `PFC_CHANNELS` → SYNC → PLAY (baseline) → baseline_ready without automatic advance → still screen → START_NFB → regulation/running → STOP, summary, log with `baseline_ready` and `running`, meta with participant/session/ROI (9/9 per `CLAUDE.md`) | valid for the real montage |
| `test_real_schema.py` | own synthetic metadata (own stream, 97 channels) | `StreamMap` (24 HbO/HbR pairs, `raw760` vs `raw850` via `wavelength`, `nirs_frame` → timestamp, 8 short, fallback via `label`), `Acquisition` with an arbitrary ROI, panel detection worker, SYNC with empty ROI, `Trigger` publication (19/19 per `CLAUDE.md`) | valid; does not depend on `PFC_CHANNELS` |
| `test_acceptance.py` | `mock_aurora_lsl.py` (whole-head `.nirs`, old schema) | ROI mapping from metadata, baseline, continuous and jump-free progress, failsafe when the mock stops, glide without drop, no retreat, consistent log, device timestamps, mock markers | **fails against the real montage due to dataset incompatibility — expected** |
| `test_live_connection.py` | `mock_aurora_lsl.py` | absent stream → clean `RuntimeError`; present stream with `REPLAY_MODE=False` → connects and maps the default ROI | **fails against the real montage due to dataset incompatibility — expected** |

The last two use `cfg.PFC_CHANNELS` (format `S{n}-D{n}`) against the old mock (anatomical labels, e.g. AF4/AF8 absent from the whole-head `.nirs`), so `RuntimeError: canais PFC ausentes na metadata` is expected. Today they serve only the generic engineering; they do not validate the experiment montage. The results above were recorded in `CLAUDE.md` and **were not re-run** for this documentation.

There is no automatic test for: `trail_display.py` (visual validated manually), `nf_logger.py` in isolation, `mock_aurora_lsl.py` in isolation, nor the behavior of `START_NFB` before `baseline_ready`.

## 8. Troubleshooting

| Symptom | Known cause | What to do |
|---|---|---|
| Incomplete baseline, frozen trail, failsafe does not trigger; strange readings | **Two mocks (or a mock + another publisher) with the same stream name `Aurora`**: they compete and corrupt the reading | Terminate all old mock processes before starting a new one; do not run `test_*.py` with their own mock in parallel with another mock |
| SYNC finds the wrong `Trigger` stream / two `Trigger` | Mocks publish `Trigger` by default and `nfb_process.py` also publishes `Trigger` | Start the mock with `--no-markers` when using the production application. `resolve_byprop("type","Markers")` takes the first one it finds |
| `ModuleNotFoundError: pylsl/psychopy` or different behavior between machines | Ran with the system Python (or the MNE installer's) instead of the PsychoPy Python | Use `C:\Program Files\PsychoPy\python.exe`; reinstall `pylsl`/`mne`/`mne-nirs`/`pygame` in the PsychoPy embedded Python when changing machine/version and re-run the tests |
| `PermissionError` / `WinError 5` when writing to `run/` | OneDrive holds a momentary lock on the file | Already mitigated: `_atomic_write` retries up to 6 times. If it persists, move the project out of the synced folder |
| After "Detectar canais" the ROI became smaller or empty; SYNC shows "N/8 canais" or "nenhum canal selecionado" | Detection replaces the list with the HbO channels of the stream found; only pairs that match `PFC_CHANNELS` are pre-checked. If the detected stream was the wrong one (e.g. old mock with anatomical labels), no/few pairs match | Check the stream name and which publisher is active, run "Detectar canais" again, re-check the ROI and "Salvar configuracao" |
| Changes to the ROI/ID have no effect | The configuration only reaches process B when "Salvar configuracao" is clicked (`CONFIGURE`); otherwise the defaults apply | Save the configuration before Sincronizar |
| SYNC: "stream resolvido mas sem amostras em 3s" | The stream exists but does not emit (in Aurora, acquisition/recording (Record) not active — reported in the field) | Start Record in Aurora and sync again |
| SYNC: "stream 'Aurora' nao encontrado em 3s" | Different name, Aurora without LSL Data Out, or mock not started | Check the name on the Aurora LSL Stream Names screen and the panel field |
| Panel restarted and buttons have no effect | The panel command counter restarts at 1; `nfb_process.py` ignores ids ≤ the last processed | Restart both processes together (starting with `nfb_process.py`) |
| PNG without transparency (checkerboard on sprite/background) | Image generators sometimes paint a fake checkerboard into the pixels | Actually remove the background (e.g. `rembg`) before using |

## 9. System latency and throughput

Source labels: **[Aurora]** reported by Aurora (stream metadata or manual); **[code]** derived from code/config, with the computation shown; **[measured]** measured in this task, on the development machine (not the lab one); **[TBC]** no data, no estimate.

**Machine for the measurements [measured]:** development PC, Windows 10 Pro (10.0.19045), CPU AMD64 Family 23 (16 logical processors), Python 3.8.10 from PsychoPy 2022.13, `pylsl` 1.15.0 / liblsl 1.15.0, against `mock_aurora_lsl_synthetic.py` in loopback (same machine), without Aurora hardware and without a PsychoPy window. The results do **not** transfer to the lab machine or to PsychoPy 2026.1.3 without new measurement.

### Information reported by Aurora

| Item | Value | Source | Note |
|---|---|---|---|
| Nominal rate | ≈ 10.17 Hz | [Aurora] | Reported from metadata captured in the field. In the repository it appears as `SFREQ = 10.17` in `mock_aurora_lsl_synthetic.py` (comment: "documented cadence") and as ≈ 10.2 Hz in `CLAUDE.md`. The exact value is read from `info.nominal_srate()` each session and written to `stream_sfreq` in the `*_meta.json` |
| `steps_per_frame` | 8 | [Aurora] | Reported by the researcher (field metadata). Not present in any file in the folder and not used by the code. Exact meaning: [TBC] |
| Number of stream columns | 97 | [Aurora] | 1 frame + 24 channels × (raw760, raw850, HbO, HbR) = 1 + 96. Corroborated by `test_real_schema.py` and by the synthetic mock (`N_OUT = 4×24+1`) |
| Data format | float32 | [Aurora] | Reported by the researcher; the mocks publish `double64`. Not verified in the code |
| Hardware, Aurora version, `ntrigger_inputs` | — | [TBC] | Values not available in the folder |
| Trigger fallback | 12 | [Aurora] | Reported in `CLAUDE.md` (Aurora LSL Stream Names screen) |
| Stream output latency | — | [TBC] | The Aurora PDF manual and the script `diagnostico_metadata.py` are not in the folder; no internal Aurora latency was inferred |

### Throughput

| Quantity | Value | Source | Computation / note |
|---|---|---|---|
| Sampling period | 98.3 ms | [code] | 1 / 10.17 Hz |
| Stream samples/s | 10.17 | [Aurora] | nominal rate |
| Values/s of the full stream | ≈ 986 | [code] | 97 columns × 10.17 |
| Values/s used by the pipeline | ≈ 81 | [code] | 8 ROI HbO columns × 10.17. The full sample (97 values) is received and converted to an array; only the ROI columns enter `add_sample` |
| New samples per screen frame | ≈ 0.17 | [code] | 10.17 / 60 fps, i.e. one new sample every ≈ 5.9 frames |
| Log rows per second (`nfb_process.py`) | ≈ 30 (target) | [code] | one row per `tick`; loop with `poll_hz = 30`. In one mock log (123 rows in ≈ 3.6 s) ≈ 34 rows/s were observed [measured in existing logs]; rate in a lab session: [TBC] |
| Log rows per second (`run_neurofeedback.py`) | ≈ frame rate (≈ 60) | [code] | one row per iteration; without display, `fps = 60` |
| `drain` limit per cycle | 64 samples | [code] | `SignalWorker`: `drain(max_samples=64, timeout=0.05)`; far above 10.17 samples/s |
| Inlet buffer | 60 s | [code] | `StreamInlet(max_buflen=60)` |
| Main loop rate (`nfb_process.py`) | 30 Hz | [code] | `run_forever(poll_hz=30)`; PsychoPy `flip` may limit it to the monitor rate; actual rate: [TBC] |
| Panel polling | 300 ms | [code] | `POLL_MS = 300` (reading `nfb_state.json`) |

### Latency budget per stage (from sample arrival to pixel)

| Stage | Value | Source | Note |
|---|---|---|---|
| Aurora sampling period | 98.3 ms | [code] | 1 / 10.17 Hz; an event only appears in the next sample (0–98 ms, mean ≈ 49 ms). Whether each sample is an average over the interval: [TBC] |
| Aurora internal latency (acquisition → LSL output) | — | [TBC] | no data |
| LSL transport (mock in loopback) | mean 1.15 ms; SD 0.47 ms; p95 1.80 ms; max 5.60 ms (n = 306) | [measured] | `local_clock()` at reception − LSL timestamp of the sample. The timestamp is the instant scheduled by the mock, so it includes the mock's scheduling jitter. It does **not** represent the lab environment or the real Aurora (real transport: [TBC]) |
| Processing per sample | `add_sample`: mean 0.054 ms (p95 0.059; max 0.161). `update_display` + `snapshot`: mean 0.011 ms (max 0.085). `Logger.write`: mean 0.040 ms (max 0.193) | [measured] | n = 306 samples in 30 s; log written to a local temporary folder, not the project folder (OneDrive). Cost of IPC (`write_state`, ≈ 30×/s, in a OneDrive folder) and of PsychoPy drawing: [TBC] |
| Collection by `SignalWorker` | ≈ immediate after arrival | [code] | `pull_sample(timeout=0.05)` blocks and returns as soon as a sample is available; the timeout only limits the wait with no data (it is not blind 50 ms polling). Delay included in the transport row |
| Main loop reads the state | 0–33 ms (mean ≈ 17 ms) | [code] | `poll_hz = 30`: the `tick` uses the pipeline state in the next iteration |
| Sliding window (simple mean) | group delay ≈ 1.97 s (≈ `FEATURE_WINDOW_S`/2) | [code] | `np.mean` over the samples with `t − t_oldest ≤ 4.0 s`: N = ⌊4.0 × 10.17⌋ + 1 = 41 samples. A simple mean (boxcar) has group delay (N−1)/2 = 20 samples = 20 / 10.17 ≈ 1.97 s. Step response: ramp from 0 to 100% in 4.0 s (50% at ≈ 2.0 s) |
| Exponential smoothing (`SMOOTH_TAU_S` = 1.5 s) | 63% at 1.5 s; 95% at ≈ 4.5 s (3τ) | [code] | 1 − e^(−t/τ); low-frequency group delay ≈ τ = 1.5 s. Updated at each `tick` with real `dt` (rate-independent) |
| Progress smoothing in `trail_display` (`SMOOTHING_SPEED` = 1.2) | τ ≈ 0.83 s: 63% at ≈ 0.83 s; 95% at ≈ 2.5 s | [code] | `progress += (target − progress) × min(1, 1.2 × dt)` → τ ≈ 1 / 1.2 s⁻¹ (approximation valid for 1.2·dt ≪ 1) |
| Frame period / `flip` | ≈ 16.7 ms at 60 Hz | [code] | `win.flip()` in `TrailDisplay.draw`. ≈ 59.3 fps was recorded in an earlier test (`CLAUDE.md`); monitor/OS latency: [TBC] |
| Failsafe timeout (`FAILSAFE_TIMEOUT_S`) | 1.0 s (+ up to 33 ms of the loop) | [code] | ≈ 10 sampling periods without a valid sample (wall clock) |
| Hemodynamic response | — | [TBC] | Physiological delay of the order of seconds, outside the system's control: [REF: hemodynamic response latency] |

**Estimate of the deterministic pipeline delay (sample arrival to pixel), [code]/[measured] items only:** the three cascaded filters add group delays (approximation for slow signals): 1.97 s (window) + 1.5 s (EMA) + ≈ 0.83 s (trail progress) ≈ **4.3 s**, plus a fixed term ≤ ≈ 0.05 s (≈ 1 ms of transport/collection [measured], up to 33 ms of the loop and up to 17 ms of frame). It is a group delay (centroid of the impulse response), not the time to reflect 100% of a change: the window takes 4.0 s to fully reflect a step and the EMA and the drawing smoothing have an exponential tail. The z-score and the clipping (±`NORM_CLIP`) add no delay, but the clipping truncates excursions.

**Left out of the estimate:** internal latency of Aurora and of the hardware, LSL transport in the real environment, quantization by the sampling period (0–98 ms), cost of PsychoPy drawing and of IPC, monitor latency, and the hemodynamic response ([REF: hemodynamic response latency]).

### Auxiliary measurement on existing logs (aggregated)

[measured, logs in `logs/`, aggregate statistics only] In the 6 mock logs at 1× speed (≈ 15.4 thousand rows), the difference `lsl_time − device_time` is an offset between two arbitrary clocks (LSL clock × device time), not a latency; what matters is its stability. Around the mean of each log: aggregate SD = 0.84 s and maximum deviation = 16.7 s; the range (max−min) per log has median 0.000 s and maximum 32.0 s. The high values come from a few logs in which the offset changes mid-run (cause: TBC; hypothesis: `--loop` or restart of the mock); in the others the offset is constant. The 13 logs at 10× speed were excluded, because device time and the LSL clock advance at different rates. Measurement with the real Aurora: [TBC].

## 10. Known limitations

1. **Incomplete manual gate:** "Iniciar NFB" is enabled throughout the `baseline` phase. If triggered before `baseline_ready`, the phase goes to `regulation` and marker `2` is emitted, but the pipeline remains in baseline; when it finishes it stays in `baseline_ready` without the button being enabled again (the confirmation dialog is the only safeguard). Deduced from the code; not reproduced at this stage.
2. **Device time axis:** `nirs_frame` is treated as seconds (TBC with the real Aurora, section 4).
3. **Simplified signal quality:** `|value| < 200 µmol/L` and not NaN, evaluated on a single sample during SYNC; no SNR, no continuous monitoring, no native Aurora indicator (check whether it exists in the metadata before collection).
4. **Uncalibrated parameters:** window, smoothing, `NORM_CLIP` (saturation observed), baseline duration.
5. **ROI by geometry:** cluster S1–S4 not anatomically confirmed; final selection is manual.
6. **Short channels:** not used in the feature, and no systemic-signal correction is implemented.
7. **Double smoothing:** EMA in the pipeline (`SMOOTH_TAU_S`) and progress smoothing in `trail_display.py` (`SMOOTHING_SPEED`).
8. **Duplicate markers/collision:** mocks use `Trigger` with value `1` (same code as the baseline start); with a mock and `nfb_process.py` active there are two `Trigger` streams.
9. **Unconsumed marker queue:** in `nfb_process.py`, the `SignalWorker` accumulates `pending_markers` from an external stream that is never read (list growth; irrelevant for short sessions).
10. **Validation:** only engineering tests with mock/synthetic data, plus the first test sessions on the equipment; no evaluation of neurofeedback performance.
11. **Divergent test dataset:** `test_acceptance.py` and `test_live_connection.py` fail against the real montage (section 7).
12. **Project copies:** divergent versions existed between the personal PC and the lab PC; the rule is to edit only on the personal PC and copy the folder to the lab PC.
13. **Platform:** interface and tests validated on Windows; `.bat` paths are fixed.
14. **Language:** the interface (tkinter/PsychoPy), messages and code comments are in Portuguese without accents.
15. **Assets:** `trail_bg.png` is ≈ 6.2 MB.
16. **Latency:** no measurement with the real Aurora (section 9). The mocks publish `double64`; the real Aurora, as reported, `float32`.
