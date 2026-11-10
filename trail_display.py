"""Camada 4: explorador subindo trilha de montanha. Progresso = HbO normalizado.

Logica de trilha portada de INSTRUCOES_PERSONAGEM_TRILHA.md (pygame) para
PsychoPy. Waypoints normalizados (0-1, origem no canto superior esquerdo,
y para baixo) convertidos para o sistema de coordenadas norm do PsychoPy
(origem no centro, y para cima): x_pp = x*2-1 ; y_pp = 1-y*2.
"""

import os

from PIL import Image
from psychopy import visual, event

import nf_config as cfg

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
TRAIL_IMAGE = os.path.join(ASSETS_DIR, "trail_bg.png")
HIKER_IMAGE = os.path.join(ASSETS_DIR, "hiker_sprite.png")
HIKER_HEIGHT_NORM = 0.48  # 0.24 * altura da janela (altura da janela = 2 em norm)
SMOOTHING_SPEED = 1.2     # menor = resposta mais lenta e estavel

TRAIL_POINTS_NORMALIZED = [
    (0.16, 0.83),  # inicio, parte inferior esquerda
    (0.29, 0.75),  # primeiro trecho ascendente
    (0.43, 0.65),  # patamar central baixo
    (0.53, 0.52),  # patamar central alto
    (0.65, 0.39),  # trecho final da montanha
    (0.78, 0.26),  # mirante
]

TRAIL_POINTS = [(x * 2 - 1, 1 - y * 2) for x, y in TRAIL_POINTS_NORMALIZED]


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def position_on_trail(progress, points):
    """x, y norm para um progresso 0-1 ao longo da rota (interpolacao por segmento)."""
    progress = _clamp(progress)
    n_segments = len(points) - 1
    segment_position = progress * n_segments
    segment_index = min(int(segment_position), n_segments - 1)
    local_t = segment_position - segment_index
    x0, y0 = points[segment_index]
    x1, y1 = points[segment_index + 1]
    return (x0 + (x1 - x0) * local_t, y0 + (y1 - y0) * local_t)


def _aspect_size(path, height_norm):
    with Image.open(path) as im:
        w, h = im.size
    return (height_norm * w / h, height_norm)


class TrailDisplay(object):
    def __init__(self, win=None):
        self.win = win or visual.Window(size=cfg.WINDOW_SIZE, units="norm",
                                        fullscr=cfg.FULLSCREEN, color=(-1, -1, -1),
                                        allowGUI=True, winType="pyglet")
        self.background = visual.ImageStim(self.win, image=TRAIL_IMAGE,
                                           pos=(0, 0), size=(2, 2), units="norm")
        self.hiker = visual.ImageStim(self.win, image=HIKER_IMAGE, pos=(0, 0),
                                      size=_aspect_size(HIKER_IMAGE, HIKER_HEIGHT_NORM),
                                      units="norm", anchor="bottom-center")
        self.status = visual.TextStim(self.win, text="", pos=(-0.95, 0.92),
                                      height=0.05, color="white",
                                      alignText="left", anchorHoriz="left")
        self.warn = visual.TextStim(self.win, text="", pos=(0, -0.85),
                                    height=0.06, color="yellow")
        self.current_progress = 0.0

    def draw(self, altitude, snap, dt=0.0):
        """altitude: mesmo valor de saida da Camada 3 (unidades cfg.ALTITUDE_RANGE),
        reescalado aqui para progresso 0-1 na trilha. Interface identica ao
        antigo plane_display.PlaneDisplay.draw()."""
        lo, hi = cfg.ALTITUDE_RANGE
        feedback_target = _clamp((altitude - lo) / (hi - lo))
        self.current_progress += (feedback_target - self.current_progress) * min(
            1.0, SMOOTHING_SPEED * dt)

        x, y = position_on_trail(self.current_progress, TRAIL_POINTS)

        self.background.draw()
        self.hiker.pos = (x, y)
        self.hiker.draw()
        self.status.text = ("estado: %s   HbO(jan): %.3f uM   z: %+.2f   progresso: %.2f"
                            % (snap["state"], snap["windowed"],
                               snap["normalized"], self.current_progress))
        self.status.draw()
        self.warn.text = ("SINAL PERDIDO - mantendo posicao" if snap["state"] == "failsafe"
                          else ("baseline em curso" if snap["state"] == "baseline" else ""))
        self.warn.draw()
        self.win.flip()

    def should_quit(self):
        return "escape" in event.getKeys(keyList=["escape"])

    def close(self):
        try:
            self.win.close()
        except Exception:
            pass
