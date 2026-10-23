# Pré-tradução dos shaders do FC 26 (estória D3)

**Em uma frase:** os shaders do FC 26 estão nos `.cas` do Frostbite, em blocos Oodle; `scripts/shader_seed.py`
descomprime os blocos com o **próprio Oodle do jogo** (modo `oodle` do `fc26-native`, sem iniciar o jogo), acha cada
par código + controle exatamente como o jogo entrega ao `nvnProgramSetShaders` e traduz com o mesmo tradutor e o mesmo
pedido do runtime, no cache `rt-<cadeia>`, com a mesma chave e o mesmo nome de arquivo.

## Como o shader está guardado

- `.cas` = catálogo no início (u32 big-endian com o tamanho + os bytes) e depois blocos:
  `u32 BE tamanho descomprimido | u8 tipo | u8 0x70 + bits 16-19 do tamanho guardado | u16 BE bits 0-15`.
  No FC 26 só aparecem o tipo `0x00` (cru) e o `0x19` (Oodle; o fluxo começa com `0x8C 0x0C`). Quem despacha os
  tipos no jogo é `main+0x8af0d30` (1.0.0); o `OodleLZ_Decompress` fica em `main+0x13d0` (o script acha pelo nome
  que a função passa ao plugin de log na entrada).
- Dentro dos dados descomprimidos, cada shader é um registro do Frostbite (`...'NVNV'..., u32 deslocamento do código,
  tamanho do código, deslocamento do controle, 0x880`) seguido do **código NVN** (cabeçalho de 0x30 bytes com
  0x12345678; compute 0x12345679) e logo depois da **seção de controle** de 0x880 bytes (GLSLC, 0x98761234, versão 1).
  O tamanho do código está em `controle+0x704`; o script não depende do registro: acha o controle e pega os
  `u32@+0x704` bytes antes dele.

## Chave e nomes (os do runtime)

- Chave: SHA-256(`controle[:ctl_key_len]` + `código[:u32@controle+0x704]`) (`nvn_mtl.m` `prog_get`; teste contra
  `runtime/shader_cache.c` `fc26_sc_shader_key`).
- Variante: `<chave>-<12 hex do SHA-256 do JSON das respostas>`, JSON do `NSJSONSerialization` com
  `NSJSONWritingSortedKeys` (ordem numérica do NSString: "9" antes de "10"; teste contra o Foundation).
- Pedido ao `totk_xlate --service`: os campos do `totk_rt_variant` (`variant`, `stage`, `code`, `c1`, respostas,
  `local` no compute, `depth_minus_w` da identidade). `<variante>.code` = código sem os 0x30 bytes (gráficos).
- Índice `<chave>.variants` reescrito como o runtime escreve; o script recusa um cache sem `fc26-cache.id` ou com
  outro tradutor/SPIRV-Cross (o runtime esvaziaria) e um cache cujo `fc26-cache.lock` uma rodada segura.

## Uso

```sh
cd games/fc26
export PY=$HOME/fc26-switch/venv/bin/python WORK=$HOME/fc26-switch/work
make runtime PY=$PY WORK=$WORK                     # fc26-native com o modo "oodle"
make shader-seed PY=$PY WORK=$WORK                 # ~2 min: $WORK/build/shader-seed-fc26/{shaders/,inventory.tsv,summary.json}
# com o jogo FECHADO (o script recusa se uma rodada segura o cache):
make shader-seed-translate PY=$PY WORK=$WORK CACHE=$WORK/build/shader-cache/rt-totk-native-v4-unverified
# prova com um shader que o runtime já traduziu (só lê o cache e o diário):
$PY scripts/shader_seed.py prove --out $WORK/build/shader-seed-fc26 --key <chave> --scratch /tmp/prova
```

`translate --journal-answers $WORK/build/shader-cache/fc26-journal` traduz também os estados ligados que o diário viu.

## Números (1.0.0, M1, 23/10/2026)

- 19 `.cas`, 645.487 blocos, 21 GiB descomprimidos em 102 s. Shaders só em 3 `.cas`
  (`installpackage_00/cas_01`, `installpackage_02/cas_01`, `installpackage_03/cas_01`).
- **10.844 shaders distintos**: 4.402 vértice, 3.550 fragmento, 2.852 compute, **40 de tesselação** (15 estágio 3,
  25 estágio 4: o runtime não tem cadeia para eles e para com `unsupported NVN stage`). 109 MiB extraídos.
- Tradução dos 10.804 traduzíveis no estado padrão: 123 s com 6 tradutores, 0 falhas, ~1,5 GiB no cache.

## Limites conhecidos

- **Controle trocado pelo jogo:** de 371 shaders do diário, 194 saem do disco com a mesma chave; os outros 177 têm o
  mesmo código e um controle que existe no disco, mas de **outro registro**, igual a menos dos 24 bytes em
  `+0x7d0..+0x7e7`. O jogo junta registros com controles iguais fora desse campo e entrega um deles; qual é depende da
  ordem de carga (não é sempre o primeiro do disco). Com a chave atual esses 177 só acertam se o par for adivinhado.
  Proposta (fora desta tarefa, muda a chave do runtime): tirar `+0x7d0..+0x7e7` do hash em `nvn_mtl.m`
  `ctl_key_len`/`prog_get` **e** `shader_cache.c` (como o kit faz com bytes do BotW); aí os 371 acertam.
- Estado padrão: 115 das 196 linhas do diário com shader extraído usam a variante padrão; o resto precisa do estado
  certo (`--journal-answers`) ou é traduzido no jogo.
- O pré-aquecimento compila **todo** `_b.metal` do cache na abertura e `FC26_SHADER_WARM=all` espera tudo (até 300 s):
  com 10.800 shaders a abertura fica bem mais longa (medir; `FC26_SHADER_WARM=kit` evita a espera).
- O limite padrão do cache (`FC26_SHADER_CACHE_MAX_MIB=2048`) fica perto do tamanho da semente (1,5 GiB + o que o jogo
  traduzir).
- Só a 1.0.0 (`extracted/v100`); a atualização tem `.cas` próprios (rodar `scan` na RomFS dela quando houver).
