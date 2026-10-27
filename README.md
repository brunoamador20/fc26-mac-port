# EA SPORTS FC 26 (Nintendo Switch) nativo no Mac

[Português](#português) | [English](#english)

# Português

## O que é

Este projeto faz o **EA SPORTS FC 26 de Nintendo Switch** rodar **nativo** num Mac com Apple silicon, sem emulador. O
código ARM do jogo é reescrito uma vez para o Mac, um pequeno host responde pelos serviços do sistema do Switch e os
gráficos NVN do jogo são refeitos em Metal. O resultado é um app, `FC 26.app`, que você mesmo monta no seu Mac a partir
dos seus próprios arquivos, com um único comando: `games/fc26/build.sh`.

O port roda **offline**: sem os servidores da EA e sem os modos online.

## Aviso legal

> **Este repositório não contém nada do jogo e nenhuma chave**: nenhum programa, arte, texto, áudio, shader, NSP/NCA ou
> `prod.keys`. Tudo que o jogo precisa é gerado no seu computador, a partir de arquivos que **você** tira do **seu**
> console.

- Use só com **o seu próprio Nintendo Switch**, **as chaves dele** e **uma cópia do FC 26 que você comprou**, tudo
  extraído do seu console.
- Não peça, não compartilhe e não baixe jogo ou chaves de terceiros. Não distribua o app nem a pasta de trabalho que o
  build gera: eles contêm o jogo e são só para o seu uso.
- Projeto de fã, sem fins lucrativos e **sem relação** com a Electronic Arts, a Nintendo ou a Apple. EA SPORTS FC é
  marca da Electronic Arts; Nintendo Switch é marca da Nintendo; Mac e macOS são marcas da Apple.

## Requisitos

1. **Do seu Nintendo Switch:**
   - as **chaves do console** (`prod.keys`), extraídas do seu próprio Switch;
   - o **jogo base 1.0.0** do EA SPORTS FC 26 (Title ID `01004FF021942000`), em NSP extraído do seu console;
   - a **atualização 1.89.6e65** (v1638400), em NSP extraído do seu console. É a versão em que o port roda;
   - DLC não é necessário.
2. **Um Mac com Apple silicon** (M1 ou mais novo) e **macOS 26 ou mais novo**. Testado num MacBook Pro 13" M1 de 8 GB
   com macOS 27.
3. **Memória:** 8 GB funcionam. Com menos de 16 GB o build avisa: a etapa de reescrita usa 4 a 5 GB, então feche os
   outros apps enquanto ela roda.
4. **Disco:** cerca de **75 GB livres** no disco da pasta de trabalho (os NSPs podem ficar em outro disco).
5. **Ferramentas** (o build confere todas e diz o que falta):
   - **Command Line Tools do Xcode:** `xcode-select --install`;
   - **Homebrew** ([brew.sh](https://brew.sh)) com `opus` e `libvpx`: `brew install opus libvpx`;
   - **Python 3.10 ou mais novo** (`brew install python`). Os pacotes de
     [games/fc26/requirements.txt](games/fc26/requirements.txt) são instalados sozinhos num ambiente próprio
     (`<pasta de trabalho>/venv`);
   - **internet** durante o build, só para os pacotes Python e para baixar e compilar o SPIRV-Cross (tradutor de
     shaders, numa versão fixa). Nada do jogo é baixado.

## Como montar, passo a passo

Não há nada pronto para baixar: o app é montado no seu Mac. Você não precisa saber programar; basta copiar e colar os
comandos no app **Terminal** (Aplicativos › Utilitários › Terminal).

1. **Instale as ferramentas** (uma vez só). No Terminal:

   ```sh
   xcode-select --install
   ```

   Instale o Homebrew seguindo as instruções de [brew.sh](https://brew.sh) e depois:

   ```sh
   brew install opus libvpx python
   ```

2. **Baixe este repositório.** No Terminal:

   ```sh
   git clone https://github.com/brunoamador20/fc26-mac-port.git ~/fc26-mac-port
   ```

3. **Separe os seus arquivos** numa pasta, por exemplo `~/FC26-arquivos/`: o NSP do jogo base 1.0.0, o NSP da
   atualização 1.89.6e65 e o `prod.keys`, todos tirados do seu console.

4. **Escolha uma pasta de trabalho** com ~75 GB livres, **fora** do repositório e **sem espaços** no caminho, por
   exemplo `~/FC26-trabalho`. Ela não precisa existir.

5. **Rode o build** (é um comando só; troque os nomes dos arquivos pelos seus):

   ```sh
   ~/fc26-mac-port/games/fc26/build.sh \
     --base   ~/FC26-arquivos/"<jogo base 1.0.0>.nsp" \
     --update ~/FC26-arquivos/"<atualização 1.89.6e65>.nsp" \
     --keys   ~/FC26-arquivos/prod.keys \
     --work   ~/FC26-trabalho \
     --app    ~/Applications/"FC 26.app"
   ```

   O build mostra cada etapa em português e em inglês. Ele demora (veja a tabela abaixo); deixe o Mac ligado na
   tomada. **Se parar no meio** (erro, falta de espaço, Mac desligado, Ctrl-C), corrija o que a mensagem disser e
   **rode exatamente o mesmo comando de novo**: as etapas já prontas são puladas.

   `build.sh --help` mostra todas as opções.

6. **Jogue:** abra o `FC 26.app` com dois cliques. Aparece a janela de opções (monitor, tela cheia, resolução, 60 fps,
   modo economia...) e depois o jogo. A primeira abertura confere os ~38 GB de dados do jogo e demora mais.

> **Não apague nem mova a pasta de trabalho.** O app é pequeno e lê o jogo de lá. Se mover a pasta, rode o build de
> novo com o novo `--work` (as etapas já feitas não são aproveitadas numa pasta nova).

### O que cada etapa faz, quanto demora e quanto ocupa

Os tempos são **estimativas aproximadas** para um Mac M1 com SSD interno; variam com o Mac e o disco. O espaço é o que
fica na pasta de trabalho.

| Etapa | O que faz | Tempo aproximado | Espaço |
|---|---|---|---|
| 1. Conferências | Mac, macOS, ferramentas, espaço livre, memória | segundos | — |
| 2. Ambiente Python | cria `<work>/venv` e instala `requirements.txt` | 1 a 3 min | ~0,3 GB |
| 3. Código da atualização | `extract_exefs.py --update`: o ExeFS da 1.89.6e65 | menos de 1 min | < 1 GB |
| 4. Dados do jogo | `merge_update_romfs.py`: a RomFS do jogo base com a da atualização, conferida bloco a bloco | 30 min a 1 h 30 | ~38 GB |
| 5. Reescrita | `make rewrite`: o código do jogo (main e sdk) reescrito para o Apple silicon; usa 4 a 5 GB de RAM | 1 a 3 h (a mais longa) | alguns GB |
| 6. Módulo de vídeo | `make nro`: tira o `Engine.Render.Core2.PlatformNvn.nro` da RomFS e o reescreve | 5 a 20 min | < 1 GB |
| 7. Runtime | `make prepare` confere tudo contra os valores esperados e gera as tabelas; `make runtime` compila | 10 a 30 min | alguns GB |
| 8. App | `make app`: lançador, tradutor de shaders, SPIRV-Cross e o `FC 26.app` | 3 a 10 min na primeira vez | pequeno |
| Primeira abertura | o jogo confere os dados e cria o cache de shaders | alguns minutos | o cache cresce com o uso |

## Onde ficam as coisas

| O quê | Onde |
|---|---|
| O app | onde você mandou com `--app` (é só o lançador; pode ficar em `~/Applications` ou `/Applications`) |
| Os dados do jogo extraídos e o runtime | a pasta de trabalho (`--work`): `extracted/`, `rewritten/`, `build-update/` |
| Logs do build | `<work>/logs/build/<etapa>.log` |
| Perfil e saves | `~/Library/Application Support/MacNativeGames/FC26/profile` |
| Log do jogo | `~/Library/Logs/MacNativeGames/fc26.log` |
| Cache de shaders | `<work>/build-update/shader-cache/rt-update` |
| Opções do app | salvas a cada mudança (domínio `org.macnativegames.fc26`) |

`"FC 26.app/Contents/MacOS/FC 26" --dry-run` mostra o que o app faria (caminhos e opções) sem abrir o jogo.

## Problemas comuns

| Mensagem ou sintoma | O que fazer |
|---|---|
| "faltam as Command Line Tools do Xcode" | `xcode-select --install` e rode o build de novo. |
| "falta /opt/homebrew/opt/opus..." ou "...libvpx..." | Instale o Homebrew ([brew.sh](https://brew.sh)) e `brew install opus libvpx`. |
| "precisa de Python 3.10 ou mais novo" ou erro na instalação dos pacotes | `brew install python` e rode de novo; ou passe outro Python com `--python /caminho/python3`. Se o erro continuar, apague `<work>/venv` e rode de novo. |
| "o Terminal está rodando pelo Rosetta" | Feche o Terminal, desmarque "Abrir com o Rosetta" nas informações dele (Finder › Obter Informações) e abra de novo. |
| "pouco espaço" | Libere espaço ou use uma pasta de trabalho em outro disco (APFS, sem espaços no caminho). |
| "--work não pode ter espaços" | Use um caminho sem espaços, como `~/FC26-trabalho`. |
| Falha na etapa 3 ou 4 (chaves, título, hash) | Confira se são o jogo base **1.0.0** e a atualização **1.89.6e65** do FC 26, e se o `prod.keys` é do seu console e está atualizado. |
| `make prepare` diz que um tamanho ou SHA-256 não confere | Os arquivos não são exatamente os esperados (outra versão ou extração com problema). Extraia de novo do console. |
| A reescrita (etapa 5) para ou o Mac fica muito lento | Falta de memória: feche os outros apps e rode o mesmo comando; só o que faltou é refeito. |
| A etapa 8 falha ao baixar o SPIRV-Cross | Precisa de internet só nessa hora; conecte e rode de novo. |
| O app abre e fecha | Veja o fim de `~/Library/Logs/MacNativeGames/fc26.log`. A pasta de trabalho precisa estar no mesmo lugar do build. |
| Engasgos nas primeiras partidas | Shaders sendo traduzidos pela primeira vez; somem com o cache. |

## O que funciona

- Menus, **Pontapé de saída** e **Carreira**: partida inteira até o apito final, avanço no calendário, salvar, fechar e
  reabrir com o progresso certo.
- 30 quadros por segundo, ou **60 fps opcional**, que esquenta mais o Mac.
- Som, teclado e controle.
- No app, as opções:
  - **modo jogo** do macOS, ao jogar em tela cheia;
  - **modo economia**, com as configurações de portátil do Switch: 720p e menos calor;
  - **"IA mais atenta" (experimental)**, que liga cálculos de inteligência que a versão de Switch deixa no modo
    econômico.

## Limitações

- Só a versão 1.89.6e65 (sobre o jogo base 1.0.0). Outras versões não são aceitas pelo build.
- Nada online: sem servidores da EA, sem Ultimate Team, sem modos online.
- A cena dos jogadores em roda antes da partida às vezes sai clara demais.
- A jogabilidade é a da versão de Switch: alguns recursos de movimento da versão de PlayStation 5 vêm desligados de
  fábrica.
- Shaders novos podem causar pequenos engasgos na primeira vez.
- Projeto em andamento.

## Para quem desenvolve

O build.sh só confere, ordena e retoma os alvos do [games/fc26/Makefile](games/fc26/Makefile) e os scripts de
`games/fc26/scripts/` (cada um explica a si mesmo com `--help`). Testes sintéticos, sem nada do jogo:

```sh
cd games/fc26 && make test PY=python3
```

Mais detalhes em [games/fc26/README.md](games/fc26/README.md) e em [games/fc26/docs](games/fc26/docs). As outras pastas
de `games/`, o `build_app.py` e o `docs/` da raiz vêm do projeto de origem e não fazem parte do build do FC 26.

## Créditos

- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT), de onde vem o caminho nativo (reescritor,
  host do Horizon, NVN sobre Metal, lançador) que este port adaptou para o FC 26.
- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT), que criou essa forma de rodar jogos de Switch
  nativos: o reescritor de NSO, o host e a camada NVN sobre Metal começaram nas partes genéricas dele.
- **[nxnative](https://github.com/seedds/nxnative)** (MIT): constantes variáveis de shader, profiler de GPU e correções
  de sincronização.
- **Ryujinx** (MIT): o tradutor de shaders Maxwell para SPIR-V e partes do áudio; o código de serviços como referência.
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** (Apache-2.0): SPIR-V para Metal Shading Language.
- **deko3d** (zlib), **[bcdec](https://github.com/iOrange/bcdec)** (MIT), **libopus** e **libvpx** (BSD).

Licenças e arquivos de cada um: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Este projeto: MIT
([LICENSE](LICENSE)).

---

# English

## What it is

This project runs the **Nintendo Switch version of EA SPORTS FC 26** **natively** on an Apple silicon Mac, with no
emulator. The game's ARM code is rewritten once for the Mac, a small host answers for the Switch's system services and
the game's NVN graphics are rebuilt on Metal. The result is an app, `FC 26.app`, that you build yourself on your Mac
from your own files with a single command: `games/fc26/build.sh`.

The port runs **offline**: no EA servers and no online modes.

## Legal

> **This repository contains no game content and no keys**: no program, art, text, audio, shaders, NSP/NCA or
> `prod.keys`. Everything the game needs is made on your computer from files **you** dump from **your** console.

- Use it only with **your own Nintendo Switch**, **its keys** and **a copy of FC 26 you bought**, all dumped from your
  console.
- Do not ask for, share or download games or keys from anyone else. Do not distribute the app or the work folder the
  build makes: they contain the game and are for your own use only.
- A non-commercial fan project, **not affiliated** with Electronic Arts, Nintendo or Apple. EA SPORTS FC is a trademark
  of Electronic Arts; Nintendo Switch is a trademark of Nintendo; Mac and macOS are trademarks of Apple.

## Requirements

1. **From your Nintendo Switch:**
   - the **console keys** (`prod.keys`), dumped from your own Switch;
   - the EA SPORTS FC 26 **1.0.0 base game** (Title ID `01004FF021942000`), as an NSP dumped from your console;
   - the **1.89.6e65 update** (v1638400), as an NSP dumped from your console. The port runs on that version;
   - no DLC is needed.
2. **An Apple silicon Mac** (M1 or newer) with **macOS 26 or newer**. Tested on an 8 GB 13" M1 MacBook Pro with
   macOS 27.
3. **Memory:** 8 GB works. Below 16 GB the build warns you: the rewrite step uses 4 to 5 GB, so close other apps while
   it runs.
4. **Disk:** about **75 GB free** on the work folder's disk (the NSPs can be on another disk).
5. **Tools** (the build checks them all and says what is missing):
   - **Xcode Command Line Tools:** `xcode-select --install`;
   - **Homebrew** ([brew.sh](https://brew.sh)) with `opus` and `libvpx`: `brew install opus libvpx`;
   - **Python 3.10 or newer** (`brew install python`). The packages in
     [games/fc26/requirements.txt](games/fc26/requirements.txt) are installed automatically into their own environment
     (`<work folder>/venv`);
   - **internet** during the build, only for the Python packages and to download and compile SPIRV-Cross (the shader
     translator, at a pinned version). Nothing from the game is downloaded.

## Building, step by step

Nothing is ready to download: the app is built on your Mac. You do not need to know how to program; just copy and paste
the commands into the **Terminal** app (Applications › Utilities › Terminal).

1. **Install the tools** (once). In Terminal:

   ```sh
   xcode-select --install
   ```

   Install Homebrew following the instructions at [brew.sh](https://brew.sh), then:

   ```sh
   brew install opus libvpx python
   ```

2. **Get this repository.** In Terminal:

   ```sh
   git clone https://github.com/brunoamador20/fc26-mac-port.git ~/fc26-mac-port
   ```

3. **Put your files** in one folder, for example `~/FC26-files/`: the 1.0.0 base game NSP, the 1.89.6e65 update NSP and
   `prod.keys`, all dumped from your console.

4. **Pick a work folder** with ~75 GB free, **outside** the repository and with **no spaces** in its path, for example
   `~/FC26-work`. It does not need to exist yet.

5. **Run the build** (a single command; replace the file names with yours):

   ```sh
   ~/fc26-mac-port/games/fc26/build.sh \
     --base   ~/FC26-files/"<base game 1.0.0>.nsp" \
     --update ~/FC26-files/"<update 1.89.6e65>.nsp" \
     --keys   ~/FC26-files/prod.keys \
     --work   ~/FC26-work \
     --app    ~/Applications/"FC 26.app"
   ```

   The build shows each step in Portuguese and English. It takes a while (see the table below); keep the Mac plugged in.
   **If it stops halfway** (an error, no disk space, the Mac shut down, Ctrl-C), fix what the message says and **run
   exactly the same command again**: finished steps are skipped.

   `build.sh --help` lists every option.

6. **Play:** double-click `FC 26.app`. The options window opens (display, full screen, resolution, 60 fps, economy
   mode...) and then the game. The first launch checks the ~38 GB of game data and takes longer.

> **Do not delete or move the work folder.** The app is small and reads the game from there. If you move the folder,
> run the build again with the new `--work` (finished steps are not reused in a new folder).

### What each step does, how long it takes and how much space it uses

Times are **rough estimates** for an M1 Mac with its internal SSD; they vary with the Mac and the disk. Space is what
stays in the work folder.

| Step | What it does | Approximate time | Space |
|---|---|---|---|
| 1. Checks | Mac, macOS, tools, free space, memory | seconds | — |
| 2. Python environment | creates `<work>/venv` and installs `requirements.txt` | 1 to 3 min | ~0.3 GB |
| 3. Update code | `extract_exefs.py --update`: the 1.89.6e65 ExeFS | under 1 min | < 1 GB |
| 4. Game data | `merge_update_romfs.py`: the base game's RomFS merged with the update's, checked block by block | 30 min to 1.5 h | ~38 GB |
| 5. Rewrite | `make rewrite`: the game code (main and sdk) rewritten for Apple silicon; uses 4 to 5 GB of RAM | 1 to 3 h (the longest) | a few GB |
| 6. Video module | `make nro`: takes `Engine.Render.Core2.PlatformNvn.nro` out of the RomFS and rewrites it | 5 to 20 min | < 1 GB |
| 7. Runtime | `make prepare` checks everything against the expected values and generates the tables; `make runtime` compiles | 10 to 30 min | a few GB |
| 8. App | `make app`: launcher, shader translator, SPIRV-Cross and `FC 26.app` | 3 to 10 min the first time | small |
| First launch | the game checks its data and builds the shader cache | a few minutes | the cache grows with play |

## Where things are

| What | Where |
|---|---|
| The app | wherever `--app` said (it is only the launcher; `~/Applications` or `/Applications` work) |
| Extracted game data and the runtime | the work folder (`--work`): `extracted/`, `rewritten/`, `build-update/` |
| Build logs | `<work>/logs/build/<step>.log` |
| Profile and saves | `~/Library/Application Support/MacNativeGames/FC26/profile` |
| Game log | `~/Library/Logs/MacNativeGames/fc26.log` |
| Shader cache | `<work>/build-update/shader-cache/rt-update` |
| App options | saved at every change (domain `org.macnativegames.fc26`) |

`"FC 26.app/Contents/MacOS/FC 26" --dry-run` prints what the app would do (paths and options) without starting the game.

## Common problems

| Message or symptom | What to do |
|---|---|
| "the Xcode Command Line Tools are missing" | `xcode-select --install`, then run the build again. |
| "/opt/homebrew/opt/opus... is missing" or "...libvpx..." | Install Homebrew ([brew.sh](https://brew.sh)) and `brew install opus libvpx`. |
| "needs Python 3.10 or newer" or the package install fails | `brew install python` and run again, or pass another Python with `--python /path/python3`. If it still fails, delete `<work>/venv` and run again. |
| "the Terminal runs under Rosetta" | Quit Terminal, untick "Open using Rosetta" in its Get Info window in Finder, and open it again. |
| "not enough space" | Free some space or use a work folder on another disk (APFS, no spaces in the path). |
| "--work cannot contain spaces" | Use a path without spaces, such as `~/FC26-work`. |
| Step 3 or 4 fails (keys, title, hash) | Check that these are FC 26's **1.0.0** base game and **1.89.6e65** update, and that `prod.keys` is from your console and up to date. |
| `make prepare` says a size or SHA-256 does not match | The files are not exactly the expected ones (another version or a bad dump). Dump them again from your console. |
| The rewrite (step 5) stops or the Mac becomes very slow | Out of memory: close other apps and run the same command; only what is missing is redone. |
| Step 8 fails downloading SPIRV-Cross | It needs internet at that moment only; connect and run again. |
| The app opens and closes | Read the end of `~/Library/Logs/MacNativeGames/fc26.log`. The work folder must be where it was at build time. |
| Stutter in the first matches | Shaders being translated the first time; it goes away as the cache fills. |

## What works

- Menus, **Kick-off** and **Career**: a full match to the final whistle, advancing the calendar, saving, quitting and
  reopening with the progress intact.
- 30 frames per second, or **optional 60 fps**, which makes the Mac run hotter.
- Sound, keyboard and controller.
- Options in the app:
  - macOS **Game Mode**, when playing full screen;
  - **economy mode**, with the Switch's handheld settings: 720p and less heat;
  - **"More attentive AI" (experimental)**, which turns on AI calculations the Switch version keeps in its economy mode.

## Limitations

- Only version 1.89.6e65 (on top of the 1.0.0 base game). The build accepts no other version.
- Nothing online: no EA servers, no Ultimate Team, no online modes.
- The players' huddle before kick-off sometimes looks too bright.
- Gameplay is the Switch version's: some PlayStation 5 movement features are off by design.
- New shaders can cause small stutters the first time.
- Work in progress.

## For developers

build.sh only checks, orders and resumes the targets of [games/fc26/Makefile](games/fc26/Makefile) and the scripts in
`games/fc26/scripts/` (each explains itself with `--help`). Synthetic tests, with no game data:

```sh
cd games/fc26 && make test PY=python3
```

More in [games/fc26/README.md](games/fc26/README.md) and [games/fc26/docs](games/fc26/docs). The other folders under
`games/`, `build_app.py` and the top-level `docs/` come from the upstream project and are not part of the FC 26 build.

## Credits

- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT), where the native approach comes from (rewriter,
  Horizon host, NVN on Metal, launcher), adapted here for FC 26.
- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT), which created this way of running Switch games
  natively: the NSO rewriter, the host and the NVN-on-Metal layer started as its generic parts.
- **[nxnative](https://github.com/seedds/nxnative)** (MIT): variable shader constants, the GPU profiler and
  synchronization fixes.
- **Ryujinx** (MIT): the Maxwell-to-SPIR-V shader translator and parts of the audio; its service code as a reference.
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** (Apache-2.0): SPIR-V to Metal Shading Language.
- **deko3d** (zlib), **[bcdec](https://github.com/iOrange/bcdec)** (MIT), **libopus** and **libvpx** (BSD).

Licenses and files for each: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This project: MIT ([LICENSE](LICENSE)).
