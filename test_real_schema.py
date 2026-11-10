"""Valida as 3 correcoes do schema real do Aurora (script de diagnostico em
campo, 97 canais / 8 fontes / 15 detectores / 8 short-distance) sem precisar
de hardware: constroi uma metadata LSL sintetica com o schema real
('nirs_hbo'/'nirs_hbr'/'nirs_raw'+wavelength/'nirs_frame', 'custom_name'
"S{n}-D{n}", fallback pro 'label' "{src}-{det}:{idx}", source/detector
vazios) e exercita StreamMap, Acquisition, o worker de deteccao de canais do
painel e o novo publish de markers.

Mesmo padrao de test_session_state_machine.py: funcoes check() imprimem
[OK]/[FALHA], main() agrega e retorna 0/1.
"""

import os
import queue
import sys
import threading
import time

from pylsl import StreamInfo, StreamInlet, StreamOutlet, local_clock, resolve_byprop

import nf_config as cfg
from acquisition import Acquisition, StreamMap
from control_panel import ControlPanel
from nfb_process import NfbSession

STREAM_NAME = "AuroraRealSchemaTest_%d" % os.getpid()
SOURCE_ID = "real_schema_test_%d" % os.getpid()
SFREQ = 10.2

# 24 pares fonte-detector: 16 "longos" + 8 short-distance (8 fontes / 15
# detectores, igual a montagem real capturada em campo).
PAIRS = [
    (1, 1, False), (1, 2, False), (2, 1, False), (2, 2, False),
    (3, 3, False), (3, 4, False), (4, 3, False), (4, 4, False),
    (5, 5, False), (5, 6, False), (6, 5, False), (6, 6, False),
    (7, 7, False), (7, 8, False), (8, 7, False), (8, 8, False),
    (1, 9, True), (2, 10, True), (3, 11, True), (4, 12, True),
    (5, 13, True), (6, 14, True), (7, 15, True), (8, 9, True),
]
# Ultimos 3 pares: sem 'custom_name', so' 'label' - exercita o fallback.
FALLBACK_IDX = {21, 22, 23}
N_PAIRS = len(PAIRS)
N_OUT = 4 * N_PAIRS + 1  # raw760 + raw850 + HbO + HbR + frame = 97

RAW760_OFFSET = 0
RAW850_OFFSET = N_PAIRS
HBO_OFFSET = 2 * N_PAIRS
HBR_OFFSET = 3 * N_PAIRS
FRAME_COL = 4 * N_PAIRS


def check(name, ok, detail=""):
    print("[%s] %-55s %s" % ("OK  " if ok else "FALHA", name, detail))
    return bool(ok)


def _add_channel(channels, global_idx, pair_idx, kind, wavelength=None):
    src, det, short = PAIRS[pair_idx]
    c = channels.append_child("channel")
    if pair_idx in FALLBACK_IDX:
        # metadata real sem 'custom_name': so' o 'label' "{src}-{det}:{idx}".
        c.append_child_value("label", "%d-%d:%d" % (src, det, global_idx))
    else:
        c.append_child_value("custom_name", "S%d-D%d" % (src, det))
        c.append_child_value("label", "%s%s" % (kind, wavelength or ""))
    c.append_child_value("type", kind)
    if wavelength is not None:
        c.append_child_value("wavelength", str(wavelength))
    unit = "umol/L" if kind in ("nirs_hbo", "nirs_hbr") else ("V" if kind == "nirs_raw" else "s")
    c.append_child_value("unit", unit)
    c.append_child_value("short_channel", "true" if short else "false")
    # campos 'source'/'detector' deliberadamente omitidos - na metadata real
    # vem vazios, o par tem que vir de custom_name/label.


def build_real_schema_info():
    info = StreamInfo(STREAM_NAME, "NIRS", N_OUT, SFREQ, "double64", SOURCE_ID)
    channels = info.desc().append_child("channels")
    idx = 0
    for pi in range(N_PAIRS):
        _add_channel(channels, idx, pi, "nirs_raw", 760.0); idx += 1
    for pi in range(N_PAIRS):
        _add_channel(channels, idx, pi, "nirs_raw", 850.0); idx += 1
    for pi in range(N_PAIRS):
        _add_channel(channels, idx, pi, "nirs_hbo"); idx += 1
    for pi in range(N_PAIRS):
        _add_channel(channels, idx, pi, "nirs_hbr"); idx += 1
    frame_c = channels.append_child("channel")
    frame_c.append_child_value("type", "nirs_frame")
    frame_c.append_child_value("label", "Frame")
    idx += 1
    assert idx == N_OUT
    return info


def build_sample():
    # HbO fica sob PLAUSIBLE_HBO_ABS_MAX (200.0, checado por nfb_process._do_sync)
    # mas ainda distinto por canal, pra provar mapeamento de coluna correto.
    row = [0.0] * N_OUT
    for pi in range(N_PAIRS):
        row[RAW760_OFFSET + pi] = float(pi + 1)
        row[RAW850_OFFSET + pi] = float(pi + 2)
        row[HBO_OFFSET + pi] = pi * 1.0
        row[HBR_OFFSET + pi] = pi * 1.0 + 1000.0
    row[FRAME_COL] = 999.5
    return row


class Pusher(threading.Thread):
    """Publica a mesma amostra em loop, como o mock_aurora_lsl.py faz, para
    que qualquer Acquisition/StreamInlet aberto durante o teste tenha dado
    disponivel para puxar."""

    def __init__(self, outlet, sample, hz=30.0):
        threading.Thread.__init__(self)
        self.daemon = True
        self.outlet = outlet
        self.sample = sample
        self.dt = 1.0 / hz
        self.stop_flag = threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            self.outlet.push_sample(self.sample, local_clock())
            time.sleep(self.dt)

    def stop(self):
        self.stop_flag.set()


def expected_pair(pair_idx):
    src, det, _short = PAIRS[pair_idx]
    return ("S%d" % src, "D%d" % det)


def test_stream_map():
    info = build_real_schema_info()
    outlet = StreamOutlet(info)
    pusher = Pusher(outlet, build_sample())
    pusher.start()
    checks = []
    try:
        found = resolve_byprop("name", STREAM_NAME, 1, 5.0)
        checks.append(check("stream sintetico resolvido", bool(found)))
        if not found:
            return checks
        inlet = StreamInlet(found[0], recover=False)
        smap = StreamMap(inlet.info(3.0))
        inlet.close_stream()

        checks.append(check("97 canais mapeados", smap.n_channels == N_OUT,
                             "n_channels=%d" % smap.n_channels))

        hbo_pairs = [(c["source"], c["detector"]) for c in smap.channels if c["type"] == "HbO"]
        hbr_pairs = [(c["source"], c["detector"]) for c in smap.channels if c["type"] == "HbR"]
        expected = [expected_pair(pi) for pi in range(N_PAIRS)]
        checks.append(check("24 pares HbO extraidos corretamente (custom_name + fallback label)",
                             hbo_pairs == expected, "hbo_pairs=%s" % hbo_pairs))
        checks.append(check("24 pares HbR extraidos corretamente",
                             hbr_pairs == expected, "hbr_pairs=%s" % hbr_pairs))

        raw760 = [i for i, c in enumerate(smap.channels) if c["type"] == "raw760"]
        raw850 = [i for i, c in enumerate(smap.channels) if c["type"] == "raw850"]
        checks.append(check("nirs_raw@760 distinguido de @850 via 'wavelength'",
                             len(raw760) == N_PAIRS and len(raw850) == N_PAIRS
                             and not set(raw760) & set(raw850),
                             "raw760=%d raw850=%d" % (len(raw760), len(raw850))))

        checks.append(check("nirs_frame traduzido para coluna de timestamp",
                             smap.timestamp_column() == FRAME_COL,
                             "timestamp_column=%s esperado=%s" % (smap.timestamp_column(), FRAME_COL)))

        short_cols = smap.short_hbo_columns()
        expected_short = [HBO_OFFSET + pi for pi in range(N_PAIRS) if PAIRS[pi][2]]
        checks.append(check("8 canais HbO short-distance identificados",
                             sorted(short_cols) == sorted(expected_short),
                             "short_cols=%s" % short_cols))
    finally:
        pusher.stop()
        pusher.join(timeout=2.0)
    return checks


def test_acquisition_roi():
    info = build_real_schema_info()
    outlet = StreamOutlet(info)
    pusher = Pusher(outlet, build_sample())
    pusher.start()
    checks = []
    try:
        roi = [expected_pair(pi) for pi in (0, 5, 21, 23)]  # inclui pares via fallback de label
        acq = Acquisition(stream_name=STREAM_NAME, pairs=roi, timeout=5.0)
        sample = acq.pull(timeout=3.0)
        checks.append(check("Acquisition mapeia ROI arbitrario (inclui pares via fallback)",
                             sample is not None and len(acq.pfc_cols) == 4,
                             "pfc_cols=%s" % (acq.pfc_cols if sample else None)))
        if sample is not None:
            _lsl_ts, _dev_ts, pfc = sample
            want = [0 * 1.0, 5 * 1.0, 21 * 1.0, 23 * 1.0]
            checks.append(check("valores de HbO lidos batem com as colunas certas",
                                 list(pfc) == want, "pfc=%s want=%s" % (list(pfc), want)))
        acq.close()
    finally:
        pusher.stop()
        pusher.join(timeout=2.0)
    return checks


def test_channel_detection_worker():
    """Mesma logica que control_panel._detect_channels_worker roda de fato,
    sem precisar abrir a janela tkinter (so' usa self.detect_queue)."""
    info = build_real_schema_info()
    outlet = StreamOutlet(info)
    pusher = Pusher(outlet, build_sample())
    pusher.start()
    checks = []
    try:
        class FakeSelf(object):
            detect_queue = queue.Queue()

        fake = FakeSelf()
        ControlPanel._detect_channels_worker(fake, STREAM_NAME)
        kind, payload = fake.detect_queue.get(timeout=5.0)
        checks.append(check("deteccao de canais retorna 'ok'", kind == "ok", "kind=%s" % kind))
        if kind == "ok":
            checks.append(check("24 pares crus detectados (S{n}-D{n}, sem traducao anatomica)",
                                 sorted(payload) == sorted(expected_pair(pi) for pi in range(N_PAIRS)),
                                 "%d pares: %s" % (len(payload), payload[:3])))
            keys = ["%s-%s" % p for p in payload]
            checks.append(check("formato de exibicao 'S1-D1' (raw, nao 'AF7-Fp1')",
                                 "S1-D1" in keys, "keys[:5]=%s" % keys[:5]))
    finally:
        pusher.stop()
        pusher.join(timeout=2.0)
    return checks


def test_sync_empty_roi():
    info = build_real_schema_info()
    outlet = StreamOutlet(info)
    pusher = Pusher(outlet, build_sample())
    pusher.start()
    checks = []
    try:
        sess = NfbSession(display_factory=lambda: None)
        sess.config.update(stream_name=STREAM_NAME, pairs=[])
        sess._do_sync()
        chres = sess.sync_result.get("channels", {})
        checks.append(check("ROI vazio -> channels ok=False (nao 0/0 trivial)",
                             chres.get("ok") is False, "channels=%s" % chres))
        checks.append(check("mensagem explicita de ROI vazio",
                             "nenhum canal selecionado" in chres.get("detail", ""),
                             "detail=%r" % chres.get("detail")))
        checks.append(check("sessao nao avanca para 'synced' com ROI vazio",
                             sess.phase == "idle", "phase=%s" % sess.phase))

        # controle positivo: mesmo stream, ROI nao vazio -> sync completo.
        sess2 = NfbSession(display_factory=lambda: None)
        sess2.config.update(stream_name=STREAM_NAME,
                             pairs=[list(expected_pair(pi)) for pi in (0, 21)])
        sess2._do_sync()
        checks.append(check("controle positivo: ROI nao vazio sincroniza normalmente",
                             sess2.phase == "synced", "sync=%s" % sess2.sync_result))
    finally:
        pusher.stop()
        pusher.join(timeout=2.0)
    return checks


def test_marker_publish():
    checks = []
    sess = NfbSession(display_factory=lambda: None)
    try:
        found = resolve_byprop("source_id", cfg.TRIGGER_SOURCE_ID, 1, 3.0)
        checks.append(check("nfb_process publica outlet 'Trigger'/Markers desde a criacao",
                             bool(found), "found=%s" % bool(found)))
        if not found:
            return checks
        inlet = StreamInlet(found[0], recover=False)
        inlet.open_stream(timeout=3.0)  # forca a conexao antes de publicar,
        # senao o primeiro push pode chegar antes do handshake terminar.
        time.sleep(0.3)
        sess._emit_marker(cfg.MARKER_BASELINE_START)
        sample, _ts = inlet.pull_sample(timeout=3.0)
        checks.append(check("marker de baseline publicado com o codigo certo",
                             sample == [cfg.MARKER_BASELINE_START], "sample=%s" % sample))
        inlet.close_stream()

        # _do_sync deve conseguir resolver um stream 'Markers' real sem
        # nenhum outro processo publicando em paralelo - so' o proprio nfb.
        info = build_real_schema_info()
        outlet = StreamOutlet(info)
        pusher = Pusher(outlet, build_sample())
        pusher.start()
        try:
            sess.config.update(stream_name=STREAM_NAME,
                                pairs=[list(expected_pair(0))])
            sess._do_sync()
            trig = sess.sync_result.get("trigger", {})
            checks.append(check("_do_sync resolve o proprio stream de markers (sem processo externo)",
                                 trig.get("ok") is True, "trigger=%s" % trig))
        finally:
            pusher.stop()
            pusher.join(timeout=2.0)
    finally:
        del sess
    return checks


def main():
    all_checks = []
    all_checks += test_stream_map()
    all_checks += test_acquisition_roi()
    all_checks += test_channel_detection_worker()
    all_checks += test_sync_empty_roi()
    all_checks += test_marker_publish()

    ok = all(all_checks)
    print("\nRESULTADO: %s (%d/%d)" % ("APROVADO" if ok else "REPROVADO",
                                        sum(1 for c in all_checks if c), len(all_checks)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
