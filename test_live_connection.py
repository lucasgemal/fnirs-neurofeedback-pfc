"""Exercita o caminho 'ao vivo' de Acquisition (item 1 do escopo): a trava
'RuntimeError se REPLAY_MODE=False' foi removida de acquisition.py porque
resolve_byprop("name", ...) nao distingue entre o mock local e o Aurora real -
e' o mesmo codigo nos dois casos, so muda quem publica o stream LSL.

Este teste nao tem hardware Aurora disponivel, mas exercita o mesmo caminho de
codigo que seria usado contra o Aurora real: resolve por nome, falha limpa
quando nao ha stream, conecta e mapeia canais quando ha. Roda com
cfg.REPLAY_MODE forcado a False para provar que Acquisition nao depende mais
dessa flag.
"""

import os
import subprocess
import sys
import time

import nf_config as cfg
from acquisition import Acquisition

HERE = os.path.dirname(os.path.abspath(__file__))


def check(name, ok, detail=""):
    print("[%s] %-45s %s" % ("OK  " if ok else "FALHA", name, detail))
    return ok


def test_absent_stream():
    """Sem nenhum publisher no ar: deve falhar limpo, nao travar, nao lancar
    excecao generica - RuntimeError com mensagem clara."""
    cfg.REPLAY_MODE = False
    try:
        Acquisition(stream_name="Stream_Que_Nao_Existe_%d" % int(time.time()), timeout=2.0)
    except RuntimeError as e:
        return check("ausencia de stream -> RuntimeError limpo", "nao encontrado" in str(e), str(e))
    except Exception as e:
        return check("ausencia de stream -> RuntimeError limpo", False,
                     "excecao inesperada: %r" % e)
    else:
        return check("ausencia de stream -> RuntimeError limpo", False, "nao levantou excecao")


def test_present_stream():
    """Com um publisher no ar (aqui, o mock - mas resolve_byprop("name", ...)
    e' identico ao que rodaria contra o Aurora real), REPLAY_MODE=False deve
    conectar normalmente e mapear os canais PFC pela metadata."""
    if not os.path.exists(cfg.HB_CACHE):
        subprocess.check_call([sys.executable, os.path.join(HERE, "nirs_to_hb.py")])

    mock = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "mock_aurora_lsl.py"),
         "--speed", "10", "--stop-after", "8"], cwd=HERE)
    time.sleep(2.0)
    cfg.REPLAY_MODE = False
    try:
        acq = Acquisition(timeout=5.0)
        sample = acq.pull(timeout=3.0)
        ok = check("presenca de stream + REPLAY_MODE=False -> conecta",
                    acq.map.n_channels > 0 and len(acq.pfc_cols) == len(cfg.PFC_CHANNELS),
                    "%d canais no stream, %d colunas PFC mapeadas"
                    % (acq.map.n_channels, len(acq.pfc_cols)))
        ok &= check("pull() retorna amostra valida", sample is not None,
                    "" if sample is None else "ts=%.3f" % sample[0])
        acq.close()
    finally:
        if mock.poll() is None:
            mock.terminate()
        mock.wait(timeout=5)
    return ok


def main():
    replay_before = cfg.REPLAY_MODE
    try:
        r1 = test_absent_stream()
        r2 = test_present_stream()
    finally:
        cfg.REPLAY_MODE = replay_before
    ok = r1 and r2
    print("\nRESULTADO: %s" % ("APROVADO" if ok else "REPROVADO"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
