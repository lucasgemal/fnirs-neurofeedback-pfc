# fNIRS neurofeedback (NIRx/Aurora + PsychoPy)

Research tool for real-time fNIRS neurofeedback (NIRSport2 + Aurora), with PsychoPy presentation.

The Aurora Data Out stream (LSL) is read, the mean HbO of a user-selected frontal ROI is normalized against a resting baseline, and the result drives an explorer climbing a mountain trail. Markers are sent back to Aurora on the `Trigger` stream and every session is logged to CSV + JSON.

## Documentation

| | English | Português (pt-BR) |
|---|---|---|
| Technical documentation (architecture, scripts, parameters, tests, troubleshooting, latency) | [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md) | [docs/pt-BR/DOCUMENTACAO_TECNICA.md](docs/pt-BR/DOCUMENTACAO_TECNICA.md) |
| Methodology (Methods-style protocol description) | [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | [docs/pt-BR/METODOLOGIA.md](docs/pt-BR/METODOLOGIA.md) |

## Requirements

- Windows, with the PsychoPy Standalone distribution; run all scripts with its embedded Python (e.g. `C:\Program Files\PsychoPy\python.exe`), not the system Python.
- Packages in that Python: `pylsl`, `numpy`, `Pillow`, PsychoPy. `scipy` is needed only for `nirs_to_hb.py`.
- Aurora fNIRS with LSL Data Out (stream name `Aurora`) and Trigger In (stream name `Trigger`), with recording active.

Validated environments: PsychoPy 2022.13 / Python 3.8.10 and PsychoPy 2026.1.3 / Python 3.10.11.

## Quick start

`PSY` = the PsychoPy Python executable. From the project folder:

```
PSY nfb_process.py       # process B: neurofeedback window (start first)
PSY control_panel.py     # process A: control panel (Settings -> Sync -> PLAY -> Start NFB -> STOP)
```

Without hardware, start the synthetic mock first (real Aurora metadata schema):

```
PSY mock_aurora_lsl_synthetic.py --speed 1 --no-markers
```

Tests (one at a time; each starts its own mock where needed):

```
PSY test_session_state_machine.py
PSY test_real_schema.py
```

`test_acceptance.py` and `test_live_connection.py` are expected to fail against the real montage (dataset incompatibility); see the technical documentation, section 7.

## Known limitations

See section 10 of the technical documentation. In particular: the control panel UI, console messages and code comments are in Portuguese (without accents); the ROI pre-selection (`PFC_CHANNELS`, sources S1–S4) was chosen by geometry and is not anatomically confirmed; several processing parameters are uncalibrated placeholders; no latency measurement with the real Aurora exists yet.

## Acknowledgements

The modular architecture (separate stream / processing / visualization components) was inspired by a reference EEG neurofeedback system (`Neurofeedback-with-MNE-and-PsychoPy`). No code from it is included.
