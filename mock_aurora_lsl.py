"""Servidor de replay LSL que imita o Data Out do Aurora (secao 8.1.1).

Colunas: [n raw 760nm] + [n raw 850nm] + [n HbO uM] + [n HbR uM] + timestamp.
Metadata carrega rotulos de canal, fonte/detector, unidade e sfreq — a Camada 2
deve mapear as colunas por essa metadata, nunca por indice fixo.
"""

import argparse
import time

import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock

import nf_config as cfg


def build_stream_info(chans, sfreq, name):
    n = len(chans)
    n_out = 4 * n + 1
    info = StreamInfo(name, cfg.STREAM_TYPE, n_out, sfreq, "double64",
                      cfg.STREAM_SOURCE_ID)
    desc = info.desc()
    desc.append_child_value("manufacturer", "NIRx (mock replay)")
    desc.append_child_value("serial_number", cfg.SERIAL_NUMBER)
    desc.append_child_value("replay_mode", "true")

    channels = desc.append_child("channels")
    blocks = [("raw", "760", "V"), ("raw", "850", "V"),
              ("HbO", "", "umol/L"), ("HbR", "", "umol/L")]
    for kind, wl, unit in blocks:
        for ch in chans:
            c = channels.append_child("channel")
            label = "%s-%s %s%s" % (ch["source_label"], ch["detector_label"],
                                    kind, wl)
            c.append_child_value("label", label)
            c.append_child_value("type", kind + wl)
            c.append_child_value("unit", unit)
            c.append_child_value("source", ch["source_label"])
            c.append_child_value("detector", ch["detector_label"])
            c.append_child_value("channel_index", str(ch["index"]))
            c.append_child_value("distance_cm", "%.2f" % ch["distance_cm"])
            c.append_child_value("short_channel", "true" if ch["short"] else "false")
            if wl:
                c.append_child_value("wavelength", wl)
    c = channels.append_child("channel")
    c.append_child_value("label", "Timestamp")
    c.append_child_value("type", "timestamp")
    c.append_child_value("unit", "s")

    optodes = desc.append_child("optodes")
    for ch in chans:
        o = optodes.append_child("optode")
        o.append_child_value("source", ch["source_label"])
        o.append_child_value("detector", ch["detector_label"])
    return info


def load_cache(path):
    z = np.load(path, allow_pickle=False)
    chans = [dict(index=int(z["ch_index"][i]),
                  source_label=str(z["ch_source"][i]),
                  detector_label=str(z["ch_detector"][i]),
                  distance_cm=float(z["ch_distance_cm"][i]),
                  short=bool(z["ch_short"][i]))
             for i in range(len(z["ch_index"]))]
    return z, chans


def run(speed=1.0, stop_after=None, loop=False, name=None, markers=True,
        verbose=True):
    z, chans = load_cache(cfg.HB_CACHE)
    sfreq = float(z["sfreq"])
    data = np.hstack([z["raw760"], z["raw850"], z["hbo"], z["hbr"]])
    t = z["t"]
    events = z["events"]
    n_samples = data.shape[0]

    info = build_stream_info(chans, sfreq * speed, name or cfg.STREAM_NAME)
    outlet = StreamOutlet(info, chunk_size=1, max_buffered=60)
    marker_outlet = None
    if markers:
        m_info = StreamInfo("Trigger", "Markers", 1, 0, "int32",
                            cfg.STREAM_SOURCE_ID + "_markers")
        marker_outlet = StreamOutlet(m_info)

    if verbose:
        print("[mock] stream '%s' %d canais @ %.2f Hz (speed x%.1f)"
              % (info.name(), info.channel_count(), sfreq * speed, speed))
        if stop_after:
            print("[mock] parada programada em %.1f s (teste de failsafe)" % stop_after)

    dt = 1.0 / (sfreq * speed)
    t0 = local_clock()
    i = 0
    sent = 0
    while True:
        now = local_clock()
        target = t0 + sent * dt
        if now < target:
            time.sleep(min(target - now, 0.05))
            continue
        if stop_after is not None and (now - t0) >= stop_after:
            if verbose:
                print("[mock] parando emissao apos %.1f s (%d amostras)"
                      % (now - t0, sent))
            return
        sample = data[i].tolist() + [float(t[i])]
        outlet.push_sample(sample, target)
        if marker_outlet is not None:
            row = np.nonzero(events[i])[0]
            for col in row:
                marker_outlet.push_sample([int(col) + 1], target)
        sent += 1
        i += 1
        if i >= n_samples:
            if not loop:
                if verbose:
                    print("[mock] fim dos dados (%d amostras)" % sent)
                return
            i = 0


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
