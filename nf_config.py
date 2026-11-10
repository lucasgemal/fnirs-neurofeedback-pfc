"""Parametros do pipeline de neurofeedback fNIRS (fase replay)."""

import os

# ---------------------------------------------------------------- modo seguro
REPLAY_MODE = True  # rotulo informativo (logs/UI); Acquisition ja conecta
                    # igual em replay ou ao vivo, resolve_byprop nao distingue

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NIRS_FILE = os.path.join(BASE_DIR, "2025-07-09_003.nirs")
HB_CACHE = os.path.join(BASE_DIR, "replay_hb.npz")
LOG_DIR = os.path.join(BASE_DIR, "logs")
RUN_DIR = os.path.join(BASE_DIR, "run")  # arquivos de estado/comando do painel <-> NFB

# ------------------------------------------------------------ stream (mock)
# PENDENCIA: nome real do Data Out do Aurora ainda nao confirmado.
STREAM_NAME = "Aurora"
STREAM_TYPE = "NIRS"
STREAM_SOURCE_ID = "mock_aurora_replay"
SERIAL_NUMBER = "MOCK-NSP2-0000"

# --------------------------------------------------- montagem / canais PFC
# Rotulos 10-20 do probeInfo (indices 1-based do .nirs).
SOURCE_LABELS = {1: "F3", 2: "AF7", 3: "AF3", 4: "Fz",
                 5: "P7", 6: "src6", 7: "CP5", 8: "T7"}
DETECTOR_LABELS = {1: "F5", 2: "F1", 3: "Fp1", 4: "TP7", 5: "P9",
                   6: "P5", 7: "C5", 8: "D08", 9: "D09", 10: "D10",
                   11: "D11", 12: "D12", 13: "D13", 14: "D14", 15: "D15"}

# Montagem real (whole-head 8/15, capturada no lab em 21/08/2026).
# Cluster frontal bilateral escolhido por geometria (fontes S1-S4 = Y alto/
# anterior; S5-S8 = Y baixo/posterior, ver metadata). Canais longos = feature
# de feedback; curtos = correcao de sinal sistemico (nao entram no feedback).
# PENDENCIA: escolha por geometria, nao confirmada anatomicamente contra
# desenho original da touca. Serve como pre-selecao default; selecao final
# e manual no painel apos "Detectar canais".
PFC_CHANNELS = [("S1", "D1"), ("S1", "D2"),
                ("S2", "D1"), ("S2", "D2"),
                ("S3", "D3"), ("S3", "D4"),
                ("S4", "D3"), ("S4", "D4")]

SHORT_CHANNELS_FRONTAL = [("S1", "D8"), ("S2", "D9"),
                          ("S3", "D10"), ("S4", "D11")]

# ------------------------------------------------------ Beer-Lambert (mBLL)
# Coeficientes de extincao molar (cm^-1 / M), tabela Prahl/Wray usada pelo
# Homer2 GetExtinctions e equivalente a usada pelo Aurora.
EXTINCTION = {760.0: (1486.5865, 3843.707),   # (HbO, HbR)
              850.0: (2526.391, 1798.643)}
DPF = {760.0: 6.0, 850.0: 6.0}
SHORT_CHANNEL_MAX_CM = 1.5  # pares mais curtos que isso = short channels

# ------------------------------------------------------------ processamento
BASELINE_S = 30.0        # repouso inicial usado para normalizar
FEATURE_WINDOW_S = 4.0   # janela deslizante da media de HbO
SMOOTH_TAU_S = 1.5       # constante de tempo do suavizador exponencial
NORM_CLIP = 3.0          # z-score saturado nesta amplitude
FAILSAFE_TIMEOUT_S = 1.0 # sem amostra valida por mais que isso -> failsafe
GLIDE_TAU_S = 2.0        # planeio suave em falha de sinal

# --------------------------------------------------------- eventos/markers
# Publicados por nfb_process.py no stream 'Trigger' (type=Markers) nas
# transicoes de fase - tanto para o Aurora (Trigger In escuta esse nome)
# quanto para o proprio painel resolver um stream real no SYNC.
TRIGGER_SOURCE_ID = "nfb_process_trigger"
MARKER_BASELINE_START = 1
MARKER_REGULATION_START = 2
MARKER_STOP = 3

# ------------------------------------------------------------- visualizacao
ALTITUDE_RANGE = (-0.75, 0.75)  # unidades de altura de tela (norm units)
PLANE_X_SPEED = 0.0             # movimento horizontal constante (0 = parado)
WINDOW_SIZE = (1280, 720)
FULLSCREEN = False
