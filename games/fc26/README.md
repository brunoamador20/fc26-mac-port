# EA SPORTS FC 26 (Switch) nativo no Mac — em andamento

Port nativo do FC 26 de Switch para o Mac com Apple silicon, pelo caminho do kit (reescritor, carregador, host do
Horizon, NVN sobre Metal). Esta pasta é um runtime próprio, derivado do fork do kit em `games/by3` (que derivou de
`games/totk`): tudo o que ele usa está aqui (`runtime/`, `third_party/d2r`, `third_party/d2r_gfx`, `prebuilt/`,
`scripts/`), e nada aqui lê a pasta de outro jogo.

- Briefing, fatos medidos e regras: [docs/BRIEFING.md](docs/BRIEFING.md).
- Estado e diário: [CHANGELOG.md](CHANGELOG.md).
- Estória 2 (runtime até o `nnMain`), preparada na nuvem, com os comandos exatos para o Mac:
  [docs/ESTORIA2_NUVEM.md](docs/ESTORIA2_NUVEM.md).
- Cache de shaders salvo em disco (estórias 4 a 6): como o kit faz, o desenho para o FC 26, o que testar no Mac e como
  medir a 1ª x 2ª vez: [docs/SHADERS_NUVEM.md](docs/SHADERS_NUVEM.md).
- Estória 4, parte dos serviços offline (loja, rede local, DLC, controle parental, Opus), preparada na nuvem:
  [docs/SERVICOS_NUVEM.md](docs/SERVICOS_NUVEM.md).

É preciso ter o jogo: o NSP e o `prod.keys` do próprio Switch. Nada do jogo entra no git (NSP/NCA/RomFS,
`main`/`sdk`/`rtld`/`.nro`, saídas do reescritor, chaves, saves); a pasta de trabalho (`FC26_build/` ou a indicada em
`WORK=`) e `mods/` ficam fora dele (`.gitignore`).

## Entrada

- Jogo base 1.0.0, Title ID `01004FF021942000`, SDK 19.3.4, **sem update e sem DLC** (um NSP de 13.409.283.148 bytes).
- ExeFS: `main`, `sdk`, `rtld`, `main.npdm`; **não há `subsdk0`**. O vídeo vem num módulo à parte que o jogo carrega
  em tempo de execução (`Engine.Render.Core2.PlatformNvn.nro`, via nn::ro): é a estória 3.

## Onde cada coisa é decidida

| O quê | Onde |
|---|---|
| Title ID, versão (`1.0.0` / `v100`), módulos (`main`, `sdk`), variáveis da reescrita | `assets/game.json` (lido por `scripts/game_config.py`; `make check-config`) |
| Hashes fixados (ExeFS, reescrita, RomFS) | `assets/expected-v1.0.0.json` (null até o Mac gravar com `make prepare PREPARE_FLAGS=--record`) |
| Constantes do jogo no C | `runtime/game_version.h` (conferido contra o `game.json`) |
| Patches de código do jogo | mecanismo em `runtime/game_patches.c` + `scripts/prepare_patches.py`; nenhum patch (FC26_PATCHES vazio) |

## Montar e rodar (resumo; a sequência completa está em docs/ESTORIA2_NUVEM.md)

De `games/fc26`, com o Python do `requirements.txt` (`PY=`) e a pasta de trabalho (`WORK=`):

```sh
python scripts/extract_exefs.py "<jogo>.nsp" --keys <chaves> --output "$WORK/extracted/v100/exefs"
python scripts/extract_romfs.py --keys <chaves> --manifest "$WORK/extracted/v100/extraction-manifest.json" --output "$WORK/extracted/v100/romfs"
# reescrita (estória 1): $WORK/rewritten/v100/{main,sdk}.patched.bin (+ .fixups.tsv, .gates.tsv)
make test PY=$PY                                   # testes sintéticos, sem dado do jogo
make prepare PY=$PY WORK=$WORK PREPARE_FLAGS=--record   # só a 1ª vez grava os hashes; depois sem --record
make runtime probe PY=$PY WORK=$WORK
make boot PY=$PY WORK=$WORK BOOT_ENV="TOTK_HEADLESS=1 TOTK_AUDIO_OFF=1 FC26_AUDIO=0 TOTK_VERIFY_STARTUP=nnmain"
```

O app (`make app`, "FC 26.app") existe, mas não é necessário antes de o jogo desenhar.
