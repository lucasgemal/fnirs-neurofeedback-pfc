# Integração do Personagem à Trilha de Montanha no Pygame

**Autor:** Manus AI  
**Objetivo:** inserir o sprite do explorador sobre o cenário de montanha e deslocá-lo suavemente pelos patamares da trilha conforme o valor normalizado de HbO aumenta.

## 1. Arquivos necessários

Coloque os dois arquivos na mesma pasta do seu programa Python, ou atualize os caminhos no código.

| Arquivo | Papel no jogo |
|---|---|
| `trilha_montanha_neurofeedback.png` | Fundo 16:9 da tarefa, contendo a rota ascendente e o mirante. |
| `personagem_trilha_neurofeedback.png` | Sprite PNG do explorador, com transparência. |

> O personagem deve ser desenhado **depois** do cenário. Assim, ele permanece visível sobre a trilha e pode avançar sem modificar a imagem do plano de fundo.

## 2. Modelo de mapeamento HbO → progresso

O seu pipeline LSL/MNE-NIRS deve disponibilizar `feedback_value` como um valor contínuo entre `0.0` e `1.0`. Nesse caso, use esse valor como o progresso desejado: `0.0` mantém o explorador no início e `1.0` o leva ao mirante.

O desenho do jogo pode continuar em 60 FPS, enquanto o processamento fNIRS atualiza o `feedback_value` em frequência menor. O filtro de suavização abaixo evita deslocamentos bruscos e torna a relação entre a HbO e o avanço mais previsível.

| Faixa de `feedback_value` | Posição esperada |
|---:|---|
| `0.00` | Início da trilha, no canto inferior esquerdo. |
| `0.20–0.40` | Primeiro e segundo patamares. |
| `0.40–0.70` | Trecho central e platôs médios. |
| `0.70–1.00` | Trecho final e mirante. |

## 3. Carregamento dos assets

Após `pygame.init()` e a criação de `screen`, inclua o bloco abaixo. O uso de `convert_alpha()` preserva a transparência do PNG do personagem.

```python
# Dimensões da janela do jogo.
WIDTH, HEIGHT = 1280, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))

# Carregue e adapte o cenário à janela.
background_original = pygame.image.load(
    "trilha_montanha_neurofeedback.png"
).convert()
background = pygame.transform.smoothscale(background_original, (WIDTH, HEIGHT))

# Carregue o personagem preservando o canal alfa do PNG.
character_original = pygame.image.load(
    "personagem_trilha_neurofeedback.png"
).convert_alpha()

# Um tamanho moderado mantém os pés do personagem bem visíveis na trilha.
CHARACTER_HEIGHT = int(HEIGHT * 0.24)
CHARACTER_WIDTH = int(
    character_original.get_width() * CHARACTER_HEIGHT / character_original.get_height()
)
character = pygame.transform.smoothscale(
    character_original, (CHARACTER_WIDTH, CHARACTER_HEIGHT)
)
```

## 4. Definição da rota

A rota abaixo usa coordenadas **normalizadas** entre `0` e `1`. Isso permite que o mesmo caminho funcione se você alterar a resolução da janela, porque os pontos são recalculados a partir de `WIDTH` e `HEIGHT`.

Os pontos foram organizados da base ao mirante, acompanhando a trilha da imagem criada. Se você trocar o cenário futuramente, ajuste apenas a lista `TRAIL_POINTS_NORMALIZED`.

```python
# Pontos centrais dos patamares, do início até o mirante.
# Cada par e' (x_normalizado, y_normalizado).
TRAIL_POINTS_NORMALIZED = [
    (0.16, 0.83),  # inicio, parte inferior esquerda
    (0.29, 0.75),  # primeiro trecho ascendente
    (0.43, 0.65),  # patamar central baixo
    (0.53, 0.52),  # patamar central alto
    (0.65, 0.39),  # trecho final da montanha
    (0.78, 0.26),  # mirante
]

TRAIL_POINTS = [
    (int(x * WIDTH), int(y * HEIGHT))
    for x, y in TRAIL_POINTS_NORMALIZED
]
```

## 5. Funções de interpolação e suavização

Adicione estas funções antes do seu loop principal. A primeira calcula a posição do personagem ao longo de segmentos sucessivos; a segunda evita que pequenas oscilações na HbO produzam saltos visuais.

```python
def clamp(value, low=0.0, high=1.0):
    """Restringe um valor ao intervalo [low, high]."""
    return max(low, min(high, value))


def position_on_trail(progress, points):
    """Retorna x, y para um progresso normalizado ao longo da rota."""
    progress = clamp(progress)

    # Cada intervalo de progresso ocupa um segmento da rota.
    n_segments = len(points) - 1
    segment_position = progress * n_segments
    segment_index = min(int(segment_position), n_segments - 1)
    local_t = segment_position - segment_index

    x0, y0 = points[segment_index]
    x1, y1 = points[segment_index + 1]

    x = x0 + (x1 - x0) * local_t
    y = y0 + (y1 - y0) * local_t
    return x, y


# Estado de posição do personagem.
current_progress = 0.0
SMOOTHING_SPEED = 1.2  # menor = resposta mais lenta e estável
```

## 6. Atualização a cada quadro

No seu `while is_running:` ou `while running:`, obtenha o tempo transcorrido com `clock.tick(FPS) / 1000.0`. Em seguida, atualize `current_progress` a partir de `feedback_value`.

```python
# No inicio do jogo, use algo como:
clock = pygame.time.Clock()
FPS = 60

# Dentro do loop principal, uma vez por quadro:
dt = clock.tick(FPS) / 1000.0

# feedback_value deve vir do seu pipeline de neurofeedback e permanecer entre 0 e 1.
# Exemplo: feedback_value = 0.63
feedback_target = clamp(feedback_value)

# Suavizacao exponencial: o personagem se aproxima gradualmente da posicao-alvo.
current_progress += (
    feedback_target - current_progress
) * min(1.0, SMOOTHING_SPEED * dt)

character_x, character_y = position_on_trail(current_progress, TRAIL_POINTS)
```

## 7. Desenho do cenário e do personagem

Substitua o desenho do foguete, avião ou círculo do seu protótipo anterior pelo bloco abaixo. O ajuste em `sprite_rect.midbottom` faz os pés do explorador acompanharem a trilha, em vez de posicionar o centro do corpo sobre ela.

```python
# Desenhe primeiro o cenário.
screen.blit(background, (0, 0))

# Desenhe o explorador por cima da trilha.
sprite_rect = character.get_rect()
sprite_rect.midbottom = (int(character_x), int(character_y))
screen.blit(character, sprite_rect)

pygame.display.flip()
```

## 8. Bloco completo para substituir a lógica visual anterior

Este exemplo resume a integração essencial. Ele pressupõe que sua thread LSL/MNE-NIRS já atualiza `feedback_value` continuamente.

```python
import pygame

pygame.init()
WIDTH, HEIGHT = 1280, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Neurofeedback fNIRS — Trilha de Montanha")
clock = pygame.time.Clock()

background_original = pygame.image.load(
    "trilha_montanha_neurofeedback.png"
).convert()
background = pygame.transform.smoothscale(background_original, (WIDTH, HEIGHT))

character_original = pygame.image.load(
    "personagem_trilha_neurofeedback.png"
).convert_alpha()
character_height = int(HEIGHT * 0.24)
character_width = int(
    character_original.get_width() * character_height / character_original.get_height()
)
character = pygame.transform.smoothscale(
    character_original, (character_width, character_height)
)

TRAIL_POINTS = [
    (int(0.16 * WIDTH), int(0.83 * HEIGHT)),
    (int(0.29 * WIDTH), int(0.75 * HEIGHT)),
    (int(0.43 * WIDTH), int(0.65 * HEIGHT)),
    (int(0.53 * WIDTH), int(0.52 * HEIGHT)),
    (int(0.65 * WIDTH), int(0.39 * HEIGHT)),
    (int(0.78 * WIDTH), int(0.26 * HEIGHT)),
]


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def position_on_trail(progress, points):
    progress = clamp(progress)
    n_segments = len(points) - 1
    segment_position = progress * n_segments
    segment_index = min(int(segment_position), n_segments - 1)
    local_t = segment_position - segment_index
    x0, y0 = points[segment_index]
    x1, y1 = points[segment_index + 1]
    return (
        x0 + (x1 - x0) * local_t,
        y0 + (y1 - y0) * local_t,
    )


running = True
feedback_value = 0.0       # Sua thread LSL/MNE-NIRS deve alterar este valor.
current_progress = 0.0
SMOOTHING_SPEED = 1.2

while running:
    dt = clock.tick(60) / 1000.0

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # HbO normalizada controla o progresso na trilha.
    feedback_target = clamp(feedback_value)
    current_progress += (
        feedback_target - current_progress
    ) * min(1.0, SMOOTHING_SPEED * dt)

    character_x, character_y = position_on_trail(
        current_progress, TRAIL_POINTS
    )

    screen.blit(background, (0, 0))
    sprite_rect = character.get_rect()
    sprite_rect.midbottom = (int(character_x), int(character_y))
    screen.blit(character, sprite_rect)
    pygame.display.flip()

pygame.quit()
```

## 9. Ajustes recomendados

| Situação observada | Ajuste proposto |
|---|---|
| O personagem se move rápido demais. | Diminua `SMOOTHING_SPEED`, por exemplo para `0.5`. |
| O personagem demora demais para responder. | Aumente `SMOOTHING_SPEED`, por exemplo para `1.8`. |
| O personagem parece fora do caminho. | Ajuste o ponto correspondente em `TRAIL_POINTS_NORMALIZED`, especialmente a coordenada `y`. |
| O sprite parece grande ou pequeno. | Altere `CHARACTER_HEIGHT` de `0.24 * HEIGHT` para um valor entre `0.18` e `0.30 * HEIGHT`. |
| A HbO oscila excessivamente. | Aplique o filtro, a linha de base e a normalização no pipeline MNE-NIRS antes de atualizar `feedback_value`. Mantenha a suavização visual no jogo. |

## 10. Integração com seu pipeline de HbO

No seu script de aquisição LSL, a função que calcula o feedback deve terminar convertendo a métrica de HbO em um valor seguro de `0.0` a `1.0`. A variável compartilhada pelo jogo deve ser atualizada sem criar uma nova janela ou reiniciar o estado do personagem.

```python
# Exemplo dentro da thread que processa os dados fNIRS:
feedback_value = np.clip(normalized_hbo, 0.0, 1.0)
```

Dessa forma, uma HbO mais alta corresponde a um avanço ascendente na trilha; uma redução sustentada aproxima o personagem de patamares inferiores de maneira gradual. Para uma tarefa experimental, defina e registre antecipadamente a janela de linha de base, a transformação de normalização e os critérios de sucesso de cada bloco.

## Referência

[1] [Pygame Documentation — `Surface.convert_alpha`](https://www.pygame.org/docs/ref/surface.html#pygame.Surface.convert_alpha)
