"""IPC entre o painel de controle (tkinter) e a janela de neurofeedback
(PsychoPy) - dois processos separados (ver CLAUDE.md / decisao de arquitetura).

Mecanismo: arquivo de estado local em JSON, escrita atomica (tmp + os.replace),
lido por polling. Escolhido em vez de socket porque:
- no equipamento de laboratorio, sockets esbarram em firewall/antivirus e
  exigem gestao de porta/reconexao; arquivo local nao tem esse risco.
- e' trivialmente inspecionavel (abrir o .json em qualquer editor durante um
  piloto) e sobrevive a reinicio de qualquer um dos dois processos.
- comandos sao disparados por clique de botao (< 1 Hz); latencia de polling
  a 10-20 Hz e' imperceptivel para essa cadencia.
- mesma filosofia de robustez ja usada no failsafe da Camada 3: nunca confiar
  em uma leitura unica, sempre versionar (id incremental / timestamp) o que
  foi lido e tratar leitura corrompida/ausente como "sem novidade", nunca
  como erro fatal.
"""

import json
import os
import tempfile
import time

import nf_config as cfg

STATE_PATH = os.path.join(cfg.RUN_DIR, "nfb_state.json")
COMMAND_PATH = os.path.join(cfg.RUN_DIR, "nfb_command.json")


def _atomic_write(path, data):
    # Projeto vive dentro de uma pasta OneDrive: o cliente de sincronizacao
    # as vezes segura um lock breve no arquivo-alvo (WinError 5) bem na hora
    # do os.replace. Retry curto absorve isso sem mudar a semantica (ainda e'
    # atomico - so' tenta de novo se a troca falhar).
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        last_err = None
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as e:
                last_err = e
                time.sleep(0.02 * (attempt + 1))
        raise last_err
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None  # ausente/corrompido/em escrita: tratar como "sem novidade"


def write_state(state, path=STATE_PATH):
    state = dict(state)
    state["updated"] = time.time()
    _atomic_write(path, state)


def read_state(path=STATE_PATH):
    return _read_json(path)


def send_command(cmd_id, cmd, payload=None, path=COMMAND_PATH):
    """cmd_id deve ser um contador crescente mantido pelo chamador (painel) -
    evita reler o arquivo so para decidir o proximo id."""
    _atomic_write(path, dict(id=cmd_id, cmd=cmd, payload=payload or {}, ts=time.time()))


def read_command(path=COMMAND_PATH):
    return _read_json(path)


def reset(path_state=STATE_PATH, path_cmd=COMMAND_PATH):
    for p in (path_state, path_cmd):
        try:
            os.remove(p)
        except OSError:
            pass
