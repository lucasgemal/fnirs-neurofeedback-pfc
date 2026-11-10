"""Processo A: painel de controle (tkinter), janela separada e flutuante -
pode ficar num monitor diferente da janela de neurofeedback (processo B,
nfb_process.py/PsychoPy). Comunicacao via session_ipc (arquivo de estado
local); ver session_ipc.py para a justificativa da escolha.

So fala LSL diretamente para a aba Configuracoes (listar canais via metadata)
- e' uma leitura independente do inlet que o processo B abre para a sessao de
verdade, o que e' suportado pelo LSL (varios inlets no mesmo outlet).
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from pylsl import StreamInlet, resolve_byprop

import nf_config as cfg
import session_ipc as ipc
from acquisition import StreamMap

POLL_MS = 300


class ControlPanel(object):
    def __init__(self, root):
        self.root = root
        root.title("Neurofeedback fNIRS - Painel de Controle")
        self.cmd_id = 0
        self.detect_queue = queue.Queue()
        self.channel_vars = {}  # "src-det" -> (tk.BooleanVar, pair tuple)
        self.last_state = None

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.tab_main = ttk.Frame(nb)
        self.tab_config = ttk.Frame(nb)
        nb.add(self.tab_main, text="Principal")
        nb.add(self.tab_config, text="Configuracoes")

        self._build_config_tab()
        self._build_main_tab()

        self.root.after(POLL_MS, self._poll_state)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------- config tab
    def _build_config_tab(self):
        f = self.tab_config

        row = ttk.Frame(f)
        row.pack(fill="x", padx=10, pady=6)
        ttk.Label(row, text="Nome do stream Data Out:").pack(side="left")
        self.stream_name_var = tk.StringVar(value=cfg.STREAM_NAME)
        ttk.Entry(row, textvariable=self.stream_name_var, width=20).pack(side="left", padx=6)
        ttk.Button(row, text="Detectar canais",
                   command=self._start_detect_channels).pack(side="left", padx=6)
        self.detect_status = ttk.Label(row, text="")
        self.detect_status.pack(side="left", padx=6)

        ttk.Label(f, text="Canais (par fonte-detector) no ROI de feedback:"
                  ).pack(anchor="w", padx=10, pady=(8, 0))
        self.channel_frame = ttk.Frame(f)
        self.channel_frame.pack(fill="x", padx=10, pady=4)
        self._populate_default_channels()

        row2 = ttk.Frame(f)
        row2.pack(fill="x", padx=10, pady=10)
        ttk.Label(row2, text="ID participante:").grid(row=0, column=0, sticky="w")
        self.participant_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.participant_var, width=16).grid(row=0, column=1, padx=6)
        ttk.Label(row2, text="Sessao:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.session_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.session_var, width=8).grid(row=0, column=3, padx=6)

        ttk.Button(f, text="Salvar configuracao",
                   command=self._save_config).pack(anchor="w", padx=10, pady=6)

    def _populate_default_channels(self, available_pairs=None):
        for w in self.channel_frame.winfo_children():
            w.destroy()
        self.channel_vars = {}
        default_pairs = [tuple(p) for p in cfg.PFC_CHANNELS]
        pairs = available_pairs if available_pairs is not None else default_pairs
        for i, pair in enumerate(pairs):
            key = "%s-%s" % pair
            var = tk.BooleanVar(value=(pair in default_pairs))
            cb = ttk.Checkbutton(self.channel_frame, text=key, variable=var)
            cb.grid(row=i // 4, column=i % 4, sticky="w", padx=4, pady=2)
            self.channel_vars[key] = (var, pair)

    def _start_detect_channels(self):
        self.detect_status.config(text="detectando...")
        name = self.stream_name_var.get().strip() or cfg.STREAM_NAME
        threading.Thread(target=self._detect_channels_worker, args=(name,),
                          daemon=True).start()
        self.root.after(200, self._drain_detect_queue)

    def _detect_channels_worker(self, name):
        try:
            streams = resolve_byprop("name", name, 1, 5.0)
            if not streams:
                self.detect_queue.put(("error", "stream '%s' nao encontrado" % name))
                return
            inlet = StreamInlet(streams[0], recover=False)
            smap = StreamMap(inlet.info(3.0))
            inlet.close_stream()
            pairs = [(c["source"], c["detector"]) for c in smap.channels if c["type"] == "HbO"]
            self.detect_queue.put(("ok", pairs))
        except Exception as e:
            self.detect_queue.put(("error", str(e)))

    def _drain_detect_queue(self):
        try:
            kind, payload = self.detect_queue.get_nowait()
        except queue.Empty:
            self.root.after(200, self._drain_detect_queue)
            return
        if kind == "error":
            self.detect_status.config(text="falha: %s" % payload)
        else:
            self.detect_status.config(text="%d canais HbO encontrados" % len(payload))
            self._populate_default_channels(available_pairs=payload)

    def _selected_pairs(self):
        return [pair for var, pair in self.channel_vars.values() if var.get()]

    def _save_config(self):
        payload = dict(
            participant_id=self.participant_var.get().strip(),
            session_id=self.session_var.get().strip(),
            stream_name=self.stream_name_var.get().strip() or cfg.STREAM_NAME,
            pairs=[list(p) for p in self._selected_pairs()],
        )
        self._send("CONFIGURE", payload)
        messagebox.showinfo("Configuracao", "Configuracao enviada ao processo de neurofeedback.")

    # ------------------------------------------------------------ main tab
    def _build_main_tab(self):
        f = self.tab_main

        self.phase_label = ttk.Label(f, text="fase: idle", font=("", 12, "bold"))
        self.phase_label.pack(anchor="w", padx=10, pady=(10, 4))

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=10, pady=6)
        self.btn_sync = ttk.Button(btns, text="Sincronizar", command=self._on_sync)
        self.btn_play = ttk.Button(btns, text="PLAY", command=self._on_play, state="disabled")
        self.btn_start_nfb = ttk.Button(btns, text="Iniciar NFB",
                                        command=self._on_start_nfb, state="disabled")
        self.btn_stop = ttk.Button(btns, text="STOP", command=self._on_stop, state="disabled")
        for b in (self.btn_sync, self.btn_play, self.btn_start_nfb, self.btn_stop):
            b.pack(side="left", padx=4)

        sync_frame = ttk.LabelFrame(f, text="Checagem de Sincronizacao")
        sync_frame.pack(fill="x", padx=10, pady=8)
        self.sync_labels = {}
        for i, key in enumerate(("trigger", "aurora", "channels")):
            lbl = ttk.Label(sync_frame, text="%s: -" % key)
            lbl.grid(row=i, column=0, sticky="w", padx=6, pady=2)
            self.sync_labels[key] = lbl

        self.quality_frame = ttk.LabelFrame(f, text="Qualidade de sinal por canal")
        self.quality_frame.pack(fill="x", padx=10, pady=8)
        self.quality_labels = {}

        self.failsafe_banner = tk.Label(f, text="", bg="#c0392b", fg="white",
                                        font=("", 11, "bold"))
        self.failsafe_banner.pack(fill="x", padx=10, pady=4)

        self.summary_text = tk.Text(f, height=6, width=70, state="disabled")
        self.summary_text.pack(fill="both", padx=10, pady=8, expand=True)

    def _send(self, cmd, payload=None):
        self.cmd_id += 1
        ipc.send_command(self.cmd_id, cmd, payload)

    def _on_sync(self):
        self._send("SYNC")

    def _on_play(self):
        self._send("PLAY")

    def _on_start_nfb(self):
        if messagebox.askyesno(
                "Confirmar",
                "Confirma o avanco do baseline para o bloco de regulacao?"):
            self._send("START_NFB")

    def _on_stop(self):
        self._send("STOP")

    def _on_close(self):
        self.root.destroy()

    # ------------------------------------------------------------- polling
    def _poll_state(self):
        state = ipc.read_state()
        if state is not None:
            self.last_state = state
            self._render_state(state)
        self.root.after(POLL_MS, self._poll_state)

    def _render_state(self, state):
        phase = state.get("phase", "idle")
        self.phase_label.config(text="fase: %s" % phase)

        self.btn_play.config(state=("normal" if phase == "synced" else "disabled"))
        self.btn_start_nfb.config(state=("normal" if phase == "baseline" else "disabled"))
        self.btn_stop.config(state=("normal" if phase not in ("idle", "stopped") else "disabled"))

        sync = state.get("sync")
        if sync:
            for key, lbl in self.sync_labels.items():
                info = sync.get(key)
                if info is None:
                    continue
                mark = "OK" if info["ok"] else "FALHA"
                lbl.config(text="%s: [%s] %s" % (key, mark, info.get("detail", "")),
                           foreground=("green" if info["ok"] else "red"))
            per_channel = (sync.get("channels") or {}).get("per_channel")
            if per_channel:
                for w in self.quality_frame.winfo_children():
                    w.destroy()
                for i, (label, q) in enumerate(sorted(per_channel.items())):
                    mark = "OK" if q["ok"] else "FALHA"
                    color = "green" if q["ok"] else "red"
                    txt = "%s: [%s] %.3f" % (label, mark, q.get("value", float("nan")))
                    ttk.Label(self.quality_frame, text=txt, foreground=color
                              ).grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=2)

        if state.get("failsafe_alert"):
            self.failsafe_banner.config(
                text="FAILSAFE FOI ATIVADO NESTA SESSAO - verificar sinal")
        else:
            self.failsafe_banner.config(text="")

        summary = state.get("last_summary")
        if summary:
            self._show_summary(summary)

    def _show_summary(self, summary):
        text = ("Sessao encerrada\n"
                "duracao: %.1fs\n"
                "amostras validas: %d | invalidas: %d\n"
                "failsafe ativado durante a sessao: %s\n"
                "log: %s\n" % (
                    summary.get("duration_s", 0.0),
                    summary.get("n_valid", 0), summary.get("n_invalid", 0),
                    "sim" if summary.get("failsafe_alert") else "nao",
                    summary.get("csv", "")))
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.config(state="disabled")


def main():
    # nao chama ipc.reset() aqui: quem "possui" o estado e' o processo B
    # (nfb_process.py), que reseta ao iniciar. Se o painel resetasse tambem,
    # o processo que abrir por ultimo apagaria comandos/estado do outro.
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
