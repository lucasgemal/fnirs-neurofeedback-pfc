"""Camada 1 offline: .nirs (Homer2) -> HbO/HbR via Beer-Lambert modificada.

Gera o cache usado pelo servidor de replay. Nada aqui toca hardware.
"""

import numpy as np
import scipy.io as sio

import nf_config as cfg


def load_nirs(path):
    """Le o .nirs e devolve (t, d, measlist, lambdas, src_pos, det_pos, s)."""
    m = sio.loadmat(path)
    sd = m["SD"][0, 0]
    return dict(
        t=m["t"][:, 0].astype(float),
        d=m["d"].astype(float),
        measlist=sd["MeasList"].astype(int),
        lambdas=sd["Lambda"][0].astype(float),
        src_pos=sd["SrcPos"].astype(float),
        det_pos=sd["DetPos"].astype(float),
        s=m["s"].astype(float),
    )


def channel_table(raw):
    """Pares fonte-detector unicos, na ordem do MeasList do 1o comprimento."""
    ml = raw["measlist"]
    wl1 = ml[ml[:, 3] == 1]
    chans = []
    for i, (src, det) in enumerate(wl1[:, :2], start=1):
        dist_mm = float(np.linalg.norm(raw["src_pos"][src - 1] - raw["det_pos"][det - 1]))
        chans.append(dict(
            index=i, source=int(src), detector=int(det),
            source_label=cfg.SOURCE_LABELS.get(int(src), "S%d" % src),
            detector_label=cfg.DETECTOR_LABELS.get(int(det), "D%02d" % det),
            distance_cm=dist_mm / 10.0,
            short=(dist_mm / 10.0) <= cfg.SHORT_CHANNEL_MAX_CM,
        ))
    return chans


def _column_of(measlist, src, det, wl_idx):
    hit = np.where((measlist[:, 0] == src) & (measlist[:, 1] == det)
                   & (measlist[:, 3] == wl_idx))[0]
    if len(hit) != 1:
        raise ValueError("coluna ambigua para S%d-D%d wl%d" % (src, det, wl_idx))
    return int(hit[0])


def intensity_to_od(intensity):
    """dOD = -log(I / media(I)), com guarda contra zero/negativo."""
    safe = np.clip(intensity, 1e-12, None)
    return -np.log(safe / safe.mean(axis=0, keepdims=True))


def od_to_conc(dod_760, dod_850, distance_cm):
    """mBLL 2x2 por canal. Entrada em dOD, saida em umol/L."""
    e = np.array([
        [cfg.EXTINCTION[760.0][0] * cfg.DPF[760.0],
         cfg.EXTINCTION[760.0][1] * cfg.DPF[760.0]],
        [cfg.EXTINCTION[850.0][0] * cfg.DPF[850.0],
         cfg.EXTINCTION[850.0][1] * cfg.DPF[850.0]],
    ]) * distance_cm
    conc = np.linalg.solve(e, np.vstack([dod_760, dod_850]))  # M
    return conc[0] * 1e6, conc[1] * 1e6


def convert(path=None, out=None):
    path = path or cfg.NIRS_FILE
    out = out or cfg.HB_CACHE
    raw = load_nirs(path)
    chans = channel_table(raw)
    ml, d = raw["measlist"], raw["d"]
    n_t, n_ch = d.shape[0], len(chans)

    raw760 = np.empty((n_t, n_ch))
    raw850 = np.empty((n_t, n_ch))
    for k, ch in enumerate(chans):
        raw760[:, k] = d[:, _column_of(ml, ch["source"], ch["detector"], 1)]
        raw850[:, k] = d[:, _column_of(ml, ch["source"], ch["detector"], 2)]

    od760 = intensity_to_od(raw760)
    od850 = intensity_to_od(raw850)
    hbo = np.empty((n_t, n_ch))
    hbr = np.empty((n_t, n_ch))
    for k, ch in enumerate(chans):
        hbo[:, k], hbr[:, k] = od_to_conc(od760[:, k], od850[:, k], ch["distance_cm"])

    t = raw["t"]
    sfreq = float(1.0 / np.median(np.diff(t)))
    np.savez_compressed(
        out, t=t, raw760=raw760, raw850=raw850, hbo=hbo, hbr=hbr,
        events=raw["s"], sfreq=sfreq,
        ch_index=np.array([c["index"] for c in chans]),
        ch_source=np.array([c["source_label"] for c in chans]),
        ch_detector=np.array([c["detector_label"] for c in chans]),
        ch_distance_cm=np.array([c["distance_cm"] for c in chans]),
        ch_short=np.array([c["short"] for c in chans]),
    )
    return out, dict(n_samples=n_t, n_channels=n_ch, sfreq=sfreq, chans=chans)


if __name__ == "__main__":
    out, info = convert()
    print("cache: %s" % out)
    print("amostras=%d canais=%d sfreq=%.3f Hz" %
          (info["n_samples"], info["n_channels"], info["sfreq"]))
    for c in info["chans"]:
        print("  ch%-3d %-4s-%-4s  %.2f cm%s" % (c["index"], c["source_label"],
              c["detector_label"], c["distance_cm"], "  [short]" if c["short"] else ""))
