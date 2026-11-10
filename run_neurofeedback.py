"""Runner das Camadas 2-5 contra o stream mockado (REPLAY_MODE)."""

import argparse
import threading
import time

from pylsl import local_clock, resolve_byprop, StreamInlet

import nf_config as cfg
from acquisition import Acquisition
from nf_logger import Logger
from processing import FeaturePipeline


class SignalWorker(threading.Thread):
    """Camadas 2+3 em thread propria; a visualizacao le o estado compartilhado."""

    def __init__(self, acq, pipeline, marker_inlet=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.acq = acq
        self.pipeline = pipeline
        self.marker_inlet = marker_inlet
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.last_lsl_ts = None
        self.last_device_ts = None
        self.pending_markers = []

    def run(self):
        while not self.stop_flag.is_set():
            samples = self.acq.drain(max_samples=64, timeout=0.05)
            if samples:
                wall = local_clock()
                with self.lock:
                    for lsl_ts, dev_ts, pfc in samples:
                        self.pipeline.add_sample(dev_ts, pfc)
                        self.last_lsl_ts, self.last_device_ts = lsl_ts, dev_ts
                    self.pipeline.mark_sample_received(wall)
            if self.marker_inlet is not None:
                try:
                    while True:
                        m, ts = self.marker_inlet.pull_sample(timeout=0.0)
                        if m is None:
                            break
                        with self.lock:
                            self.pending_markers.append((ts, int(m[0])))
                except Exception:
                    # stream de markers perdido: segue sem markers, sem derrubar
                    # a thread de sinal (o failsafe cuida do feedback)
                    self.marker_inlet = None

    def take_markers(self):
        with self.lock:
            out, self.pending_markers = self.pending_markers, []
        return out

    def stop(self):
        self.stop_flag.set()


def run(duration=None, display=True, stream_name=None, log_prefix="replay",
        fps=60.0, quiet=False):
    acq = Acquisition(stream_name=stream_name)
    pipeline = FeaturePipeline()

    marker_inlet = None
    found = resolve_byprop("type", "Markers", 1, 1.0)
    if found:
        marker_inlet = StreamInlet(found[0], recover=False)

    meta = dict(
        replay_mode=cfg.REPLAY_MODE,
        stream_name=acq.map.name,
        stream_sfreq=acq.map.sfreq,
        n_stream_channels=acq.map.n_channels,
        pfc_pairs=[list(p) for p in cfg.PFC_CHANNELS],
        pfc_hbo_columns=acq.pfc_cols,
        pfc_labels=[acq.map.channels[i]["label"] for i in acq.pfc_cols],
        short_hbo_columns=acq.short_cols,
        timestamp_column=acq.ts_col,
        params=dict(baseline_s=cfg.BASELINE_S, window_s=cfg.FEATURE_WINDOW_S,
                    smooth_tau_s=cfg.SMOOTH_TAU_S, clip=cfg.NORM_CLIP,
                    failsafe_timeout_s=cfg.FAILSAFE_TIMEOUT_S,
                    glide_tau_s=cfg.GLIDE_TAU_S, dpf=cfg.DPF,
                    extinction=cfg.EXTINCTION,
                    altitude_range=list(cfg.ALTITUDE_RANGE)),
        source_file=cfg.NIRS_FILE,
        started=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    log = Logger(prefix=log_prefix, meta=meta)
    if not quiet:
        print("[run] canais PFC mapeados: %s" % meta["pfc_labels"])
        print("[run] log: %s" % log.csv_path)

    disp = None
    if display:
        from trail_display import TrailDisplay
        disp = TrailDisplay()

    worker = SignalWorker(acq, pipeline, marker_inlet)
    worker.start()

    t0 = local_clock()
    prev = t0
    frame_dt = 1.0 / fps
    try:
        while True:
            now = local_clock()
            dt = now - prev
            prev = now
            with worker.lock:
                altitude = pipeline.update_display(now)
                snap = pipeline.snapshot()
                lsl_ts, dev_ts = worker.last_lsl_ts, worker.last_device_ts
            markers = worker.take_markers()
            valid = snap["state"] != "failsafe"
            log.write(lsl_ts, dev_ts, snap, valid, acq.n_valid, acq.n_invalid,
                      marker=";".join(str(m[1]) for m in markers))
            if disp is not None:
                disp.draw(altitude, snap, dt)
                if disp.should_quit():
                    break
            else:
                time.sleep(max(0.0, frame_dt - (local_clock() - now)))
            if duration is not None and (now - t0) >= duration:
                break
    finally:
        worker.stop()
        worker.join(timeout=1.0)
        acq.close()
        log.close()
        if disp is not None:
            disp.close()

    summary = dict(rows=log.n_rows, csv=log.csv_path, meta=log.meta_path,
                   n_valid=acq.n_valid, n_invalid=acq.n_invalid,
                   final_state=pipeline.state)
    if not quiet:
        print("[run] %d linhas, %d amostras validas, estado final=%s"
              % (summary["rows"], summary["n_valid"], summary["final_state"]))
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--no-display", action="store_true")
    p.add_argument("--stream", default=None)
    p.add_argument("--prefix", default="replay")
    a = p.parse_args()
    run(duration=a.duration, display=not a.no_display, stream_name=a.stream,
        log_prefix=a.prefix)
