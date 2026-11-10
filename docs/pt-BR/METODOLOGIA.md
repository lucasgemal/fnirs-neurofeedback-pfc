---
title: "Sistema de neurofeedback fNIRS em tempo real — Metodologia"
lang: pt-BR
---

# Sistema de neurofeedback fNIRS em tempo real — Metodologia

Ferramenta de pesquisa para neurofeedback em tempo real com fNIRS (NIRSport2 + Aurora), apresentação em PsychoPy.

Este texto descreve o sistema como protocolo reprodutível, no estilo de uma seção de Métodos. O que o código não permite afirmar está marcado como "a confirmar". Referências bibliográficas não foram incluídas: onde caberia citação consta `[REF: tema]`.

## 1. Equipamento e software

**Aquisição.** Sistema fNIRS contínuo NIRSport2 (NIRx) operado pelo software Aurora fNIRS (versão do manual consultado: 2025.2.5). Taxa de amostragem do stream: ≈ 10,2 Hz (valor documentado para o Aurora; o valor exato é lido da metadata do stream em cada sessão e gravado no arquivo de metadados). Comprimentos de onda: 760 e 850 nm. O Aurora disponibiliza os dados em tempo real por Lab Streaming Layer (LSL) no stream "Data Out" (nome configurado: `Aurora`) e recebe marcadores no stream "Trigger In" (nome: `Trigger`) `[REF: LSL]`.

**Software.** Python embutido na distribuição Standalone do PsychoPy (versões validadas: PsychoPy 2022.13 com Python 3.8.10 e PsychoPy 2026.1.3 com Python 3.10.11), `pylsl` (liblsl 1.15.0 e 1.17.4 nos dois ambientes), `numpy`, `Pillow`, `tkinter` (painel de controle). A apresentação visual usa PsychoPy `[REF: PsychoPy]`. O sistema é composto por dois processos (painel de controle e janela de neurofeedback) que se comunicam por arquivo JSON local; o código-fonte e a documentação técnica acompanham este texto (`DOCUMENTACAO_TECNICA.md`).

A arquitetura modular (separação entre aquisição, processamento e visualização) foi inspirada em um sistema de neurofeedback EEG de referência; nenhum código ou método de processamento de EEG foi reutilizado `[REF: neurofeedback EEG]`.

## 2. Montagem e seleção do ROI

A montagem registrada na metadata do Aurora tem 8 fontes, 15 detectores e 24 pares fonte-detector (16 canais de distância longa e 8 de distância curta). As posições dos optodos foram definidas no Aurora/NIRSite (posições anatômicas 10-20 do experimento: a confirmar com o desenho da touca).

O ROI de feedback é um conjunto de pares fonte-detector **selecionado manualmente no painel de controle**, por checkboxes, após a detecção dos canais HbO presentes no stream. A pré-seleção padrão (`PFC_CHANNELS`) contém 8 canais longos do cluster frontal bilateral: S1-D1, S1-D2, S2-D1, S2-D2, S3-D3, S3-D4, S4-D3, S4-D4. **O cluster frontal S1–S4 foi escolhido pela geometria das coordenadas dos optodos (fontes S1–S4 com posição mais anterior; S5–S8 mais posterior) e não foi confirmado anatomicamente** contra o desenho original da touca; a correspondência com os rótulos 10-20 (AF7, AF3, AF4, AF8 para as fontes e Fp1, F5, Fp2, F6 para os detectores, segundo o planejamento do projeto) permanece a confirmar. O PFC bilateral é tratado como região única (média dos canais; sem lateralização). Os canais de distância curta não entram na feature de feedback, e nenhuma regressão de sinal sistêmico é implementada no pipeline.

## 3. Obtenção do sinal

A concentração de hemoglobina oxigenada (HbO, µmol/L) é a fornecida pelo Aurora no stream de dados, calculada pelo próprio software a partir da densidade óptica com a Lei de Beer-Lambert modificada e coeficientes fixos do Aurora (não configuráveis) `[REF: Beer-Lambert modificada]`. **O pipeline não reprocessa o sinal óptico**: não há conversão, filtragem passa-banda, correção de artefato de movimento ou correção de canais curtos no código de tempo real. As colunas de HbO são localizadas dinamicamente pela metadata do stream (tipo `nirs_hbo` e nome `S{n}-D{n}`), nunca por índice fixo. Amostras com valor não finito (NaN/Inf) em qualquer canal do ROI são descartadas e contadas, e nunca substituem a última amostra válida.

## 4. Cálculo da feature

Seja *x(t)* a média de HbO dos canais do ROI (por amostra). O cálculo é, em ordem:

1. **Janela deslizante:** média de *x* sobre as amostras dos últimos `FEATURE_WINDOW_S` = 4,0 s (tempo do dispositivo, coluna de frame/timestamp do stream; unidade a confirmar, ver seção 9) → *w(t)*.
2. **Baseline:** durante os primeiros `BASELINE_S` = 30,0 s de dados desde a primeira amostra, os valores *x* são acumulados; ao final calcula-se a média *μ* e o desvio-padrão amostral *σ* (ddof = 1; piso de 10⁻⁹) do baseline. O pipeline então aguarda confirmação manual do avanço (seção 7); durante essa espera e durante o baseline a saída do feedback é mantida em z = 0.
3. **Normalização (z-score):** *z(t) = (w(t) − μ) / σ*. Observação: *σ* é o desvio dos valores por amostra do baseline, enquanto *w* é uma média em janela; portanto *z* não é um z-score de uma variável com a mesma variância.
4. **Saturação:** *z* é limitado a [−`NORM_CLIP`, +`NORM_CLIP`] = [−3, +3].
5. **Suavização:** média móvel exponencial com constante de tempo `SMOOTH_TAU_S` = 1,5 s, aplicada no relógio de exibição (não por amostra): *s ← s + (1 − e^(−Δt/τ))·(z − s)*.

O valor resultante é convertido internamente para uma "altitude" na faixa (−0,75, 0,75) (nome herdado de uma metáfora visual anterior), por mapeamento linear de *s* ∈ [−3, 3].

## 5. Mapeamento da feature para o feedback visual

A janela de neurofeedback mostra um explorador (sprite) sobre uma trilha de montanha (imagem de fundo fixa). A altitude é reescalada linearmente para um **progresso *p* ∈ [0, 1]** — *p = (s + 3)/6* — de modo que *z* = 0 (nível do baseline) corresponde a *p* = 0,5 (meio da trilha), *z* ≥ +3 ao final da trilha e *z* ≤ −3 ao início. O progresso exibido segue o alvo com uma segunda suavização exponencial no desenho (taxa `SMOOTHING_SPEED` = 1,2 s⁻¹, ou seja, τ ≈ 0,83 s). A posição do sprite é obtida por interpolação linear ao longo de 6 waypoints fixos, com o sprite ancorado pelos pés. O mapeamento é contínuo e direto: sem limiares, sem recompensa discreta. Uma linha de texto na tela exibe estado, HbO da janela, *z* e progresso (para uso do pesquisador; a decisão de exibi-la ao participante é a confirmar). O sentido do feedback (aumento de HbO → avanço na trilha) é fixo no código.

## 6. Tratamento de perda de sinal (failsafe)

Se, após o baseline, não chegar amostra válida por mais de `FAILSAFE_TIMEOUT_S` = 1,0 s (relógio de parede), o estado passa a "failsafe": a suavização é congelada, a trilha mantém a última posição válida (sem recuo para o início; ajuste suave com constante `GLIDE_TAU_S` = 2,0 s) e a tela exibe o aviso "SINAL PERDIDO - mantendo posicao". Quando amostras válidas retornam, a operação normal é retomada sem salto. O painel exibe um alerta persistente caso o failsafe tenha sido acionado na sessão e o resumo informa as contagens de amostras válidas e inválidas. Durante o baseline não há failsafe: se o sinal for interrompido, o baseline apenas não avança.

## 7. Protocolo da sessão

1. **Configuração (painel):** nome do stream, detecção dos canais, seleção do ROI, ID do participante e número da sessão; o painel envia a configuração ao processo de neurofeedback.
2. **Sincronização:** o sistema verifica (i) a existência de um stream de marcadores (`Trigger`, publicado pelo próprio processo de neurofeedback), (ii) a existência do stream de dados e o recebimento de uma amostra em até 3 s, e (iii) a presença de todos os canais do ROI, com checagem simplificada de plausibilidade (valor não-NaN e |valor| < 200 µmol/L, em uma única amostra por canal). Os três indicadores devem estar OK para liberar o início. Com o Aurora, a gravação (Record) precisa estar ativa para o fluxo de amostras.
3. **PLAY — baseline:** inicia a aquisição, o log e o cálculo do baseline de 30 s; marcador `1` enviado ao stream `Trigger`. A trilha permanece no ponto médio. Condição do baseline (olhos abertos com fixação, instrução ao participante): **a confirmar** (foi apenas uma recomendação, não imposta pelo código).
4. **Avanço manual:** ao concluir o baseline, o pipeline entra em "baseline_ready" e a trilha permanece parada. O pesquisador aciona "Iniciar NFB" e confirma o diálogo; marcador `2` (início da regulação). Pelo código, o botão está habilitado durante todo o baseline, não apenas após seu término; a aplicação do procedimento correto (acionar somente após "baseline_ready") depende do operador.
5. **Regulação:** o feedback evolui conforme a seção 4–5, sem duração fixa programada (a duração do bloco é definida pelo operador; duração da fase de recuperação ("recovery") do desenho original: a confirmar, não implementada como fase).
6. **STOP:** marcador `3`, encerramento da aquisição, fechamento do log e exibição do resumo. A tecla Esc na janela de neurofeedback também encerra a sessão.

**Dados registrados.** Para cada sessão: (a) CSV com uma linha por ciclo de atualização (≈ 30 Hz), contendo carimbo de tempo de parede (ISO e Unix), tempo LSL e tempo do dispositivo da última amostra, estado do pipeline, HbO médio do ROI, média em janela, z-score, valor suavizado, altitude, indicador de validade, contadores de amostras válidas/inválidas e o marcador emitido na linha; (b) JSON de metadados com modo (replay/ao vivo, rótulo informativo), ID do participante e da sessão, nome e taxa do stream, número de canais, pares e colunas do ROI, rótulos dos canais e parâmetros de processamento; (c) marcadores `1`, `2`, `3` enviados ao Aurora (Trigger In), que permitem reconciliar o log com o arquivo de eventos do Aurora (`*_lsl.tri`) pelos tempos LSL/dispositivo (procedimento de reconciliação: a confirmar). Valor de fallback do Aurora para trigger inválido: 12 (conforme configuração informada).

## 8. Validação realizada

A validação limitou-se a **testes de engenharia** com mock/dado sintético e às **primeiras sessões de teste** no equipamento:

- Fase de replay (stream simulado a partir de dados de outra tarefa, com montagem whole-head): critérios de aceitação 9/9 — mapeamento do ROI pela metadata, baseline, progresso contínuo, ausência de saltos, failsafe, planeio sem queda, não recuo, log consistente e markers; taxa de quadros ≈ 59 fps na confirmação visual.
- Testes automatizados com stream sintético no schema real do Aurora (máquina de estados da sessão, IPC, interpretação da metadata, detecção de canais, publicação de markers).
- Primeiras sessões de teste com o Aurora real: sincronização com os três indicadores OK e sessões concluídas. Nenhum desempenho de neurofeedback, efeito de aprendizado ou validade fisiológica do sinal de feedback foi avaliado. O dado sintético não é fisiológico.
- Os testes `test_acceptance.py` e `test_live_connection.py` não são aplicáveis à montagem real (dataset incompatível).

## 9. Parâmetros ainda não calibrados e decisões pendentes

| Item | Situação atual | Pendência |
|---|---|---|
| Janela da feature (`FEATURE_WINDOW_S`) | 4,0 s, valor inicial | Definir em piloto real |
| Suavização (`SMOOTH_TAU_S`; `SMOOTHING_SPEED` no desenho; `GLIDE_TAU_S`) | 1,5 s; 1,2 s⁻¹; 2,0 s, valores iniciais; suavização em dois estágios | Definir em piloto real; decidir se manter dois estágios |
| Saturação (`NORM_CLIP`) | 3,0; saturação do z-score observada em teste com deriva lenta | Reavaliar com dado real antes de qualquer coleta |
| Duração do baseline (`BASELINE_S`) | 30 s (planejamento previa 30–60 s) | A confirmar |
| Condição do baseline | Olhos abertos com fixação: apenas recomendação | A confirmar |
| Qualidade de sinal | Verificação simplificada (|valor| < 200 µmol/L e não-NaN, uma amostra, só no SYNC); sem SNR | Considerar indicador de qualidade nativo do Aurora, se existir na metadata, e monitoramento contínuo |
| ROI | Cluster S1–S4 por geometria, seleção manual | Confirmar anatomicamente contra o desenho da touca |
| Eixo de tempo | Coluna `nirs_frame` tratada como segundos | Confirmar com sessão real (se for contador de quadros, janela e baseline ficam em unidades de amostras) |
| Pré-processamento do sinal | Nenhum além do fornecido pelo Aurora; sem correção de canais curtos nem de movimento | Decidir se necessário `[REF: correção de sinal sistêmico / movimento em fNIRS]` |
| Normalização | σ do baseline por amostra aplicado à média em janela | Decidir se mantém |
| Fase de recuperação ("recovery") e duração do bloco de regulação | Não implementadas como fases | A confirmar |
| Reconciliação com `*_lsl.tri` | Possível pelos tempos e markers registrados | Procedimento a confirmar |
| Sentido do feedback e exibição do texto de estado ao participante | Fixos no código | A confirmar |

## 10. Latência e throughput do sistema

Rótulos de origem: **[Aurora]** informado pelo Aurora (metadata do stream ou manual); **[código]** derivado do código/config, com a conta mostrada; **[medido]** medido nesta tarefa, na máquina de desenvolvimento (não a do laboratório); **[a confirmar]** sem dado, sem estimativa.

**Máquina das medições [medido]:** PC de desenvolvimento, Windows 10 Pro (10.0.19045), CPU AMD64 Family 23 (16 processadores lógicos), Python 3.8.10 do PsychoPy 2022.13, `pylsl` 1.15.0 / liblsl 1.15.0, contra `mock_aurora_lsl_synthetic.py` em loopback (mesma máquina), sem hardware Aurora e sem janela PsychoPy. Os resultados **não** se transferem para a máquina do laboratório nem para o PsychoPy 2026.1.3 sem nova medição.

### Informações reportadas pelo Aurora

| Item | Valor | Origem | Observação |
|---|---|---|---|
| Taxa nominal | ≈ 10,17 Hz | [Aurora] | Informado a partir da metadata capturada em campo. No repositório aparece como `SFREQ = 10.17` em `mock_aurora_lsl_synthetic.py` (comentário: "cadência documentada") e como ≈ 10,2 Hz no `CLAUDE.md`. O valor exato é lido de `info.nominal_srate()` a cada sessão e gravado em `stream_sfreq` no `*_meta.json` |
| `steps_per_frame` | 8 | [Aurora] | Informado pelo pesquisador (metadata de campo). Não consta em nenhum arquivo da pasta e não é usado pelo código. Significado exato: [a confirmar] |
| Nº de colunas do stream | 97 | [Aurora] | 1 frame + 24 canais × (raw760, raw850, HbO, HbR) = 1 + 96. Corroborado por `test_real_schema.py` e pelo mock sintético (`N_OUT = 4×24+1`) |
| Formato dos dados | float32 | [Aurora] | Informado pelo pesquisador; os mocks publicam `double64`. Não verificado no código |
| Hardware, versão do Aurora, `ntrigger_inputs` | — | [a confirmar] | Valores não disponíveis na pasta |
| Fallback de trigger | 12 | [Aurora] | Informado no `CLAUDE.md` (tela LSL Stream Names do Aurora) |
| Latência de saída do stream | — | [a confirmar] | O manual PDF do Aurora e o script `diagnostico_metadata.py` não estão na pasta; nenhuma latência interna do Aurora foi deduzida |

### Throughput

| Grandeza | Valor | Origem | Conta / observação |
|---|---|---|---|
| Período de amostragem | 98,3 ms | [código] | 1 / 10,17 Hz |
| Amostras/s do stream | 10,17 | [Aurora] | taxa nominal |
| Valores/s do stream completo | ≈ 986 | [código] | 97 colunas × 10,17 |
| Valores/s usados pelo pipeline | ≈ 81 | [código] | 8 colunas HbO do ROI × 10,17. A amostra completa (97 valores) é recebida e convertida em array; só as colunas do ROI entram em `add_sample` |
| Amostras novas por quadro de tela | ≈ 0,17 | [código] | 10,17 / 60 fps, ou seja, uma amostra nova a cada ≈ 5,9 quadros |
| Linhas de log por segundo (`nfb_process.py`) | ≈ 30 (alvo) | [código] | uma linha por `tick`; laço com `poll_hz = 30`. Em um log de mock (123 linhas em ≈ 3,6 s) observaram-se ≈ 34 linhas/s [medido nos logs existentes]; taxa em sessão de laboratório: [a confirmar] |
| Linhas de log por segundo (`run_neurofeedback.py`) | ≈ taxa de quadros (≈ 60) | [código] | uma linha por iteração; sem display, `fps = 60` |
| Limite de `drain` por ciclo | 64 amostras | [código] | `SignalWorker`: `drain(max_samples=64, timeout=0.05)`; muito acima de 10,17 amostras/s |
| Buffer do inlet | 60 s | [código] | `StreamInlet(max_buflen=60)` |
| Taxa do laço principal (`nfb_process.py`) | 30 Hz | [código] | `run_forever(poll_hz=30)`; o `flip` do PsychoPy pode limitar à taxa do monitor; taxa real: [a confirmar] |
| Polling do painel | 300 ms | [código] | `POLL_MS = 300` (leitura de `nfb_state.json`) |

### Orçamento de latência por etapa (da chegada da amostra ao pixel)

| Etapa | Valor | Origem | Observação |
|---|---|---|---|
| Período de amostragem do Aurora | 98,3 ms | [código] | 1 / 10,17 Hz; um evento só aparece na próxima amostra (0–98 ms, média ≈ 49 ms). Se cada amostra é média sobre o intervalo: [a confirmar] |
| Latência interna do Aurora (aquisição → saída LSL) | — | [a confirmar] | sem dado |
| Transporte LSL (mock em loopback) | média 1,15 ms; DP 0,47 ms; p95 1,80 ms; máx. 5,60 ms (n = 306) | [medido] | `local_clock()` no recebimento − timestamp LSL da amostra. O timestamp é o instante agendado pelo mock, então inclui o jitter do agendamento do mock. **Não** representa o ambiente do laboratório nem o Aurora real (transporte real: [a confirmar]) |
| Processamento por amostra | `add_sample`: média 0,054 ms (p95 0,059; máx. 0,161). `update_display` + `snapshot`: média 0,011 ms (máx. 0,085). `Logger.write`: média 0,040 ms (máx. 0,193) | [medido] | n = 306 amostras em 30 s; log gravado em pasta temporária local, não na pasta do projeto (OneDrive). Custo do IPC (`write_state`, ≈ 30×/s, em pasta OneDrive) e do desenho PsychoPy: [a confirmar] |
| Coleta pelo `SignalWorker` | ≈ imediata após a chegada | [código] | `pull_sample(timeout=0.05)` bloqueia e retorna assim que há amostra; o timeout só limita a espera sem dado (não é polling cego de 50 ms). Atraso incluído na linha do transporte |
| Laço principal lê o estado | 0–33 ms (média ≈ 17 ms) | [código] | `poll_hz = 30`: o `tick` usa o estado do pipeline na iteração seguinte |
| Janela deslizante (média simples) | atraso de grupo ≈ 1,97 s (≈ `FEATURE_WINDOW_S`/2) | [código] | `np.mean` sobre as amostras com `t − t_mais_antiga ≤ 4,0 s`: N = ⌊4,0 × 10,17⌋ + 1 = 41 amostras. Média simples (boxcar) tem atraso de grupo (N−1)/2 = 20 amostras = 20 / 10,17 ≈ 1,97 s. Resposta a degrau: rampa de 0 a 100% em 4,0 s (50% em ≈ 2,0 s) |
| Suavização exponencial (`SMOOTH_TAU_S` = 1,5 s) | 63% em 1,5 s; 95% em ≈ 4,5 s (3τ) | [código] | 1 − e^(−t/τ); atraso de grupo em baixa frequência ≈ τ = 1,5 s. Atualizada a cada `tick` com `dt` real (independe da taxa) |
| Suavização do progresso no `trail_display` (`SMOOTHING_SPEED` = 1,2) | τ ≈ 0,83 s: 63% em ≈ 0,83 s; 95% em ≈ 2,5 s | [código] | `progresso += (alvo − progresso) × min(1, 1,2 × dt)` → τ ≈ 1 / 1,2 s⁻¹ (aproximação válida para 1,2·dt ≪ 1) |
| Período de quadro / `flip` | ≈ 16,7 ms a 60 Hz | [código] | `win.flip()` em `TrailDisplay.draw`. ≈ 59,3 fps foi registrado em teste anterior (`CLAUDE.md`); latência do monitor/SO: [a confirmar] |
| Timeout do failsafe (`FAILSAFE_TIMEOUT_S`) | 1,0 s (+ até 33 ms do laço) | [código] | ≈ 10 períodos de amostragem sem amostra válida (relógio de parede) |
| Resposta hemodinâmica | — | [a confirmar] | Atraso fisiológico da ordem de segundos, fora do controle do sistema: [REF: hemodynamic response latency] |

**Estimativa do atraso determinístico do pipeline (chegada da amostra ao pixel), somente itens [código]/[medido]:** os três filtros em cascata somam atrasos de grupo (aproximação para sinais lentos): 1,97 s (janela) + 1,5 s (EMA) + ≈ 0,83 s (progresso na trilha) ≈ **4,3 s**, mais um termo fixo ≤ ≈ 0,05 s (≈ 1 ms de transporte/coleta [medido], até 33 ms do laço e até 17 ms de quadro). É um atraso de grupo (centróide da resposta ao impulso), não o tempo para refletir 100% de uma mudança: a janela leva 4,0 s para refletir um degrau por completo e a EMA e a suavização do desenho têm cauda exponencial. O z-score e a saturação (±`NORM_CLIP`) não adicionam atraso, mas a saturação trunca excursões.

**Fica de fora da estimativa:** latência interna do Aurora e do hardware, transporte LSL no ambiente real, quantização pelo período de amostragem (0–98 ms), custo do desenho PsychoPy e do IPC, latência do monitor e a resposta hemodinâmica ([REF: hemodynamic response latency]).

### Medição auxiliar nos logs existentes (agregada)

[medido, logs em `logs/`, apenas estatísticas agregadas] Nos 6 logs de mock em velocidade 1× (≈ 15,4 mil linhas), a diferença `lsl_time − device_time` é um deslocamento entre dois relógios arbitrários (relógio LSL × tempo do dispositivo), não uma latência; o que importa é sua estabilidade. Em torno da média de cada log: DP agregado = 0,84 s e desvio máximo = 16,7 s; a faixa (máx.−mín.) por log tem mediana 0,000 s e máximo 32,0 s. Os valores altos vêm de poucos logs em que o deslocamento muda no meio da execução (causa: a confirmar; hipótese: `--loop` ou reinício do mock); nos demais o deslocamento é constante. Os 13 logs em velocidade 10× foram excluídos, pois o tempo do dispositivo e o relógio LSL avançam em ritmos diferentes. Medição com o Aurora real: [a confirmar].
