---
title: "Real-time fNIRS neurofeedback system — Methodology"
lang: en
---

# Real-time fNIRS neurofeedback system — Methodology

Research tool for real-time fNIRS neurofeedback (NIRSport2 + Aurora), with PsychoPy presentation.

This text describes the system as a reproducible protocol, in the style of a Methods section. Whatever the code does not allow to be stated is marked "TBC (to be confirmed)". Bibliographic references are not included: where a citation would belong, `[REF: topic]` appears.

Portuguese original: [pt-BR/METODOLOGIA.md](pt-BR/METODOLOGIA.md).

## 1. Equipment and software

**Acquisition.** Continuous-wave fNIRS system NIRSport2 (NIRx) operated with the Aurora fNIRS software (version of the manual consulted: 2025.2.5). Stream sampling rate: ≈ 10.2 Hz (value documented for Aurora; the exact value is read from the stream metadata in each session and written to the metadata file). Wavelengths: 760 and 850 nm. Aurora provides the data in real time through Lab Streaming Layer (LSL) on the "Data Out" stream (configured name: `Aurora`) and receives markers on the "Trigger In" stream (name: `Trigger`) `[REF: LSL]`.

**Software.** Python embedded in the PsychoPy Standalone distribution (validated versions: PsychoPy 2022.13 with Python 3.8.10 and PsychoPy 2026.1.3 with Python 3.10.11), `pylsl` (liblsl 1.15.0 and 1.17.4 in the two environments), `numpy`, `Pillow`, `tkinter` (control panel). The visual presentation uses PsychoPy `[REF: PsychoPy]`. The system consists of two processes (control panel and neurofeedback window) that communicate through a local JSON file; the source code and the technical documentation accompany this text (`TECHNICAL_DOCUMENTATION.md`).

The modular architecture (separation between acquisition, processing and visualization) was inspired by a reference EEG neurofeedback system; no EEG processing code or methods were reused `[REF: EEG neurofeedback]`.

## 2. Montage and ROI selection

The montage recorded in the Aurora metadata has 8 sources, 15 detectors and 24 source-detector pairs (16 long-distance channels and 8 short-distance ones). Optode positions were defined in Aurora/NIRSite (10-20 anatomical positions of the experiment: TBC against the cap drawing).

The feedback ROI is a set of source-detector pairs **selected manually in the control panel**, by checkboxes, after detection of the HbO channels present in the stream. The default pre-selection (`PFC_CHANNELS`) contains 8 long channels of the bilateral frontal cluster: S1-D1, S1-D2, S2-D1, S2-D2, S3-D3, S3-D4, S4-D3, S4-D4. **The frontal cluster S1–S4 was chosen from the geometry of the optode coordinates (sources S1–S4 with the most anterior position; S5–S8 more posterior) and was not anatomically confirmed** against the original cap drawing; the correspondence with the 10-20 labels (AF7, AF3, AF4, AF8 for the sources and Fp1, F5, Fp2, F6 for the detectors, per the project planning) remains TBC. The bilateral PFC is treated as a single region (channel mean; no lateralization). Short-distance channels do not enter the feedback feature, and no systemic-signal regression is implemented in the pipeline.

## 3. Signal acquisition

The oxygenated hemoglobin concentration (HbO, µmol/L) is the one supplied by Aurora in the data stream, computed by the software itself from optical density using the modified Beer-Lambert law and fixed Aurora coefficients (not configurable) `[REF: modified Beer-Lambert]`. **The pipeline does not reprocess the optical signal**: there is no conversion, band-pass filtering, motion-artifact correction or short-channel correction in the real-time code. The HbO columns are located dynamically from the stream metadata (type `nirs_hbo` and name `S{n}-D{n}`), never by fixed index. Samples with a non-finite value (NaN/Inf) in any ROI channel are discarded and counted, and never replace the last valid sample.

## 4. Feature computation

Let *x(t)* be the mean HbO of the ROI channels (per sample). The computation is, in order:

1. **Sliding window:** mean of *x* over the samples of the last `FEATURE_WINDOW_S` = 4.0 s (device time, frame/timestamp column of the stream; unit TBC, see section 9) → *w(t)*.
2. **Baseline:** during the first `BASELINE_S` = 30.0 s of data from the first sample, the *x* values are accumulated; at the end the baseline mean *μ* and sample standard deviation *σ* (ddof = 1; floor of 10⁻⁹) are computed. The pipeline then waits for manual confirmation of the advance (section 7); during this wait and during the baseline the feedback output is held at z = 0.
3. **Normalization (z-score):** *z(t) = (w(t) − μ) / σ*. Note: *σ* is the standard deviation of the per-sample baseline values, whereas *w* is a windowed mean; therefore *z* is not a z-score of a variable with the same variance.
4. **Clipping:** *z* is limited to [−`NORM_CLIP`, +`NORM_CLIP`] = [−3, +3].
5. **Smoothing:** exponential moving average with time constant `SMOOTH_TAU_S` = 1.5 s, applied on the display clock (not per sample): *s ← s + (1 − e^(−Δt/τ))·(z − s)*.

The resulting value is converted internally to an "altitude" in the range (−0.75, 0.75) (name inherited from a previous visual metaphor), by linear mapping of *s* ∈ [−3, 3].

## 5. Mapping the feature to visual feedback

The neurofeedback window shows an explorer (sprite) on a mountain trail (fixed background image). The altitude is linearly rescaled to a **progress *p* ∈ [0, 1]** — *p = (s + 3)/6* — so that *z* = 0 (baseline level) corresponds to *p* = 0.5 (middle of the trail), *z* ≥ +3 to the end of the trail and *z* ≤ −3 to the start. The displayed progress follows the target with a second exponential smoothing in the drawing (rate `SMOOTHING_SPEED` = 1.2 s⁻¹, i.e. τ ≈ 0.83 s). The sprite position is obtained by linear interpolation along 6 fixed waypoints, with the sprite anchored by its feet. The mapping is continuous and direct: no thresholds, no discrete reward. A text line on the screen shows state, windowed HbO, *z* and progress (for the researcher's use; the decision whether to show it to the participant is TBC). The direction of the feedback (increase in HbO → advance on the trail) is fixed in the code.

## 6. Handling of signal loss (failsafe)

If, after the baseline, no valid sample arrives for more than `FAILSAFE_TIMEOUT_S` = 1.0 s (wall clock), the state becomes "failsafe": smoothing is frozen, the trail keeps the last valid position (no retreat to the start; smooth adjustment with constant `GLIDE_TAU_S` = 2.0 s) and the screen shows the warning "SINAL PERDIDO - mantendo posicao". When valid samples return, normal operation resumes without a jump. The panel shows a persistent alert if the failsafe was triggered in the session, and the summary reports the counts of valid and invalid samples. During the baseline there is no failsafe: if the signal is interrupted, the baseline simply does not advance.

## 7. Session protocol

1. **Configuration (panel):** stream name, channel detection, ROI selection, participant ID and session number; the panel sends the configuration to the neurofeedback process.
2. **Synchronization:** the system verifies (i) the existence of a markers stream (`Trigger`, published by the neurofeedback process itself), (ii) the existence of the data stream and the reception of a sample within 3 s, and (iii) the presence of all ROI channels, with a simplified plausibility check (non-NaN value and |value| < 200 µmol/L, on a single sample per channel). The three indicators must be OK to allow the start. With Aurora, recording (Record) must be active for samples to flow.
3. **PLAY — baseline:** starts acquisition, the log and the 30 s baseline computation; marker `1` sent to the `Trigger` stream. The trail stays at the midpoint. Baseline condition (eyes open with fixation, instruction to the participant): **TBC** (it was only a recommendation, not enforced by the code).
4. **Manual advance:** when the baseline completes, the pipeline enters "baseline_ready" and the trail stays still. The researcher triggers "Iniciar NFB" and confirms the dialog; marker `2` (regulation start). In the code, the button is enabled throughout the baseline, not only after it ends; applying the correct procedure (triggering only after "baseline_ready") depends on the operator.
5. **Regulation:** the feedback evolves according to sections 4–5, with no programmed fixed duration (the block duration is defined by the operator; duration of the recovery phase of the original design: TBC, not implemented as a phase).
6. **STOP:** marker `3`, end of acquisition, log closed and summary displayed. The Esc key in the neurofeedback window also ends the session.

**Recorded data.** For each session: (a) a CSV with one row per update cycle (≈ 30 Hz), containing wall-clock timestamp (ISO and Unix), LSL time and device time of the last sample, pipeline state, ROI mean HbO, windowed mean, z-score, smoothed value, altitude, validity flag, counters of valid/invalid samples and the marker emitted in the row; (b) a metadata JSON with mode (replay/live, informative label), participant and session ID, stream name and rate, number of channels, ROI pairs and columns, channel labels and processing parameters; (c) markers `1`, `2`, `3` sent to Aurora (Trigger In), which allow the log to be reconciled with the Aurora events file (`*_lsl.tri`) through the LSL/device times (reconciliation procedure: TBC). Aurora fallback value for an invalid trigger: 12 (per the reported configuration).

## 8. Validation performed

Validation was limited to **engineering tests** with mock/synthetic data and to the **first test sessions** on the equipment:

- Replay phase (stream simulated from data of another task, with a whole-head montage): acceptance criteria 9/9 — ROI mapping from metadata, baseline, continuous progress, absence of jumps, failsafe, glide without drop, no retreat, consistent log and markers; frame rate ≈ 59 fps in the visual confirmation.
- Automated tests with a synthetic stream in the real Aurora schema (session state machine, IPC, metadata interpretation, channel detection, marker publication).
- First test sessions with the real Aurora: synchronization with the three indicators OK and sessions completed. No neurofeedback performance, learning effect or physiological validity of the feedback signal was evaluated. The synthetic data is not physiological.
- The tests `test_acceptance.py` and `test_live_connection.py` are not applicable to the real montage (incompatible dataset).

## 9. Parameters not yet calibrated and pending decisions

| Item | Current status | Pending |
|---|---|---|
| Feature window (`FEATURE_WINDOW_S`) | 4.0 s, initial value | Define in a real pilot |
| Smoothing (`SMOOTH_TAU_S`; `SMOOTHING_SPEED` in the drawing; `GLIDE_TAU_S`) | 1.5 s; 1.2 s⁻¹; 2.0 s, initial values; two-stage smoothing | Define in a real pilot; decide whether to keep two stages |
| Clipping (`NORM_CLIP`) | 3.0; z-score saturation observed in a test with slow drift | Reassess with real data before any collection |
| Baseline duration (`BASELINE_S`) | 30 s (planning foresaw 30–60 s) | TBC |
| Baseline condition | Eyes open with fixation: recommendation only | TBC |
| Signal quality | Simplified check (|value| < 200 µmol/L and non-NaN, one sample, SYNC only); no SNR | Consider a native Aurora quality indicator, if it exists in the metadata, and continuous monitoring |
| ROI | Cluster S1–S4 by geometry, manual selection | Confirm anatomically against the cap drawing |
| Time axis | `nirs_frame` column treated as seconds | Confirm with a real session (if it is a frame counter, window and baseline are in sample units) |
| Signal preprocessing | None beyond what Aurora supplies; no short-channel or motion correction | Decide whether necessary `[REF: systemic-signal / motion correction in fNIRS]` |
| Normalization | Baseline per-sample σ applied to the windowed mean | Decide whether to keep |
| Recovery phase and regulation block duration | Not implemented as phases | TBC |
| Reconciliation with `*_lsl.tri` | Possible through the recorded times and markers | Procedure TBC |
| Feedback direction and showing the state text to the participant | Fixed in the code | TBC |

## 10. System latency and throughput

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
