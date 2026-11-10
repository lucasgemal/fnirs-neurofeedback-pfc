"""Exercita a maquina de estados do processo B (nfb_process.NfbSession) e o
IPC (session_ipc), sem abrir janela PsychoPy/OpenGL - usa um display falso
(FakeDisplay) no lugar de trail_display.TrailDisplay, ja que a logica de
orquestracao (sync/play/gate manual do baseline/stop) e' independente do
motor grafico.

Fluxo coberto, igual ao que o painel de controle dispara por clique de botao:
CONFIGURE (ROI = PFC_CHANNELS real) -> SYNC -> PLAY (baseline) -> aguarda
baseline_ready (NAO avanca sozinho) -> START_NFB (confirmacao) -> running ->
STOP -> log/meta.

Usa mock_aurora_lsl_synthetic.py (nao mock_aurora_lsl.py) porque este ultimo
reproduz o '.nirs' de teste no schema ANTIGO (rotulos anatomicos direto em
source/detector) - incompativel com PFC_CHANNELS no formato real 'S{n}-D{n}'
(ver CLAUDE.md, "schema real do Aurora corrigido"). O mock sintetico gera
dado diretamente no schema real e inclui literalmente os pares de
PFC_CHANNELS, entao o teste valida fim-a-fim contra o ROI real sem precisar
de um subconjunto manual.
"""

import csv
import json
import os
import subprocess
import sys
import time

import nf_config as cfg
import session_ipc as ipc
from nfb_process import NfbSession
from pylsl import local_clock

HERE = os.path.dirname(os.path.abspath(__file__))
SPEED = 10.0
MOCK_STOP_AFTER = 20.0


class FakeDisplay(object):
    def __init__(self):
        self.frames = 0
        self.last_altitude = None
        self.last_state = None

    def draw(self, altitude, snap, dt=0.0):
        self.frames += 1
        self.last_altitude = altitude
        self.last_state = snap["state"]

    def should_quit(self):
        return False

    def close(self):
        pass


def check(name, ok, detail=""):
    print("[%s] %-45s %s" % ("OK  " if ok else "FALHA", name, detail))
    return bool(ok)


def run_session(pairs):
    disp = FakeDisplay()
    sess = NfbSession(display_factory=lambda: disp)
    sess.disp = disp

    # CONFIGURE com ROI customizado (subconjunto), participante/sessao -
    # mesma via que o painel usa (session_ipc), nao chamada direta.
    ipc.send_command(1, "CONFIGURE", dict(
        participant_id="P07", session_id="3",
        stream_name=cfg.STREAM_NAME, pairs=[list(p) for p in pairs]))
    cmd = ipc.read_command()
    sess.last_cmd_id = cmd["id"]
    sess.handle_command(cmd["cmd"], cmd["payload"])

    sess.handle_command("SYNC", {})
    checks = []
    checks.append(check("SYNC resolve trigger+aurora+canais",
                         sess.phase == "synced", "sync=%s" % sess.sync_result))

    sess.handle_command("PLAY", {})
    checks.append(check("PLAY inicia baseline", sess.phase == "baseline",
                         "phase=%s" % sess.phase))
    checks.append(check("PLAY nao avanca a tela (alvo em 0)",
                         disp.frames == 0, "frames antes do primeiro tick=%d" % disp.frames))

    t0 = local_clock()
    prev = t0
    reached_ready = False
    while local_clock() - t0 < 8.0:
        now = local_clock()
        dt = now - prev
        prev = now
        with sess.worker.lock:
            pass  # so' pra garantir que o worker existe/nao morreu
        sess.tick(now, dt)
        if sess.pipeline.state == "baseline_ready":
            reached_ready = True
            break
        time.sleep(0.03)
    checks.append(check("baseline termina em baseline_ready (nao pula sozinho p/ running)",
                         reached_ready, "estado apos espera=%s" % sess.pipeline.state))

    # roda mais alguns frames ainda em baseline_ready: tela deve continuar parada
    for _ in range(10):
        now = local_clock()
        sess.tick(now, 0.03)
        time.sleep(0.01)
    checks.append(check("tela fica parada em baseline_ready ate confirmacao",
                         disp.last_state == "baseline_ready", "last_state=%s" % disp.last_state))

    sess.handle_command("START_NFB", {})
    checks.append(check("START_NFB confirma avanco para regulation",
                         sess.phase == "regulation" and sess.pipeline.state == "running",
                         "phase=%s pipeline_state=%s" % (sess.phase, sess.pipeline.state)))

    for _ in range(15):
        now = local_clock()
        sess.tick(now, 0.03)
        time.sleep(0.03)

    sess.handle_command("STOP", {})
    checks.append(check("STOP encerra sessao e produz resumo",
                         sess.phase == "stopped" and sess.last_summary is not None,
                         "summary=%s" % sess.last_summary))

    if sess.last_summary:
        rows = list(csv.DictReader(open(sess.last_summary["csv"], newline="")))
        states = set(r["state"] for r in rows)
        checks.append(check("log contem baseline_ready e running",
                             {"baseline_ready", "running"} <= states, "estados=%s" % states))
        meta = json.load(open(sess.last_summary["meta"]))
        checks.append(check("meta registra participante/sessao/ROI selecionado",
                             meta.get("participant_id") == "P07"
                             and meta.get("session_id") == "3"
                             and meta.get("pfc_pairs") == [list(p) for p in pairs],
                             "participant_id=%s session_id=%s pairs=%s"
                             % (meta.get("participant_id"), meta.get("session_id"),
                                meta.get("pfc_pairs"))))

    return checks


def main():
    ipc.reset()
    mock = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "mock_aurora_lsl_synthetic.py"),
         "--speed", str(SPEED), "--stop-after", str(MOCK_STOP_AFTER)], cwd=HERE)
    time.sleep(2.0)
    try:
        # PFC_CHANNELS real (formato 'S{n}-D{n}'), sem subconjunto manual -
        # o mock sintetico ja' inclui esses pares literalmente.
        pfc_pairs = [tuple(p) for p in cfg.PFC_CHANNELS]
        checks = run_session(pfc_pairs)
    finally:
        if mock.poll() is None:
            mock.terminate()
        mock.wait(timeout=5)

    ok = all(checks)
    print("\nRESULTADO: %s" % ("APROVADO" if ok else "REPROVADO"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
