"""Teste de aceitacao do replay (CLAUDE.md, criterio 5). Roda sem display."""

import csv
import json
import os
import subprocess
import sys
import time

import nf_config as cfg
import run_neurofeedback

SPEED = 10.0          # 10x mais rapido que os ~10.17 Hz originais
MOCK_STOP_AFTER = 12  # segundos de parede ate o mock parar de emitir
RUN_DURATION = 18     # segundos de parede do pipeline


def _read_log(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main():
    assert cfg.REPLAY_MODE, "REPLAY_MODE deve ser True nesta fase"
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(cfg.HB_CACHE):
        subprocess.check_call([sys.executable, os.path.join(here, "nirs_to_hb.py")])

    mock = subprocess.Popen(
        [sys.executable, os.path.join(here, "mock_aurora_lsl.py"),
         "--speed", str(SPEED), "--stop-after", str(MOCK_STOP_AFTER)],
        cwd=here)
    time.sleep(2.0)
    try:
        summary = run_neurofeedback.run(duration=RUN_DURATION, display=False,
                                        log_prefix="acceptance", quiet=True)
    finally:
        if mock.poll() is None:
            mock.terminate()
        mock.wait(timeout=5)

    rows = _read_log(summary["csv"])
    meta = json.load(open(summary["meta"]))
    lo, hi = cfg.ALTITUDE_RANGE  # mesma faixa que trail_display.py rescala para progresso 0-1

    def to_progress(a):
        return max(0.0, min(1.0, (a - lo) / (hi - lo)))

    alt = [float(r["altitude"]) for r in rows]
    states = [r["state"] for r in rows]
    running = [to_progress(float(r["altitude"])) for r in rows if r["state"] == "running"]
    failsafe = [to_progress(float(r["altitude"])) for r in rows if r["state"] == "failsafe"]

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # --- Camada 2: mapeamento dinamico por metadata
    n_ch = meta["n_stream_channels"]
    n_pairs = (n_ch - 1) // 4
    hbo_block = range(2 * n_pairs, 3 * n_pairs)
    check("mapeamento PFC via metadata",
          len(meta["pfc_hbo_columns"]) == len(cfg.PFC_CHANNELS)
          and all(c in hbo_block for c in meta["pfc_hbo_columns"]),
          "cols=%s labels=%s" % (meta["pfc_hbo_columns"], meta["pfc_labels"]))

    # --- Camadas 3-4: resposta continua ao HbO (progresso 0-1 na trilha)
    jump_tol = 0.05 / (hi - lo)  # mesma tolerancia relativa usada em altitude
    check("baseline concluido", "running" in states,
          "%d amostras validas" % summary["n_valid"])
    check("progresso na trilha varia continuamente",
          len(set(running)) > 50 and (max(running) - min(running)) > 0.02 / (hi - lo),
          "%d valores distintos, faixa %.3f" %
          (len(set(running)), (max(running) - min(running)) if running else 0))
    jumps = [abs(b - a) for a, b in zip(running, running[1:])]
    check("sem saltos/limiar (movimento suave)",
          bool(jumps) and max(jumps) < jump_tol,
          "salto maximo %.4f" % (max(jumps) if jumps else -1))

    # --- failsafe
    check("failsafe ativado quando o mock para", len(failsafe) > 0,
          "%d frames em failsafe" % len(failsafe))
    if running and failsafe:
        drift = max(abs(a - running[-1]) for a in failsafe)
        check("planeio sem queda", drift < jump_tol, "desvio maximo %.4f" % drift)
        check("nao recua ao inicio da trilha",
              min(failsafe) > 0.0 + 1e-6,
              "min=%.3f" % min(failsafe))

    # --- Camada 5: log
    check("log gerado e consistente",
          len(rows) > 100 and all(r["state"] in ("baseline", "running", "failsafe")
                                  for r in rows)
          and all(a == a for a in alt),
          "%d linhas em %s" % (len(rows), os.path.basename(summary["csv"])))
    n_ts = sum(1 for r in rows if r["device_time"])
    check("log tem timestamps do dispositivo", n_ts > 100, "%d linhas" % n_ts)
    n_mark = sum(1 for r in rows if r["marker"])
    check("markers do mock registrados", n_mark > 0, "%d frames com marker" % n_mark)

    print("")
    for name, ok, detail in checks:
        print("[%s] %-38s %s" % ("OK " if ok else "FALHA", name, detail))
    ok = all(c[1] for c in checks)
    print("\nRESULTADO: %s" % ("APROVADO" if ok else "REPROVADO"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
