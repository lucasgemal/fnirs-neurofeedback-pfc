"""Mock alternativo de replay continuo, gerando dado sintetico diretamente no
schema REAL do Aurora (capturado em campo, ver CLAUDE.md "schema real do
Aurora corrigido") - ao contrario de mock_aurora_lsl.py, que reproduz o
'.nirs' de teste (dataset de outra tarefa, whole-head, metadata no formato
antigo com rotulos anatomicos direto em source/detector).

Metadata gerada aqui: type minusculo/prefixado ('nirs_raw'+'wavelength',
'nirs_hbo', 'nirs_hbr', 'nirs_frame'), par fonte-detector em 'custom_name'
("S{n}-D{n}") - source/detector deixados vazios de proposito, para casar com
o que o Aurora real manda (a extracao por regex de acquisition.StreamMap ja'
cobre esse caminho, validado em test_real_schema.py).

Topologia: 8 fontes / 15 detectores / 24 pares, 16 longos + 8 short-distance.
Inclui literalmente os pares de PFC_CHANNELS (cluster frontal S1-S4) e de
SHORT_CHANNELS_FRONTAL (nf_config.py) - por isso test_session_state_machine.py
pode validar fim-a-fim contra o PFC_CHANNELS real sem precisar de ROI manual.

Sem dependencia de mne/mne-nirs (nao reimplementa Beer-Lambert): HbO/HbR sao
ruido + deriva lenta por canal, plausiveis o bastante pra exercitar
mapeamento de canal / sync / failsafe / maquina de estados - nao pretende
ser fisiologicamente realista.
"""

import argparse
import math
import random
import time

from pylsl import StreamInfo, StreamOutlet, local_clock

import nf_config as cfg

SFREQ = 10.17  # mesma cadencia documentada para o Aurora real (~10.2 Hz)

# 24 pares fonte-detector: cluster frontal (S1-S4, = PFC_CHANNELS) + cluster
# posterior (S5-S8) + 8 short-distance (4 frontais = SHORT_CHANNELS_FRONTAL,
# 4 posteriores) - mesma estrutura 8 fontes/15 detectores documentada no
# CLAUDE.md a partir da metadata real.
PAIRS = [
    (1, 1, False), (1, 2, False), (2, 1, False), (2, 2, False),
    (3, 3, False), (3, 4, False), (4, 3, False), (4, 4, False),
    (5, 5, False), (5, 6, False), (6, 5, False), (6, 6, False),
    (7, 7, False), (7, 8, False), (8, 7, False), (8, 8, False),
    (1, 8, True), (2, 9, True), (3, 10, True), (4, 11, True),
    (5, 12, True), (6, 13, True), (7, 14, True), (8, 15, True),
]
N_PAIRS = len(PAIRS)
N_OUT = 4 * N_PAIRS + 1  # raw760 + raw850 + HbO + HbR + frame

RAW760_OFFSET = 0
RAW850_OFFSET = N_PAIRS
HBO_OFFSET = 2 * N_PAIRS
HBR_OFFSET = 3 * N_PAIRS
FRAME_COL = 4 * N_PAIRS

_PAIR_SET = set((s, d) for s, d, _short in PAIRS)
for _label, _pairs in (("PFC_CHANNELS", cfg.PFC_CHANNELS),
                        ("SHORT_CHANNELS_FRONTAL", cfg.SHORT_CHANNELS_FRONTAL)):
    for _src, _det in _pairs:
        _pair_num = (int(_src[1:]), int(_det[1:]))  # "S1"/"D1" -> (1, 1)
        if _pair_num not in _PAIR_SET:
            raise RuntimeError(
                "%s tem par %s-%s fora da topologia sintetica deste mock "
                "(PAIRS) - atualize as duas listas juntas" % (_label, _src, _det))


def build_stream_info(name):
    n = N_OUT
    info = StreamInfo(name, cfg.STREAM_TYPE, n, SFREQ, "double64",
                      cfg.STREAM_SOURCE_ID + "_synthetic")
    desc = info.desc()
    desc.append_child_value("manufacturer", "NIRx (mock synthetic replay)")
    desc.append_child_value("serial_number", cfg.SERIAL_NUMBER)
    desc.append_child_value("replay_mode", "true")

    channels = desc.append_child("channels")

    def add(pair_idx, kind, wavelength=None):
        src, det, short = PAIRS[pair_idx]
        c = channels.append_child("channel")
        c.append_child_value("custom_name", "S%d-D%d" % (src, det))
        c.append_child_value("label", "%s%s S%d-D%d" % (kind, wavelength or "", src, det))
        c.append_child_value("type", kind)
        if wavelength is not None:
            c.append_child_value("wavelength", str(wavelength))
        unit = "umol/L" if kind in ("nirs_hbo", "nirs_hbr") else "V"
        c.append_child_value("unit", unit)
        c.append_child_value("short_channel", "true" if short else "false")

    for pi in range(N_PAIRS):
        add(pi, "nirs_raw", 760.0)
    for pi in range(N_PAIRS):
        add(pi, "nirs_raw", 850.0)
    for pi in range(N_PAIRS):
        add(pi, "nirs_hbo")
    for pi in range(N_PAIRS):
        add(pi, "nirs_hbr")
    frame_c = channels.append_child("channel")
    frame_c.append_child_value("type", "nirs_frame")
    frame_c.append_child_value("label", "Frame")

    optodes = desc.append_child("optodes")
    for src, det, _short in PAIRS:
        o = optodes.append_child("optode")
        o.append_child_value("custom_name", "S%d-D%d" % (src, det))
    return info


class _ChannelNoise(object):
    """Ruido AR(1) + deriva senoidal lenta por canal - so' precisa ser
    plausivel (< PLAUSIBLE_HBO_ABS_MAX), nao fisiologico."""

    def __init__(self, n_channels, drift_amp, ar1_sigma, ar1_decay=0.995, seed=0):
        rng = random.Random(seed)
        self.state = [0.0] * n_channels
        self.phase = [rng.uniform(0, 2 * math.pi) for _ in range(n_channels)]
        self.freq = [rng.uniform(0.01, 0.03) for _ in range(n_channels)]
        self.drift_amp = drift_amp
        self.ar1_sigma = ar1_sigma
        self.ar1_decay = ar1_decay
        self._rng = rng

    def step(self, t_elapsed):
        out = []
        for c in range(len(self.state)):
            self.state[c] = self.state[c] * self.ar1_decay + self._rng.gauss(0, self.ar1_sigma)
            drift = self.drift_amp * math.sin(2 * math.pi * self.freq[c] * t_elapsed + self.phase[c])
            out.append(drift + self.state[c])
        return out


def run(speed=1.0, stop_after=None, loop=False, name=None, markers=True, verbose=True):
    # 'loop' nao se aplica aqui - a geracao e' continua/infinita por
    # construcao (nao ha dataset finito pra repetir). Mantido no CLI so' por
    # paridade de interface com mock_aurora_lsl.py.
    info = build_stream_info(name or cfg.STREAM_NAME)
    outlet = StreamOutlet(info, chunk_size=1, max_buffered=60)
    marker_outlet = None
    if markers:
        m_info = StreamInfo("Trigger", "Markers", 1, 0, "int32",
                            cfg.STREAM_SOURCE_ID + "_synthetic_markers")
        marker_outlet = StreamOutlet(m_info)

    if verbose:
        print("[mock-synth] stream '%s' %d canais @ %.2f Hz (speed x%.1f), schema real"
              % (info.name(), N_OUT, SFREQ * speed, speed))
        if stop_after:
            print("[mock-synth] parada programada em %.1f s (teste de failsafe)" % stop_after)

    hbo_noise = _ChannelNoise(N_PAIRS, drift_amp=3.0, ar1_sigma=0.15, seed=1)
    hbr_noise = _ChannelNoise(N_PAIRS, drift_amp=1.0, ar1_sigma=0.05, seed=2)
    raw_rng = random.Random(3)

    dt = 1.0 / (SFREQ * speed)
    marker_every_n = max(1, int(SFREQ * 5))  # ~1 marker a cada 5s de dado (device time)
    t0 = local_clock()
    sent = 0
    try:
        while True:
            now = local_clock()
            target = t0 + sent * dt
            if now < target:
                time.sleep(min(target - now, 0.05))
                continue
            if stop_after is not None and (now - t0) >= stop_after:
                if verbose:
                    print("[mock-synth] parando emissao apos %.1f s (%d amostras)"
                          % (now - t0, sent))
                return
            t_elapsed = sent / SFREQ  # tempo de dispositivo, independente de 'speed'

            hbo = hbo_noise.step(t_elapsed)
            hbr = hbr_noise.step(t_elapsed)
            raw760 = [0.02 + raw_rng.gauss(0, 0.002) for _ in range(N_PAIRS)]
            raw850 = [0.03 + raw_rng.gauss(0, 0.002) for _ in range(N_PAIRS)]

            row = raw760 + raw850 + hbo + hbr + [t_elapsed]
            outlet.push_sample(row, target)
            if marker_outlet is not None and sent % marker_every_n == 0:
                marker_outlet.push_sample([1], target)
            sent += 1
    finally:
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--stop-after", type=float, default=None)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--name", default=None)
    p.add_argument("--no-markers", action="store_true")
    a = p.parse_args()
    run(speed=a.speed, stop_after=a.stop_after, loop=a.loop, name=a.name,
        markers=not a.no_markers)
