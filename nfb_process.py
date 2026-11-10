"""Processo B: janela de neurofeedback (PsychoPy/trail_display), controlada
pelo painel de controle (processo A, tkinter) via session_ipc.

Fica com a janela PsychoPy e a thread de aquisicao LSL; nunca importa tkinter.
Maquina de estados por fase (self.phase), disparada por comandos do painel:

  idle -> (SYNC) -> synced -> (PLAY) -> baseline -> (START_NFB) -> regulation
                                   \-> (STOP, de qualquer fase) -> stopped

A logica de estado (sync/play/start_nfb/stop) fica isolada em NfbSession e nao
depende do TrailDisplay real - por isso pode ser testada com um display falso
(ver test_session_state_machine.py), sem precisar abrir janela/OpenGL.
"""

import time

from pylsl import StreamInfo, StreamInlet, StreamOutlet, local_clock, resolve_byprop

import nf_config as cfg
import session_ipc as ipc
from acquisition import Acquisition, StreamMap
from nf_logger import Logger
from processing import FeaturePipeline
from run_neurofeedback import SignalWorker

PLAUSIBLE_HBO_ABS_MAX = 200.0  # umol/L; so descarta leitura obviamente quebrada


class NfbSession(object):
    def __init__(self, display_factory=None):
        """display_factory: callable() -> objeto com draw(altitude, snap, dt),
        should_quit(), close(). Default = trail_display.TrailDisplay (import
        adiado para nao exigir PsychoPy/OpenGL em testes de logica pura)."""
        self.display_factory = display_factory
        self.disp = None

        self.phase = "idle"
        self.config = dict(participant_id="", session_id="",
                            stream_name=cfg.STREAM_NAME,
                            pairs=[list(p) for p in cfg.PFC_CHANNELS])
        self.sync_result = None
        self.acq = None
        self.pipeline = None
        self.log = None
        self.worker = None
        self.last_cmd_id = 0
        self.failsafe_alert = False
        self.session_started_wall = None
        self.last_summary = None

        self._idle_snap = dict(state="idle", windowed=float("nan"), normalized=0.0)
        self._idle_altitude = cfg.ALTITUDE_RANGE[0]

        # Publica markers de transicao de fase (baseline/regulacao/stop) desde
        # o inicio do processo - nao so em PLAY - para que o SYNC ja encontre
        # um stream 'Markers' real, sem depender de outro processo rodando em
        # paralelo. Papel de *publicacao*, independente do marker_inlet criado
        # em _do_play/SignalWorker (que so *escuta*, para uma fonte externa de
        # triggers - nao mexido aqui).
        info = StreamInfo("Trigger", "Markers", 1, 0, "int32", cfg.TRIGGER_SOURCE_ID)
        self.marker_outlet = StreamOutlet(info)
        self._pending_log_marker = ""

    # ------------------------------------------------------------ display
    def ensure_display(self):
        if self.disp is None:
            if self.display_factory is None:
                from trail_display import TrailDisplay
                self.display_factory = TrailDisplay
            self.disp = self.display_factory()

    # ----------------------------------------------------------- comandos
    def handle_command(self, cmd, payload):
        if cmd == "CONFIGURE":
            self.config.update(payload)
        elif cmd == "SYNC":
            self._do_sync()
        elif cmd == "PLAY":
            self._do_play()
        elif cmd == "START_NFB":
            self._do_start_nfb()
        elif cmd == "STOP":
            self._do_stop()

    def _emit_marker(self, code):
        """Publica no outlet 'Trigger' (Aurora Trigger In escuta esse nome) e
        deixa marcado para ser anexado a proxima linha do log em tick()."""
        try:
            self.marker_outlet.push_sample([int(code)])
        except Exception:
            pass
        self._pending_log_marker = str(code)

    def _do_sync(self):
        result = {}

        trig = resolve_byprop("type", "Markers", 1, 2.0)
        result["trigger"] = dict(
            ok=bool(trig),
            detail="stream de markers encontrado" if trig
            else "nenhum stream 'Markers' resolvido em 2s")

        pairs = [tuple(p) for p in self.config["pairs"]]
        aur = resolve_byprop("name", self.config["stream_name"], 1, 3.0)
        if not aur:
            result["aurora"] = dict(ok=False, detail="stream '%s' nao encontrado em 3s"
                                     % self.config["stream_name"])
            result["channels"] = dict(ok=False, detail="sem stream, nao verificado")
        else:
            inlet = StreamInlet(aur[0], recover=False)
            smap = StreamMap(inlet.info(2.0))
            sample, _ts = inlet.pull_sample(timeout=3.0)
            if sample is None:
                result["aurora"] = dict(ok=False,
                                         detail="stream resolvido mas sem amostras em 3s")
                result["channels"] = dict(ok=False, detail="sem amostra, nao verificado")
            else:
                result["aurora"] = dict(ok=True, detail="%d canais, %.1f Hz"
                                         % (smap.n_channels, smap.sfreq))
                if not pairs:
                    result["channels"] = dict(
                        ok=False, detail="nenhum canal selecionado no ROI")
                else:
                    try:
                        cols = smap.pfc_hbo_columns(pairs)
                        quality = {}
                        for (src, det), col in zip(pairs, cols):
                            val = float(sample[col])
                            ok = val == val and abs(val) < PLAUSIBLE_HBO_ABS_MAX
                            quality["%s-%s" % (src, det)] = dict(ok=ok, value=val)
                        result["channels"] = dict(
                            ok=all(q["ok"] for q in quality.values()),
                            detail="%d/%d canais presentes" % (len(cols), len(pairs)),
                            per_channel=quality)
                    except RuntimeError as e:
                        result["channels"] = dict(ok=False, detail=str(e))
            inlet.close_stream()

        self.sync_result = result
        self.phase = "synced" if all(v["ok"] for v in result.values()) else "idle"

    def _do_play(self):
        if self.phase != "synced":
            return
        pairs = [tuple(p) for p in self.config["pairs"]]
        self.acq = Acquisition(stream_name=self.config["stream_name"], pairs=pairs)
        self.pipeline = FeaturePipeline(manual_gate=True)

        marker_inlet = None
        found = resolve_byprop("type", "Markers", 1, 1.0)
        if found:
            marker_inlet = StreamInlet(found[0], recover=False)

        meta = dict(
            replay_mode=cfg.REPLAY_MODE,
            participant_id=self.config["participant_id"],
            session_id=self.config["session_id"],
            stream_name=self.acq.map.name,
            stream_sfreq=self.acq.map.sfreq,
            n_stream_channels=self.acq.map.n_channels,
            pfc_pairs=[list(p) for p in pairs],
            pfc_hbo_columns=self.acq.pfc_cols,
            pfc_labels=[self.acq.map.channels[i]["label"] for i in self.acq.pfc_cols],
            params=dict(baseline_s=cfg.BASELINE_S, window_s=cfg.FEATURE_WINDOW_S,
                        smooth_tau_s=cfg.SMOOTH_TAU_S, clip=cfg.NORM_CLIP,
                        failsafe_timeout_s=cfg.FAILSAFE_TIMEOUT_S,
                        glide_tau_s=cfg.GLIDE_TAU_S),
            started=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        prefix = "session_%s_%s" % (self.config["participant_id"] or "anon",
                                     self.config["session_id"] or "0")
        self.log = Logger(prefix=prefix, meta=meta)
        self.worker = SignalWorker(self.acq, self.pipeline, marker_inlet)
        self.worker.start()

        self.phase = "baseline"
        self.failsafe_alert = False
        self.last_summary = None
        self.session_started_wall = local_clock()
        self._emit_marker(cfg.MARKER_BASELINE_START)

    def _do_start_nfb(self):
        if self.phase == "baseline" and self.pipeline is not None:
            self.pipeline.begin_regulation()
            self.phase = "regulation"
            self._emit_marker(cfg.MARKER_REGULATION_START)

    def _do_stop(self):
        self._emit_marker(cfg.MARKER_STOP)
        if self.worker is not None:
            self.worker.stop()
            self.worker.join(timeout=1.0)
        if self.acq is not None:
            self.acq.close()
        if self.log is not None:
            self.last_summary = dict(
                rows=self.log.n_rows, csv=self.log.csv_path, meta=self.log.meta_path,
                duration_s=(local_clock() - self.session_started_wall)
                if self.session_started_wall else 0.0,
                n_valid=self.acq.n_valid if self.acq else 0,
                n_invalid=self.acq.n_invalid if self.acq else 0,
                failsafe_alert=self.failsafe_alert)
            self.log.close()
        self.acq = self.pipeline = self.log = self.worker = None
        self.phase = "stopped"

    # -------------------------------------------------------------- loop
    def tick(self, now, dt):
        """Um passo do loop principal: atualiza pipeline/log/display, publica
        estado. Separado de run_forever() para ser testavel sem sleep real."""
        altitude, snap = self._idle_altitude, self._idle_snap
        if self.pipeline is not None and self.worker is not None:
            with self.worker.lock:
                altitude = self.pipeline.update_display(now)
                snap = self.pipeline.snapshot()
                lsl_ts, dev_ts = self.worker.last_lsl_ts, self.worker.last_device_ts
            if snap["state"] == "failsafe":
                self.failsafe_alert = True
            if self.log is not None:
                valid = snap["state"] != "failsafe"
                self.log.write(lsl_ts, dev_ts, snap, valid,
                                self.acq.n_valid, self.acq.n_invalid,
                                marker=self._pending_log_marker)
                self._pending_log_marker = ""
        if self.disp is not None:
            self.disp.draw(altitude, snap, dt)
        self._publish_state()

    def _publish_state(self):
        state = dict(phase=self.phase, sync=self.sync_result, config=self.config,
                     failsafe_alert=self.failsafe_alert, last_summary=self.last_summary)
        if self.pipeline is not None:
            state["snapshot"] = self.pipeline.snapshot()
        if self.acq is not None:
            state["n_valid"] = self.acq.n_valid
            state["n_invalid"] = self.acq.n_invalid
        ipc.write_state(state)

    def run_forever(self, poll_hz=30.0):
        self.ensure_display()
        prev = local_clock()
        period = 1.0 / poll_hz
        while True:
            cmdobj = ipc.read_command()
            if cmdobj and cmdobj.get("id", 0) > self.last_cmd_id:
                self.last_cmd_id = cmdobj["id"]
                self.handle_command(cmdobj["cmd"], cmdobj.get("payload", {}))
            now = local_clock()
            dt = now - prev
            prev = now
            self.tick(now, dt)
            if self.disp.should_quit():
                self._do_stop()
                self._publish_state()
                break
            time.sleep(max(0.0, period - (local_clock() - now)))
        self.disp.close()


if __name__ == "__main__":
    ipc.reset()
    NfbSession().run_forever()
