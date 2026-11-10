"""Camada 3: feature = HbO medio dos canais PFC, normalizado pelo baseline."""

import math
from collections import deque

import numpy as np

import nf_config as cfg


class FeaturePipeline(object):
    """Janela deslizante -> z-score do baseline -> suavizacao -> altitude.

    Estados: 'baseline' (coletando repouso), 'baseline_ready' (repouso
    concluido, aguardando confirmacao manual - so existe se manual_gate=True),
    'running', 'failsafe'.
    """

    def __init__(self, baseline_s=None, window_s=None, smooth_tau_s=None,
                 clip=None, failsafe_timeout_s=None, glide_tau_s=None,
                 manual_gate=False):
        self.baseline_s = cfg.BASELINE_S if baseline_s is None else baseline_s
        self.window_s = cfg.FEATURE_WINDOW_S if window_s is None else window_s
        self.smooth_tau = cfg.SMOOTH_TAU_S if smooth_tau_s is None else smooth_tau_s
        self.clip = cfg.NORM_CLIP if clip is None else clip
        self.failsafe_timeout = (cfg.FAILSAFE_TIMEOUT_S if failsafe_timeout_s
                                 is None else failsafe_timeout_s)
        self.glide_tau = cfg.GLIDE_TAU_S if glide_tau_s is None else glide_tau_s
        self.manual_gate = manual_gate

        self.window = deque()          # (t, hbo_mean)
        self.baseline_vals = []
        self.baseline_mean = None
        self.baseline_std = None
        self.t_start = None
        self.t_last_sample = None
        self.t_wall_of_last_sample = None  # relogio de parede da ultima amostra
        self.state = "baseline"

        self.raw_feature = float("nan")   # media dos canais PFC, umol/L
        self.windowed = float("nan")      # media na janela deslizante
        self.normalized = 0.0             # z-score saturado
        self.smoothed = 0.0               # apos EMA
        self.altitude = self._to_altitude(0.0)
        self._last_display_update = None

    # ------------------------------------------------------------- helpers
    def _to_altitude(self, z):
        lo, hi = cfg.ALTITUDE_RANGE
        frac = (max(-self.clip, min(self.clip, z)) + self.clip) / (2.0 * self.clip)
        return lo + frac * (hi - lo)

    @staticmethod
    def _ema(prev, target, dt, tau):
        if tau <= 0 or dt <= 0:
            return target
        a = 1.0 - math.exp(-dt / tau)
        return prev + a * (target - prev)

    # ------------------------------------------------------------ interface
    def add_sample(self, t, pfc_hbo):
        """Adiciona uma amostra valida (t em segundos, vetor HbO dos canais PFC)."""
        val = float(np.mean(pfc_hbo))
        if not np.isfinite(val):
            return
        if self.t_start is None:
            self.t_start = t
        self.t_last_sample = t
        self.raw_feature = val

        self.window.append((t, val))
        while self.window and (t - self.window[0][0]) > self.window_s:
            self.window.popleft()
        self.windowed = float(np.mean([v for _, v in self.window]))

        if self.state == "baseline":
            self.baseline_vals.append(val)
            if (t - self.t_start) >= self.baseline_s:
                arr = np.asarray(self.baseline_vals, dtype=float)
                self.baseline_mean = float(arr.mean())
                sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
                self.baseline_std = sd if sd > 1e-9 else 1e-9
                self.state = "baseline_ready" if self.manual_gate else "running"
            return

        if self.state == "baseline_ready":
            return  # aguardando begin_regulation(); tela nao avanca sozinha

        z = (self.windowed - self.baseline_mean) / self.baseline_std
        self.normalized = max(-self.clip, min(self.clip, z))
        self.state = "running"

    def begin_regulation(self):
        """Confirmacao manual (botao 'Iniciar NFB'): baseline_ready -> running."""
        if self.state == "baseline_ready":
            self.state = "running"

    def update_display(self, now):
        """Avanca suavizacao/planeio no relogio de exibicao. Devolve altitude."""
        dt = 0.0 if self._last_display_update is None else now - self._last_display_update
        self._last_display_update = now

        pre_regulation = self.state in ("baseline", "baseline_ready")
        stale = (self.t_wall_of_last_sample is None or
                 (now - self.t_wall_of_last_sample) > self.failsafe_timeout)
        if stale and not pre_regulation:
            self.state = "failsafe"
            # planeio: mantem a ultima altitude valida, sem queda
            self.altitude = self._ema(self.altitude,
                                      self._to_altitude(self.smoothed),
                                      dt, self.glide_tau)
            return self.altitude

        if pre_regulation:
            target = 0.0
        else:
            target = self.normalized
        self.smoothed = self._ema(self.smoothed, target, dt, self.smooth_tau)
        self.altitude = self._to_altitude(self.smoothed)
        return self.altitude

    def mark_sample_received(self, wall_time):
        self.t_wall_of_last_sample = wall_time

    def snapshot(self):
        return dict(state=self.state, raw_feature=self.raw_feature,
                    windowed=self.windowed, normalized=self.normalized,
                    smoothed=self.smoothed, altitude=self.altitude,
                    baseline_mean=self.baseline_mean,
                    baseline_std=self.baseline_std,
                    n_window=len(self.window))
