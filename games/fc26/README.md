# EA SPORTS FC 26 (Nintendo Switch) nativo no Mac — pasta do runtime

[Português](#português) | [English](#english)

## Português

Esta pasta é o runtime do FC 26: o host do Horizon (`runtime/`), o reescritor (`third_party/d2r`), a camada NVN sobre
Metal (`third_party/d2r_gfx`), o tradutor de shaders (`prebuilt/`), o lançador (`app/`), os scripts (`scripts/`) e os
valores esperados de cada versão (`assets/`). Não tem nada do jogo nem chaves.

**Requisitos, aviso legal, passo a passo, problemas comuns e créditos: [README da raiz](../../README.md).** Guia para
assistentes de IA: [AGENTS.md](../../AGENTS.md).

Resumo do build, de um comando só e retomável:

```sh
games/fc26/build.sh --base <jogo base 1.0.0.nsp> --update <atualização 1.89.6e65.nsp> \
                    --keys <prod.keys> --work <pasta de trabalho> --app "<pasta>/FC 26.app"
```

O que ele roda, nesta ordem (cada script explica a si mesmo com `--help`; `WORK` fora do repositório, `PY` o Python do
venv `<work>/venv` com o [requirements.txt](requirements.txt)):

```sh
$PY scripts/extract_exefs.py <atualização>.nsp --keys <prod.keys> --update --output $WORK/extracted/v1638400/exefs
$PY scripts/merge_update_romfs.py <jogo base>.nsp <atualização>.nsp --keys <prod.keys> --output $WORK/extracted/v1638400/romfs
make rewrite PY=$PY WORK=$WORK                               # main e sdk (4 a 5 GB de RAM)
make nro PY=$PY WORK=$WORK                                   # Engine.Render.Core2.PlatformNvn.nro
make prepare runtime PY=$PY WORK=$WORK OUT=$WORK/build-update
make app PY=$PY WORK=$WORK APP="<pasta>/FC 26.app" GAME=<jogo base>.nsp KEYS=<prod.keys>   # usa build-update sozinho
```

Testes sintéticos, sem nada do jogo: `make test PY=python3`. Documentos técnicos: [docs/](docs).

## English

This folder contains the FC 26 runtime. It contains no game content and no keys. These are its parts:

- `runtime/`: the Horizon host;
- `third_party/d2r`: the rewriter;
- `third_party/d2r_gfx`: the NVN-on-Metal layer;
- `prebuilt/`: the shader translator;
- `app/`: the launcher;
- `scripts/`: the build scripts;
- `assets/`: the expected values of each version.

**The [top-level README](../../README.md) gives the requirements, the legal notice, the build steps, the usual problems
and the credits.** [AGENTS.md](../../AGENTS.md) is the guide for AI assistants.

To build the app, use this command. If it stops, run it again:

```sh
games/fc26/build.sh --base <base game 1.0.0.nsp> --update <update 1.89.6e65.nsp> \
                    --keys <prod.keys> --work <work folder> --app "<folder>/FC 26.app"
```

`build.sh` runs the commands of the Portuguese section above, in this sequence. It skips the steps that are complete.

1. `scripts/extract_exefs.py --update` extracts the ExeFS of the update.
2. `scripts/merge_update_romfs.py` merges the RomFS of the base game and the update.
3. `make rewrite` rewrites the game code.
4. `make nro` rewrites the video module.
5. `make prepare runtime OUT=$WORK/build-update` checks the files and compiles the runtime.
6. `make app` makes the app from `build-update`.

The synthetic tests use no game data: `make test PY=python3`. The technical notes are in [docs/](docs).
