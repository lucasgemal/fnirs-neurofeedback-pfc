"""Camada 5: log da feature, estado e eventos, reconciliavel com o *_lsl.tri."""

import csv
import datetime
import json
import os

import nf_config as cfg

FIELDS = ["wall_iso", "wall_unix", "lsl_time", "device_time", "state",
          "raw_feature_hbo", "windowed_hbo", "normalized", "smoothed",
          "altitude", "valid", "n_valid", "n_invalid", "marker"]


class Logger(object):
    def __init__(self, prefix="replay", meta=None, log_dir=None):
        d = log_dir or cfg.LOG_DIR
        if not os.path.isdir(d):
            os.makedirs(d)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.csv_path = os.path.join(d, "%s_%s.csv" % (prefix, stamp))
        self.meta_path = os.path.join(d, "%s_%s_meta.json" % (prefix, stamp))
        self._fh = open(self.csv_path, "w", newline="")
        self._w = csv.DictWriter(self._fh, fieldnames=FIELDS)
        self._w.writeheader()
        self.n_rows = 0
        if meta is not None:
            with open(self.meta_path, "w") as fh:
                json.dump(meta, fh, indent=2, default=str)

    def write(self, lsl_time, device_time, snap, valid, n_valid, n_invalid,
              marker=""):
        now = datetime.datetime.now()
        self._w.writerow({
            "wall_iso": now.isoformat(timespec="milliseconds"),
            "wall_unix": "%.6f" % now.timestamp(),
            "lsl_time": "" if lsl_time is None else "%.6f" % lsl_time,
            "device_time": "" if device_time is None else "%.6f" % device_time,
            "state": snap["state"],
            "raw_feature_hbo": "%.6f" % snap["raw_feature"],
            "windowed_hbo": "%.6f" % snap["windowed"],
            "normalized": "%.6f" % snap["normalized"],
            "smoothed": "%.6f" % snap["smoothed"],
            "altitude": "%.6f" % snap["altitude"],
            "valid": int(bool(valid)),
            "n_valid": n_valid,
            "n_invalid": n_invalid,
            "marker": marker,
        })
        self.n_rows += 1

    def close(self):
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass
