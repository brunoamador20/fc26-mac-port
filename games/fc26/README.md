# EA SPORTS FC 26 (Nintendo Switch) nativo no Mac — pasta do runtime

[Português](#português) | [English](#english)

## Português

Esta pasta é o runtime do FC 26: o host do Horizon (`runtime/`), o reescritor (`third_party/d2r`), a camada NVN sobre
Metal (`third_party/d2r_gfx`), o tradutor de shaders (`prebuilt/`), o lançador (`app/`), os scripts (`scripts/`) e os
valores esperados de cada versão (`assets/`). Não tem nada do jogo nem chaves.

**Requisitos, aviso legal, passo a passo, problemas comuns e créditos: [README da raiz](../../README.md).**

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

This folder is FC 26's runtime: the Horizon host (`runtime/`), the rewriter (`third_party/d2r`), the NVN-on-Metal layer
(`third_party/d2r_gfx`), the shader translator (`prebuilt/`), the launcher (`app/`), the scripts (`scripts/`) and each
version's expected values (`assets/`). It holds no game content and no keys.

**Requirements, legal notice, step-by-step build, common problems and credits: [top-level README](../../README.md).**

The build in short, one resumable command:

```sh
games/fc26/build.sh --base <base game 1.0.0.nsp> --update <update 1.89.6e65.nsp> \
                    --keys <prod.keys> --work <work folder> --app "<folder>/FC 26.app"
```

It runs the commands listed in the Portuguese section above, in that order: the update's ExeFS
(`scripts/extract_exefs.py --update`), the merged RomFS (`scripts/merge_update_romfs.py`), `make rewrite`, `make nro`,
`make prepare runtime OUT=$WORK/build-update` and `make app` (which uses build-update by itself), skipping what is
already done. Synthetic tests, with no game data: `make test PY=python3`. Technical notes: [docs/](docs).
