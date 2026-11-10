"""Camada 2: aquisicao LSL. Mapeia colunas pela metadata do stream."""

import re

import numpy as np
from pylsl import StreamInlet, resolve_byprop

import nf_config as cfg

# Schema real do Aurora (confirmado via script de diagnostico em campo): o
# metadado 'type' vem minusculo/prefixado ('nirs_hbo', 'nirs_hbr', 'nirs_raw',
# 'nirs_frame'), nao 'HbO'/'HbR' como assumido originalmente. Traduzido aqui
# para a interface publica ja usada por quem consome StreamMap (columns(),
# pfc_hbo_columns(), etc.) para nao propagar a mudanca de schema pra fora
# desta camada. 'nirs_raw' nao distingue 760/850nm pelo 'type' - precisa do
# campo separado 'wavelength'.
_TYPE_ALIASES = {"nirs_hbo": "HbO", "nirs_hbr": "HbR", "nirs_frame": "timestamp"}

# A metadata real nao populam 'source'/'detector' (vem vazios) - o par
# fonte-detector precisa ser extraido de 'custom_name' ("S{n}-D{n}"), com
# fallback pro 'label' ("{src}-{det}:{idx}") quando custom_name estiver
# ausente.
_CUSTOM_NAME_RE = re.compile(r"S(\d+)-D(\d+)")
_LABEL_PAIR_RE = re.compile(r"(\d+)-(\d+):\d+")


def _translate_type(raw_type, wavelength):
    if raw_type == "nirs_raw":
        try:
            wl = float(wavelength)
        except (TypeError, ValueError):
            return "raw"
        if wl == 760.0:
            return "raw760"
        if wl == 850.0:
            return "raw850"
        return "raw"
    return _TYPE_ALIASES.get(raw_type, raw_type)


def _parse_source_detector(custom_name, label):
    if custom_name:
        m = _CUSTOM_NAME_RE.search(custom_name)
        if m:
            return "S" + m.group(1), "D" + m.group(2)
    if label:
        m = _LABEL_PAIR_RE.search(label)
        if m:
            return "S" + m.group(1), "D" + m.group(2)
    return "", ""


class StreamMap(object):
    """Indice de colunas derivado da metadata (nunca hardcoded)."""

    def __init__(self, info):
        self.name = info.name()
        self.sfreq = info.nominal_srate()
        self.n_channels = info.channel_count()
        self.channels = []
        ch = info.desc().child("channels").child("channel")
        while not ch.empty():
            custom_name = ch.child_value("custom_name")
            label = ch.child_value("label")
            source = ch.child_value("source")
            detector = ch.child_value("detector")
            if not source or not detector:
                source, detector = _parse_source_detector(custom_name, label)
            self.channels.append(dict(
                label=label,
                type=_translate_type(ch.child_value("type"), ch.child_value("wavelength")),
                unit=ch.child_value("unit"),
                source=source,
                detector=detector,
                short=ch.child_value("short_channel") == "true",
            ))
            ch = ch.next_sibling()
        if len(self.channels) != self.n_channels:
            raise RuntimeError("metadata incompleta: %d rotulos para %d canais"
                               % (len(self.channels), self.n_channels))

    def columns(self, ctype, pairs=None):
        """Indices das colunas de um tipo ('HbO', 'HbR', 'raw760', ...)."""
        out = []
        for i, c in enumerate(self.channels):
            if c["type"] != ctype:
                continue
            if pairs is not None and (c["source"], c["detector"]) not in pairs:
                continue
            out.append(i)
        return out

    def pfc_hbo_columns(self, pairs):
        cols = []
        found = []
        for pair in pairs:
            hit = [i for i, c in enumerate(self.channels)
                   if c["type"] == "HbO" and (c["source"], c["detector"]) == pair]
            if len(hit) == 1:
                cols.append(hit[0])
                found.append(pair)
        missing = [p for p in pairs if p not in found]
        if missing:
            raise RuntimeError("canais PFC ausentes na metadata: %s" % (missing,))
        return cols

    def short_hbo_columns(self):
        return [i for i, c in enumerate(self.channels)
                if c["type"] == "HbO" and c["short"]]

    def timestamp_column(self):
        for i, c in enumerate(self.channels):
            if c["type"] == "timestamp":
                return i
        return None


class Acquisition(object):
    """Inlet + failsafe: amostra invalida nunca sobrescreve a ultima valida."""

    def __init__(self, stream_name=None, timeout=10.0, pairs=None):
        """Resolve o stream Data Out por nome via LSL. Identico em replay e ao
        vivo: resolve_byprop nao distingue quem publica o stream (mock local
        ou Aurora real) - o nome e' o unico contrato. REPLAY_MODE nao gate-ia
        mais esta chamada; e' so metadado informativo para logs/UI."""
        name = stream_name or cfg.STREAM_NAME
        streams = resolve_byprop("name", name, 1, timeout)
        if not streams:
            raise RuntimeError("stream '%s' nao encontrado" % name)
        self.inlet = StreamInlet(streams[0], max_buflen=60, recover=False)
        self.map = StreamMap(self.inlet.info(timeout))
        pairs = [tuple(p) for p in (pairs if pairs is not None else cfg.PFC_CHANNELS)]
        self.pfc_cols = self.map.pfc_hbo_columns(pairs)
        self.short_cols = self.map.short_hbo_columns()
        self.ts_col = self.map.timestamp_column()
        self.last_valid = None      # (lsl_ts, device_ts, pfc_vector)
        self.n_valid = 0
        self.n_invalid = 0

    def pull(self, timeout=0.0):
        """Devolve (lsl_ts, device_ts, pfc_hbo_array) ou None se nao houve
        amostra valida agora. Nunca devolve dado obsoleto como se fosse novo."""
        try:
            sample, ts = self.inlet.pull_sample(timeout=timeout)
        except Exception:
            return None
        if sample is None:
            return None
        arr = np.asarray(sample, dtype=float)
        pfc = arr[self.pfc_cols]
        if not np.all(np.isfinite(pfc)):
            self.n_invalid += 1
            return None
        dev_ts = float(arr[self.ts_col]) if self.ts_col is not None else float(ts)
        self.n_valid += 1
        self.last_valid = (float(ts), dev_ts, pfc)
        return self.last_valid

    def drain(self, max_samples=64, timeout=0.0):
        """Consome o que estiver disponivel; devolve lista de amostras validas."""
        out = []
        for _ in range(max_samples):
            s = self.pull(timeout=timeout)
            if s is None:
                break
            out.append(s)
            timeout = 0.0
        return out

    def close(self):
        try:
            self.inlet.close_stream()
        except Exception:
            pass
