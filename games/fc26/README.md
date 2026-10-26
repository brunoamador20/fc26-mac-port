# EA SPORTS FC 26 (Nintendo Switch) nativo no Mac

[Português](#português) | [English](#english)

## Português

O código do FC 26 de Switch roda **nativo** num Mac com Apple silicon, sem emulador. O código ARM do jogo é reescrito
uma vez para o Mac, um host imita os serviços do sistema do Switch, e os gráficos NVN são traduzidos para Metal. O
caminho é o do [MacNativeGames](../../README.md). Esta pasta é o runtime próprio do FC 26.

### O que você precisa ter

> **Este repositório não tem nada do jogo e nenhuma chave.** Ele só funciona com arquivos que você mesmo tira do seu
> console. Não peça, não compartilhe e não baixe jogo ou chaves de terceiros.

1. **Um Nintendo Switch seu**, de onde você tira:
   - as **chaves do console** (`prod.keys`), extraídas do **seu próprio** Switch;
   - o **EA SPORTS FC 26 que você comprou**:
     - o jogo base 1.0.0 (Title ID `01004FF021942000`), em NSP extraído do seu console;
     - a **atualização 1.89.6e65** (v1638400), também extraída do seu console. É a versão em que o port roda;
     - DLC não é necessário.
2. **Um Mac com Apple silicon** (M1 ou mais novo) com **macOS 26 ou mais novo**. Foi testado num MacBook Pro 13" M1 de
   8 GB com macOS 27.
3. **Espaço em disco:** cerca de **75 GB livres**, para os arquivos do jogo, os dados extraídos, a compilação e o cache
   de gráficos.
4. **Ferramentas:**
   - as Command Line Tools do Xcode;
   - o [Homebrew](https://brew.sh) com `opus` e `libvpx` (`brew install opus libvpx`);
   - Python 3 com os pacotes de [requirements.txt](requirements.txt).
5. **Memória:** a reescrita do código do jogo, feita uma vez só, usa uns 4 a 5 GB de RAM. Num Mac de 8 GB, feche os
   outros apps durante essa etapa.

Tudo que é online fica de fora: o port roda **offline**, sem os servidores da EA e sem os modos online.

### O que funciona

- Menus, **Pontapé de saída** e **Carreira**: partida inteira até o apito final, avanço no calendário, salvar,
  fechar e reabrir com o progresso certo.
- 30 quadros por segundo, ou **60 fps opcional**, que esquenta mais o Mac.
- Som, teclado e controle.
- No app, as opções:
  - **modo jogo** do macOS, ao jogar em tela cheia;
  - **modo economia**, com as configurações de portátil do Switch: 720p e menos calor;
  - **"IA mais atenta" (experimental)**, que liga cálculos de inteligência que a versão de Switch deixa no modo
    econômico.

### Limitações conhecidas

- A cena dos jogadores em roda antes da partida às vezes sai clara demais.
- A jogabilidade é a da versão de Switch: alguns recursos de movimento da versão de PlayStation 5 vêm desligados de
  fábrica.
- Projeto em andamento.

### Como montar

Não há nada pronto para baixar: tudo é gerado no seu computador a partir dos seus arquivos. A montagem ainda é técnica.
Abaixo está o caminho principal; os detalhes de cada script estão no `--help` dele. De `games/fc26`, com o Python do
`requirements.txt` (`PY=`) e uma pasta de trabalho fora do repositório (`WORK=`):

```sh
make test PY=$PY                                         # testes sintéticos, sem nada do jogo
# 1. o código do jogo base e o da atualização
$PY scripts/extract_exefs.py "<jogo base>.nsp" --keys <prod.keys> --output "$WORK/extracted/v100/exefs"
$PY scripts/extract_exefs.py "<atualização>.nsp" --keys <prod.keys> --update --output "$WORK/extracted/v1638400/exefs"
# 2. os dados do jogo (RomFS) da atualização sobre os do jogo base: veja scripts/extract_romfs.py --help
# 3. a reescrita do código para o Mac, uma vez só (uns 4 a 5 GB de RAM)
make rewrite PY=$PY WORK=$WORK
# 4. o runtime e o app
make prepare runtime PY=$PY WORK=$WORK OUT=$WORK/build-update
make app WORK=$WORK APP="<pasta>/FC 26.app"
```

O app "FC 26.app" é só o lançador: abre a janela de opções e roda o jogo a partir da pasta de trabalho. Perfil e saves
ficam em `~/Library/Application Support/MacNativeGames/FC26/profile`, e o log em `~/Library/Logs/MacNativeGames/fc26.log`.

### Aviso legal

Projeto de fã, sem fins lucrativos, **sem relação** com a Electronic Arts, a Nintendo ou a Apple. EA SPORTS FC é marca da
Electronic Arts; Nintendo Switch é marca da Nintendo. Use apenas com uma cópia do jogo que você comprou e com chaves do seu
próprio console.

Créditos: [MacNativeGames](https://github.com/ly05010419/MacNativeGames) (MIT), de onde vem o caminho nativo, e os demais
projetos listados em [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md), entre eles o
[nxnative](https://github.com/seedds/nxnative) (MIT).

## English

The Switch code of FC 26 runs **natively** on an Apple silicon Mac, with no emulator. The game's ARM code is rewritten
once for the Mac, a host stands in for the Switch's system services, and NVN graphics are translated to Metal. The
approach is [MacNativeGames](../../README.md)'s; this folder is FC 26's own runtime.

### What you need

> **This repository contains no game content and no keys.** It only works with files you dump from your own console.
> Do not ask for, share or download games or keys from anyone else.

1. **Your own Nintendo Switch**, from which you dump:
   - the **console keys** (`prod.keys`), from **your own** Switch;
   - the **EA SPORTS FC 26 you bought**:
     - the base game 1.0.0 (Title ID `01004FF021942000`), as an NSP dumped from your console;
     - the **1.89.6e65 update** (v1638400), also dumped from your console. The port runs on that version;
     - no DLC is needed.
2. **An Apple silicon Mac** (M1 or newer) with **macOS 26 or newer**. It was tested on an 8 GB 13" M1 MacBook Pro with
   macOS 27.
3. **Disk space:** about **75 GB free**, for the game files, the extracted data, the build and the graphics cache.
4. **Tools:**
   - the Xcode Command Line Tools;
   - [Homebrew](https://brew.sh) with `opus` and `libvpx` (`brew install opus libvpx`);
   - Python 3 with the packages in [requirements.txt](requirements.txt).
5. **Memory:** the one-time rewrite of the game code takes about 4 to 5 GB of RAM. On an 8 GB Mac, close other apps
   during that step.

Everything online is left out: the port runs **offline**, without EA's servers and without the online modes.

### What works

- Menus, **Kick-off** and **Career**: a full match to the final whistle, advancing the calendar, saving, quitting and
  reopening with the progress intact.
- 30 frames per second, or **optional 60 fps**, which makes the Mac run hotter.
- Sound, keyboard and controller.
- Options in the app:
  - macOS **Game Mode**, when playing full screen;
  - **economy mode**, with the Switch's handheld settings: 720p and less heat;
  - **"More attentive AI" (experimental)**, which turns on AI calculations the Switch version keeps in its economy mode.

### Known limitations

- The players' huddle before kick-off sometimes looks too bright.
- Gameplay is the Switch version's: some PlayStation 5 movement features are off by design.
- Work in progress.

### Building

Nothing is ready to download: everything is made on your computer from your own files. The build is still technical:
the main steps are in the Portuguese section above (`make test`, extract the base and update code with
`scripts/extract_exefs.py`, the update's RomFS over the base's, `make rewrite`, `make prepare runtime`, `make app`), and
each script explains itself with `--help`. Run them from `games/fc26`, with the Python of `requirements.txt` (`PY=`) and
a work folder outside the repository (`WORK=`).

The "FC 26.app" is only the launcher: it opens the options window and runs the game from the work folder. Profile and
saves go to `~/Library/Application Support/MacNativeGames/FC26/profile`, the log to `~/Library/Logs/MacNativeGames/fc26.log`.

### Legal

A non-commercial fan project, **not affiliated** with Electronic Arts, Nintendo or Apple. EA SPORTS FC is a trademark of
Electronic Arts; Nintendo Switch is a trademark of Nintendo. Use it only with a copy of the game you bought and keys from
your own console.

Credits: [MacNativeGames](https://github.com/ly05010419/MacNativeGames) (MIT), where the native approach comes from, and
the other projects listed in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md), among them
[nxnative](https://github.com/seedds/nxnative) (MIT).
