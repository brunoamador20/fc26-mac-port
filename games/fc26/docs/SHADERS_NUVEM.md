# Cache de shaders salvo em disco — estórias 4 a 6, preparado na nuvem (2026-10-23)

**Em uma frase:** o kit já guarda em disco cada shader que traduz e o pré-compila na abertura seguinte; para o FC 26
faltavam a **versão** (cache de outro tradutor era usado como se fosse bom), o **limite de tamanho**, um **diário** do
que o jogo entregou (para retraduzir tudo antes da partida quando o tradutor mudar) e uma **espera garantida antes da
partida**. Este PR acrescenta isso por fora do kit (arquivos novos + cinco ganchos de uma linha), com testes no Linux, e
deixa as ferramentas e o roteiro para medir no Mac a diferença entre a 1ª e a 2ª vez.

Branch `claude/fc26-shader-cache-q4p6v0`, PR em rascunho contra `claude/fc26-runtime-estoria2-6qq3u7` (PR #2). Nada foi
rodado com o jogo: a nuvem não tem o jogo nem macOS. Review BMAD obrigatório antes de integrar.

**Fato de partida (BRIEFING, medido no jogo):** não há shaders soltos na RomFS; ficam no `shaderBlockDepot` dentro dos
`.cas` do Frostbite e chegam ao NVN em tempo de execução. Por isso a semente de shaders do kit (que acha BNSH na RomFS)
não serve, e a 1ª vez de cada efeito passa pela tradução Ryujinx → SPIR-V → MSL → Metal.

**Quando isto passa a valer:** só quando o jogo desenhar (estórias 3 e 4: o módulo `PlatformNvn.nro` carregado e os
programas chegando ao NVN). Até lá nenhum shader passa por aqui e nada deste PR roda.

---

## 1. Como o kit faz hoje

Estudados os três runtimes (`games/totk`, `games/by3`, `games/fc26`) e `vendor/ryujinx`. O `games/fc26` tem a cópia do
`games/by3` (cadeia `totk-native-v4-unverified`); o `games/totk` é mais novo (cadeia v7) e tem peças que o fc26 não tem
(seção 1.3). Referências com `arquivo:linha` do `games/fc26` depois deste PR.

### 1.1 O caminho de um shader

| Passo | Onde | O que acontece |
|---|---|---|
| 1. O jogo liga um programa | `third_party/d2r_gfx/gfx/nvn/nvn_mtl.m:5094` `prog_get` | Para cada estágio: **chave do shader** = SHA-256 dos primeiros `ctl_key_len` bytes da seção de controle (a palavra em +0x20 se estiver entre 0x7cc e 0x880, senão 0x880; `nvn_mtl.m:5093`) + os `u32@controle+0x704` bytes do código. Estágio em `controle+0x714`: só 0 (vértice), 1 (fragmento), 5 (compute); outro estágio para o jogo. |
| 2. Estado ligado | `nvn_mtl.m:5695` `rt_answers`, `:5800` `rt_local` | "Respostas" que mudam a tradução: tipo de cada textura ligada (2d, cube, …, `_depth`), imagens (tipo e formato), tipo dos atributos de vértice, tipo das saídas de cor; no compute, o tamanho do grupo de threads (vem do controle, já está na chave). |
| 3. Variante | `totk_shader_rt.m:185` `totk_rt_variant` | Índice `<chave>.variants` (JSON: variante + dependências). Se uma variante serve às respostas, é usada. Senão: nome `<chave>-<12 hex do SHA-256 das respostas>` (`:212`), o código vai para `<variante>.code` e o pedido (JSON) vai ao serviço. |
| 4. Tradução | `totk_shader_rt.m:105` `service_start` | `<WORK>/build/shader-service/totk_xlate --service` (Ryujinx + patches + SPIRV-Cross, compilado com NativeAOT; `prebuilt/macos-arm64`, SHA-256 fixado) grava `<variante>_b.metal` (MSL) e `<variante>_b.json` (reflexão). Falha de tradução **para o jogo** (`die`). |
| 5. Biblioteca Metal | `nvn_mtl.m:4991` `shader_load` | O MSL é compilado na hora com `newLibraryWithSource` e matemática segura (`:4872`). Quem guarda o compilado é o **cache do próprio macOS** (por fonte + opções); o kit não guarda `.metallib` no Mac. |
| 6. Listas de pré-aquecimento | `nvn_mtl.m:4788`, `:4810` | Cada shader e pipeline criado durante o jogo vira uma linha (`S` shader, `R` pipeline de render, `C` compute) em `pso_collected.tsv` (junto do cache) e `pso_user.tsv` (no perfil). |
| 7. Abertura seguinte | `nvn_mtl.m:6739` `warm_start`, `:6531` `warm_worker` | No 1º uso de programa, um trabalho em segundo plano (até 8 threads) compila as listas e **todo** `_b.metal` do cache. O 1º quadro espera só a 1ª lista; o resto segue atrás; no 1º quadro "de mundo" o kit espera até 15 s (`hle_nvn.c:2898`, heurística do TOTK: mais de 2000 desenhos num quadro ou a tela de carregamento). |

Pasta do cache: `<WORK>/build/shader-cache/rt-<DMSH_CHAIN>` (ou `TOTK_SHADER_CACHE`). Com o `make boot`, `<WORK>` é a
pasta de trabalho (`FC26_WORK`/`WORK`).

### 1.2 Respostas às perguntas da tarefa

| Pergunta | Hoje no kit |
|---|---|
| Onde a tradução acontece | No 1º uso de cada programa, na thread de envio (passos 1–4): é ali que nasce a travada da 1ª vez. |
| Existe cache em disco de MSL? | **Sim**: `_b.metal` + `_b.json` + índice `.variants`, por variante. |
| De biblioteca Metal? | **Não no Mac** (o macOS guarda o compilado; o iOS leva `.metallib` prontos). |
| De pipelines (binary archive)? | **Não no fc26.** O `games/totk` novo tem `totk_pipeline_archive.h` (um `MTLBinaryArchive` por pipeline, com identidade SO + GPU + cadeia). |
| Qual a chave | Shader: SHA-256(controle[:ctl_key_len] + código). Variante: + 12 hex do SHA-256 das respostas. Pasta: nome da cadeia (`DMSH_CHAIN`). |
| Versão do formato | Só o nome da cadeia. O hash do tradutor, do SPIRV-Cross, o `TOTK_SHADER_DEBUGMODE` e o modo de profundidade **não** entram: trocar o tradutor sem trocar a cadeia reaproveita MSL velho. Cadeia nova deixa a pasta velha no disco para sempre. |
| Limite de tamanho | Nenhum. |
| Pré-aquecimento | Sim (passo 7), sem garantia de "antes da partida" no FC 26 (a heurística é do TOTK). |
| Pré-aquecimento a partir da RomFS | `scripts/prepare_shader_seed.py` do TOTK/BotW acha BNSH nos pacotes da RomFS e traduz offline uma "semente" que o app importa (`totk_shader_seed.h`). **Não serve ao FC 26**: não há BNSH na RomFS. |

### 1.3 O que o `games/totk` tem a mais (não trazido neste PR)

- **Arquivo de pipelines** (`totk_pipeline_archive.h`): pipelines prontas mesmo depois que o macOS limpa o próprio cache
  (reinício, atualização). Mexe em vários pontos de `nvn_mtl.m` (criação de pipeline, pré-aquecimento): é um porte
  grande e só se mede no Mac.
- **Tradução assíncrona** (`bg_translate`): a 1ª vez não trava, o desenho é pulado até a tradução chegar.
- **Escopo/observados** (`totk_shader_scope.h`, `totk_shader_observed.h`): pré-aquecer só shaders desta versão do jogo.
- A **identidade da tradução** existe no TOTK só no preparo offline da semente (`prepare_shader_seed.py`
  `TranslationCache`: cadeia + SHA-256 do tradutor + SHA-256 do SPIRV-Cross + o construtor do pedido; "identidade
  diferente esvazia a pasta"). Este PR leva essa mesma regra para o cache de tempo de execução do FC 26.

---

## 2. O desenho para o FC 26

```
jogo → NVN programa → chave (kit) → cache rt-<cadeia> (kit: .variants, _b.metal, _b.json)
                                     │
            camada FC 26 ────────────┼── identidade (fc26-cache.id): outro tradutor? esvazia
                                     ├── diário (../fc26-journal): controle + código + estados de cada variante
                                     ├── limite (mais antigo sai primeiro) + trava (uma rodada por vez)
                                     └── antes da partida: retraduz o que falta (prefill) e espera o pré-aquecimento inteiro
```

### 2.1 O que entra na chave (e o que mais influi na tradução)

- **Shader** (do kit, sem mudança): SHA-256 do controle (até `ctl_key_len`) + código. Inclui o segmento de constantes
  `c1` e o grupo de threads do compute, que vêm de lá.
- **Variante** (do kit): + estado ligado (respostas).
- **Identidade da tradução** (nova, `fc26-cache.id` dentro da pasta do cache), tudo o que muda o MSL sem mudar a chave:
  esquema desta camada (`FC26_SC_SCHEMA`), cadeia (`DMSH_CHAIN`), **SHA-256 do `totk_xlate`**, **SHA-256 do
  `spirv-cross`**, revisão do pedido (`FC26_SC_REQUEST_REV`, trocar se `totk_rt_variant` mudar os campos do pedido),
  `TOTK_SHADER_DEBUGMODE` e o **modo de profundidade** (`nvnDeviceSetDepthMode`: com NEAR_IS_MINUS_W todo shader de
  vértice é traduzido com a conversão de z). Se o jogo mudar o modo durante a rodada, a camada apaga a identidade e a
  próxima abertura reconstrói.
- Não entram (só afetam a compilação Metal, que o macOS já separa por fonte + opções): `DM_PRESERVE_INVARIANCE`,
  `TOTK_FAST_MATH`.

A camada recalcula a chave do kit em C (`runtime/shader_cache.c` `fc26_sc_shader_key`, cópia de `ctl_key_len`) e confere
a cada shader novo: se um dia as duas regras divergirem, o log diz `the key rule here (shader_cache.c) differs from
nvn_mtl.m ctl_key_len` e o diário para de aceitar aquele shader (o cache do kit segue funcionando).

### 2.2 Diário: "cada shader que o jogo entrega na hora"

Pasta `<WORK>/build/shader-cache/fc26-journal/` (ou `FC26_SHADER_JOURNAL`), fora da pasta da cadeia, para sobreviver a
troca de tradutor:

- `<chave>.shader`: cabeçalho `FC26SHD1` + estágio + a seção de controle (0x880 bytes) + o código, exatamente o que o
  kit lê. Ao ler, os bytes são conferidos contra a chave.
- `<chave>.rows`: uma linha por variante traduzida: nome da variante, modo de profundidade e o estado ligado em JSON.

É dado do jogo: fica na pasta de trabalho e nunca no git (`.gitignore` cobre `shader-cache/` e `fc26-journal/` se alguém
apontar para dentro do repositório).

### 2.3 Versão: o cache velho é descartado

Na 1ª vez que o kit abre a pasta (`totk_rt_dir`), a camada:

1. calcula a identidade; se o tradutor ou o SPIRV-Cross **não existem**, não mexe em nada (não apaga um cache bom porque
   faltou `make shader-tools`) e diz isso no log;
2. pega a trava `fc26-cache.lock` (se outra rodada a tem, só usa o cache, sem apagar nada);
3. compara com a identidade gravada: diferente, ilegível ou ausente com traduções dentro → **apaga as traduções**
   (arquivos que começam com uma chave e o recibo da semente), mantém as listas de pré-aquecimento (os nomes de variante
   não dependem do tradutor) e o diário, e diz no log qual campo mudou. Por isso não aponte `TOTK_SHADER_CACHE` para o
   cache de outro jogo: uma pasta sem identidade e com traduções dentro tem origem desconhecida e é esvaziada;
4. apaga as pastas `rt-<cadeia velha>` vizinhas **que esta camada marcou** e que nenhuma rodada está usando (as de outros
   ficam);
5. aplica o limite de tamanho.

### 2.4 Antes da partida

- **Retradução (prefill)**: no começo do pré-aquecimento (`warm_start`), as variantes do diário sem `_b.metal` (tradutor
  novo, cache limpo pelo limite de outra máquina, diário copiado) são traduzidas pelo **próprio caminho do kit**
  (`totk_rt_variant`), com a barra "Translating the saved shaders". Antes de cada uma fica um marcador
  `<variante>.prefill`; se essa tradução derrubar o jogo, a próxima abertura pula a variante (ela só será traduzida, ou
  derrubará o jogo, se o jogo usá-la), em vez de não abrir nunca mais.
- **Espera**: com `FC26_SHADER_WARM=all` (padrão), o 1º uso de shader espera o pré-aquecimento **inteiro** (todo shader
  do cache e toda pipeline das listas), no máximo `FC26_SHADER_WARM_TIMEOUT_S` (300 s). Motivo: ainda não se sabe como
  reconhecer o começo da partida no FC 26 (a heurística do kit é do TOTK); esperar antes do 1º desenho é o único ponto
  que garante "antes da partida". Custo: abertura mais lenta, a medir. `FC26_SHADER_WARM=kit` volta ao do kit.
  A espera fica no mesmo ponto e roda as mesmas funções (`shader_load`, criação de pipeline) que a espera da 1ª lista do
  kit, que o TOTK já usa com a lista da tela de título; não há trava nova. Se mesmo assim a abertura parar no teto
  (`warm-up: … (time limit …)` no log), rodar com `FC26_SHADER_WARM=kit` e registrar o caso.

### 2.5 Limite de tamanho

- `FC26_SHADER_CACHE_MAX_MIB` (padrão 2048; `0` = sem limite) vale para traduções + diário. Passou do limite: saem os
  shaders usados há mais tempo (todos os arquivos daquele shader nas duas pastas) até 90% do limite. O padrão é um
  chute: a seção 6 pede os números para calibrar.
- "Uso" = data de modificação dos arquivos do shader; a camada toca 1 arquivo por shader por rodada quando o kit acha
  a variante pronta.
- As listas `pso_*.tsv` podem citar shaders que saíram: o pré-aquecimento do kit já pula esses em silêncio (conta no
  fim). Elas não são podadas (seção 7).

### 2.6 Variáveis de ambiente

| Variável | Padrão | Efeito |
|---|---|---|
| `FC26_SHADER_CACHE` | ligado | `0` desliga a camada inteira (só o cache do kit, como antes) |
| `FC26_SHADER_CACHE_MAX_MIB` | 2048 | limite de traduções + diário; `0` = sem limite |
| `FC26_SHADER_WARM` | `all` | `all`: 1º uso de shader espera o pré-aquecimento inteiro; `kit`: só as esperas do kit |
| `FC26_SHADER_WARM_TIMEOUT_S` | 300 | teto da espera (1..3600 s) |
| `FC26_SHADER_PREFILL` | ligado | `0` não retraduz o diário na abertura |
| `FC26_SHADER_JOURNAL` | `<cache>/../fc26-journal` | pasta do diário |
| do kit: `TOTK_SHADER_CACHE`, `TOTK_SHADER_DEBUGMODE`, `TOTK_SURVEY_SHADER_LOG`, `TOTK_CTL_DUMP`, `DM_NVN_TSV`, `TOTK_WARM_THREADS`, `DM_PSO_MANIFEST` | | ver os comentários em `totk_shader_rt.m` e `nvn_mtl.m` |

### 2.7 Arquivos

| Arquivo | O quê |
|---|---|
| `runtime/shader_cache.h`, `runtime/shader_cache.c` | **novo**, C puro (POSIX): SHA-256, chave, identidade, diário, descarte, pastas velhas, limite, trava, leitura das variáveis |
| `runtime/shader_cache_mac.m` | **novo**, Objective-C: liga a lógica ao kit (abrir, uso, salvo, prefill, espera); `TODO(mac)` |
| `third_party/d2r_gfx/gfx/nvn/totk_shader_rt.m` | **3 ganchos** (`:66` abrir, `:203` uso, `:258` salvo) + declarações `weak_import` (`:28-30`) |
| `third_party/d2r_gfx/gfx/nvn/nvn_mtl.m` | **2 ganchos** em `warm_start` (`:6741` prefill, `:6793` espera) + declarações (`:82-83`) |
| `scripts/shader_cache_report.py` | **novo**: relatório por rodada e ganho 1ª → 2ª (`make shader-report`) |
| `scripts/shader_key_check.py` | **novo**: a chave se repete entre aberturas? (`make shader-keys`) |
| `tests/test_shader_cache.py` + `tests/shader_cache_check.c`, `tests/test_shader_tools.py` | **novos**: 22 + 8 testes sintéticos |
| `Makefile`, `.gitignore`, `tests/test_runtime_syntax.py` | alvos `shader-report`/`shader-keys`; pastas de cache ignoradas; `shader_cache.c` na lista de fontes portáveis |

Os ganchos são `weak_import`, o mesmo jeito que a camada gráfica já chama `runtime_boot_status`: sem o runtime do FC 26
ligado, a camada gráfica se comporta exatamente como antes.

---

## 3. O que foi conferido na nuvem

| Checagem | Resultado |
|---|---|
| `make test` (Linux, Python 3.13): 22 testes da lógica C + 8 das ferramentas + os 25 que a base já tinha | OK (55) |
| Os 22 testes da lógica C com o arnês compilado com ASan + UBSan + LSan (gcc) | OK, sem erro de memória nem vazamento na biblioteca |
| `runtime/shader_cache.c` com clang 18 e gcc, `-std=c11 -Wall -Wextra -Werror` | OK |
| `runtime/shader_cache_mac.m` contra cabeçalhos Foundation de mentira (só sintaxe e tipos) | OK |
| **CI no macOS do GitHub** (run 39891061410, commit `5155e41`) | **OK**: o passo de testes (`make test`, que no macOS também roda os testes do cache e passa `xcrun clang -Werror` em todo `.c`/`.m` do runtime) passou; `make runtime` compilou e linkou o `fc26-native` com `shader_cache.c`, `shader_cache_mac.m` (`-Werror`) e os ganchos (conferido no log do job); o binário inicia |
| Rodar com o jogo | **não feito** (nuvem sem jogo e sem macOS) |

---

## 4. O que falta testar no Mac (`TODO(mac)`)

Pré-requisito: a estória 4 avançada a ponto de o jogo desenhar (shaders chegando ao NVN). Regras do Mac (BRIEFING): uma
compilação/rodada por vez, sem som nas rodadas automáticas, rede negada ao jogo, processo só por PID.

```sh
cd ~/fc26-switch/mng/games/fc26          # o clone com esta branch
export PY=$HOME/fc26-switch/venv/bin/python WORK=$HOME/fc26-switch/work
make test PY=$PY                          # inclui os testes do cache, agora no Mac
make shader-tools PY=$PY WORK=$WORK       # tradutor (prebuilt, SHA-256 conferido) + spirv-cross (clona o commit fixado: rede só p/ compilar)
make runtime PY=$PY WORK=$WORK
```

`make boot` **não** depende de `shader-tools`: sem eles, a 1ª tradução para o jogo (`shader service exited…`) e a camada
avisa `translator … or SPIRV-Cross … missing (make shader-tools)`.

| # | Teste | Como | Esperado |
|---|---|---|---|
| 1 | **A chave se repete entre aberturas** (decide tudo) | duas aberturas iguais com `TOTK_CTL_DUMP=$WORK/logs/ctl-1.tsv` e `ctl-2.tsv` no `BOOT_ENV`; `make shader-keys PY=$PY DUMPS="$WORK/logs/ctl-1.tsv $WORK/logs/ctl-2.tsv"` | `veredito: chave ESTÁVEL`. Se não: os bytes do controle que mudam aparecem; ver seção 6, pergunta 1 |
| 2 | A camada abre | 1ª abertura; `grep '\[fc26-shader-cache\]' $WORK/logs/boot.log`; `ls $WORK/build/shader-cache` | linha `cache …: N shaders …`; pastas `rt-totk-native-v4-unverified/` (com `fc26-cache.id`) e `fc26-journal/` (com `.shader`/`.rows`) |
| 3 | Ganho 1ª x 2ª vez | seção 5 | 2ª rodada sem traduções e quase sem compilação durante o jogo |
| 4 | Versão | abrir com `TOTK_SHADER_DEBUGMODE=1` no `BOOT_ENV`, depois sem | log `cache identity differs (debug_mode)` e `prefill: N … translating them before play`; na volta, o mesmo de novo |
| 5 | Limite | abrir com `FC26_SHADER_CACHE_MAX_MIB=1` | log `… least recently used removed`; traduções + diário caem para perto de 0,9 MiB (as listas `pso_*.tsv` não saem); o jogo segue e retraduz o que precisar |
| 6 | Espera | comparar `FC26_SHADER_WARM=all` (padrão) com `=kit`: tempo até o menu e travadas no jogo | `all`: abertura mais longa, 0 compilação na partida; `kit`: abertura curta, alguma compilação até o pré-aquecimento terminar |
| 7 | Memória (Mac de 8 GB) | rodada 2 com `/usr/bin/time -l` antes do `./build/fc26-native` (linha `maximum resident set size`) | anotar o pico: o pré-aquecimento mantém shaders e pipelines na memória |
| 8 | Derrubada no prefill | (só se acontecer) ver `ls $WORK/build/shader-cache/rt-*/*.prefill` | a variante é pulada na abertura seguinte e o log diz `skipped` |

---

## 5. Como medir o ganho (travadas na 1ª vez x 2ª vez)

**O que é "travada" aqui:** trabalho feito durante o jogo, na thread de envio, que o cache existe para tirar: tradução
de shader, compilação de biblioteca Metal e criação de pipeline. O kit já mede cada um (`TOTK_SURVEY_SHADER_LOG=1`: uma
linha por item com o quadro e os ms), registra os **quadros longos** com quantas pipelines/bibliotecas foram criadas
neles (log `[长帧]`, ligado por padrão) e, com `DM_NVN_TSV`, o tempo de cada quadro.

**Protocolo:** a mesma sequência nas duas rodadas (por exemplo: abrir → menus → Kick-Off → 2 min de jogo → sair), de
preferência com janela, mesmas configurações, nada mais rodando. Para repetir os mesmos toques, `TOTK_INPUT_SCRIPT`
(`"segundo:código:ms,..."`, códigos de tecla do Mac: 38 = J = botão A, 36 = Return = botão +) — a sequência de menus do FC 26 só se sabe com o jogo.

```sh
# Rodada 1, cache vazio (move o cache de lado em vez de apagar)
mv "$WORK/build/shader-cache" "$WORK/build/shader-cache.antes-$(date +%Y%m%d-%H%M)" 2>/dev/null
make boot PY=$PY WORK=$WORK FC26_LOG=$WORK/logs/shader-1.log \
  BOOT_ENV="TOTK_AUDIO_OFF=1 FC26_AUDIO=0 TOTK_SURVEY_SHADER_LOG=1 DM_NVN_TSV=$WORK/logs/frames-1.tsv DM_NVN_TSV_CALLS=0 TOTK_CTL_DUMP=$WORK/logs/ctl-1.tsv"
# Rodada 2, logo depois, a mesma sequência
make boot PY=$PY WORK=$WORK FC26_LOG=$WORK/logs/shader-2.log \
  BOOT_ENV="TOTK_AUDIO_OFF=1 FC26_AUDIO=0 TOTK_SURVEY_SHADER_LOG=1 DM_NVN_TSV=$WORK/logs/frames-2.tsv DM_NVN_TSV_CALLS=0 TOTK_CTL_DUMP=$WORK/logs/ctl-2.tsv"
make shader-keys PY=$PY DUMPS="$WORK/logs/ctl-1.tsv $WORK/logs/ctl-2.tsv"
make shader-report PY=$PY RUNS="$WORK/logs/shader-1.log $WORK/logs/shader-2.log" FRAMES="$WORK/logs/frames-1.tsv $WORK/logs/frames-2.tsv"
```

(Sem `TOTK_HEADLESS=1` a rodada abre a janela; com ele também mede, mas as duas rodadas têm de ser iguais nisso.)

**Como ler o relatório** (`make shader-report`):

- por rodada: traduções, bibliotecas Metal e pipelines feitas **durante o jogo** (quantas, total, p95, máximo), quadros
  longos com compilação (e quais ficaram escondidos atrás de uma tela de carregamento), espera do pré-aquecimento, e a
  tabela de quadros (p50/p95/p99/máximo, quantos acima de 33 ms e de 100 ms, quantos compilaram algo);
- no fim, **Ganho**: `travadas X → Y ms`, contagens 1ª → 2ª, quadros > 33 ms e p99.
- Esperado na 2ª rodada, para a mesma sequência: 0 traduções; bibliotecas e pipelines perto de 0 (só o que a 1ª rodada
  não viu); quadros longos com compilação perto de 0; em troca, a abertura fica mais longa pelo pré-aquecimento
  (linhas `warm-up: the first shader use waited … ms` e `管线预热完成 … 后台用时 … ms`).
- Uma 3ª rodada depois de reiniciar o Mac mostra o caso "dia seguinte": o nosso cache está lá, mas o cache de
  compilação do macOS pode ter sido limpo; aí o pré-aquecimento recompila tudo (mais lento) e o jogo continua sem
  travar. Se esse tempo ficar ruim, é o argumento para trazer o arquivo de pipelines do TOTK (seção 7).

Registrar no `CHANGELOG.md`: as duas linhas de **Ganho**, o veredito do `shader-keys`, o tamanho do cache (linha
`[fc26-shader-cache] cache …`) e o tempo da abertura com e sem `FC26_SHADER_WARM=all`.

---

## 6. Perguntas que só o binário responde

1. **A chave de cada shader é a mesma de uma abertura para a outra?** (teste 1). Se o Frostbite montar a seção de
   controle com bytes que mudam a cada abertura (como o BotW com bytes depois da seção), o cache nunca acerta e é
   preciso zerar esses bytes antes do hash — no kit (`ctl_key_len`/`prog_get`) **e** em `shader_cache.c`, juntos. O
   `shader-keys` diz quais bytes.
2. Qual o tamanho da seção de controle do FC 26 (palavra em `controle+0x20`)? O kit assume 0x880 ou um valor entre 0x7cc
   e 0x880.
3. Quantos shaders e variantes uma partida usa, e quantos MiB o cache ocupa? Calibra o limite padrão (2048 MiB).
4. O FC 26 usa tesselação ou geometria? O kit só traduz vértice, fragmento e compute e **para** com `NVN stage %d has no
   translation chain` (o BRIEFING lista tesselação entre as lacunas do NVN).
5. O jogo chama `nvnDeviceSetDepthMode`? Antes do 1º programa? (A identidade lê o modo quando o cache abre.)
6. Os 7 compute shaders embutidos no módulo de vídeo chegam pelo mesmo caminho (`nvnProgramSetShaders`)? Se sim, também
   vão para o cache e o diário.
7. Quanto tempo o pré-aquecimento leva no M1 de 8 GB, com e sem o cache de compilação do macOS, e quanta memória fica?
8. Onde começa "a partida" (tela de carregamento do Kick-Off)? Sabendo isso, a espera pode sair do 1º desenho e ir para a
   tela de carregamento, como o kit faz no TOTK, encurtando a abertura.
9. Quanto custa a 1ª rodada (traduções por minuto de jogo, pior quadro)? Se for ruim, a tradução assíncrona do TOTK
   entra na fila (seção 7).

---

## 7. Próximos passos (fora deste PR)

- **Semente a partir do diário:** o `fc26-journal/` de uma máquina, copiado para outra, é traduzido inteiro antes da 1ª
  partida (é o prefill). Isso dá ao FC 26 o que a semente da RomFS dá ao TOTK, sem precisar ler o `shaderBlockDepot`.
  (Ler o depósito direto dos `.cas` exigiria o formato do Frostbite: só com o jogo.) Contém dado do jogo: nunca no git.
- **Arquivo de pipelines do TOTK** (`totk_pipeline_archive.h`), se a 3ª rodada da seção 5 mostrar recompilação longa.
- **Tradução assíncrona do TOTK**, se a 1ª rodada travar demais.
- Podar de `pso_collected.tsv`/`pso_user.tsv` as linhas de shaders que o limite tirou (hoje só crescem; o kit pula as
  linhas órfãs).
