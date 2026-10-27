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

### Com um assistente de IA

Se você usa um assistente de IA no Terminal (Claude Code, Codex etc.), abra-o na pasta do repositório e peça para ele
instalar o FC 26. O guia dele é o [AGENTS.md](AGENTS.md): o que pedir a você, as conferências, o comando, os erros comuns
e as regras (ele nunca baixa jogo nem chaves e nunca mostra o conteúdo do `prod.keys`). Você continua tendo que fornecer
os seus próprios arquivos.

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

Mais detalhes em [games/fc26/README.md](games/fc26/README.md), em [games/fc26/docs](games/fc26/docs) e em
[CONTRIBUTING.md](CONTRIBUTING.md).

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

This project makes the **Nintendo Switch version of EA SPORTS FC 26** run **natively** on an Apple silicon Mac. It does
not use an emulator.

The build rewrites the ARM code of the game one time for the Mac. A small host answers the Switch system services. The
NVN graphics of the game operate on Metal.

The result is an app, `FC 26.app`. You build it on your Mac from your own files with one command:
`games/fc26/build.sh`.

The port operates **offline**. It does not connect to EA servers and it has no online modes.

## Legal notice

> **This repository contains no game content and no keys.** It contains no game code, art, text, audio, shaders,
> NSP/NCA files or `prod.keys`. Your computer makes all the game files from files that **you** dump from **your**
> console.

- Use the port only with **your own Nintendo Switch**, **its keys** and **a copy of FC 26 that you bought**. Dump all
  of them from your console.
- Do not ask for games or keys from other persons. Do not share or download games or keys.
- Do not distribute the app or the work folder of the build. They contain the game and are for your own use only.
- This is a non-commercial fan project. It has **no relation** with Electronic Arts, Nintendo or Apple.
- EA SPORTS FC is a trademark of Electronic Arts. Nintendo Switch is a trademark of Nintendo. Mac and macOS are
  trademarks of Apple.

## Requirements

1. **Files from your Nintendo Switch:**
   - the **console keys** (`prod.keys`), dumped from your own Switch;
   - the EA SPORTS FC 26 **1.0.0 base game** (Title ID `01004FF021942000`), as an NSP dumped from your console;
   - the **1.89.6e65 update** (v1638400), as an NSP dumped from your console. The port operates only on this version.
   - You do not need DLC.
2. **An Apple silicon Mac** (M1 or newer) with **macOS 26 or newer**. We tested the port on an 8 GB 13" M1 MacBook Pro
   with macOS 27.
3. **Memory:** 8 GB is enough. Below 16 GB, the build shows a warning. The rewrite step uses 4 to 5 GB. Close other
   apps during this step.
4. **Disk:** about **75 GB free** on the disk of the work folder. The NSP files can be on a different disk.
5. **Tools.** The build checks all the tools and tells you which tool is not on the Mac.
   - **Xcode Command Line Tools:** `xcode-select --install`.
   - **Homebrew** ([brew.sh](https://brew.sh)) with `opus` and `libvpx`: `brew install opus libvpx`.
   - **Python 3.10 or newer** (`brew install python`). The build installs the packages in
     [games/fc26/requirements.txt](games/fc26/requirements.txt) into a separate environment (`<work folder>/venv`).
   - **Internet access** during the build. The build downloads only the Python packages and SPIRV-Cross (the shader
     translator, at a fixed version). It downloads nothing from the game.

## How to build the app

You cannot download the app. You build it on your Mac. You do not need to know how to write code. Copy the commands and
paste them into the **Terminal** app (Applications › Utilities › Terminal).

1. **Install the tools** (one time only). In Terminal, run:

   ```sh
   xcode-select --install
   ```

   Install Homebrew with the instructions at [brew.sh](https://brew.sh). Then run:

   ```sh
   brew install opus libvpx python
   ```

2. **Get this repository.** In Terminal, run:

   ```sh
   git clone https://github.com/brunoamador20/fc26-mac-port.git ~/fc26-mac-port
   ```

3. **Put your files** in one folder, for example `~/FC26-files/`. You need the 1.0.0 base game NSP, the 1.89.6e65
   update NSP and `prod.keys`. Dump all of them from your console.

4. **Choose a work folder** with about 75 GB free. It must be **outside** the repository. Its path must have
   **no spaces**. For example, use `~/FC26-work`. The folder can be new.

5. **Run the build.** It is one command. Replace the file names with the names of your files:

   ```sh
   ~/fc26-mac-port/games/fc26/build.sh \
     --base   ~/FC26-files/"<base game 1.0.0>.nsp" \
     --update ~/FC26-files/"<update 1.89.6e65>.nsp" \
     --keys   ~/FC26-files/prod.keys \
     --work   ~/FC26-work \
     --app    ~/Applications/"FC 26.app"
   ```

   The build shows each step in Portuguese and in English. The build takes a long time (see the table below). Keep the
   Mac connected to power.

   **If the build stops**, read the message and correct the problem. Then **run the same command again**. The build
   skips the steps that are complete. A build can stop because of an error, a full disk, a shutdown or Ctrl-C.

   `build.sh --help` shows all the options.

6. **Play.** Double-click `FC 26.app`. The options window opens first. It has the display, full screen, resolution,
   60 fps and economy mode options. Then the game starts. The first start checks the ~38 GB of game data and takes
   more time.

> **Do not delete or move the work folder.** The app is small and reads the game from this folder. If you move the
> folder, run the build again with the new `--work`. The build cannot use the completed steps in a new folder.

### With an AI assistant

You can use an AI assistant in Terminal, for example Claude Code or Codex. Open it in the repository folder. Then ask
it to install FC 26.

[AGENTS.md](AGENTS.md) is the guide for the assistant. It tells the assistant which files to ask for, which checks to
do and how to correct the usual errors. It also gives rules: the assistant never downloads games or keys, and never
shows the contents of `prod.keys`.

You must still give your own files.

### What each step does, its time and its disk space

The times are approximate values for an M1 Mac with its internal SSD. They change with the Mac and the disk. The space
is the space that stays in the work folder.

| Step | What it does | Approximate time | Space |
|---|---|---|---|
| 1. Checks | Examines the Mac, macOS, the tools, the free space and the memory | Seconds | — |
| 2. Python environment | Makes `<work>/venv` and installs `requirements.txt` | 1 to 3 min | ~0.3 GB |
| 3. Update code | `extract_exefs.py --update` extracts the 1.89.6e65 ExeFS | Less than 1 min | Less than 1 GB |
| 4. Game data | `merge_update_romfs.py` merges the base game RomFS and the update RomFS, and checks each block | 30 min to 1.5 h | ~38 GB |
| 5. Rewrite | `make rewrite` rewrites the game code (main and sdk) for Apple silicon. It uses 4 to 5 GB of RAM. | 1 to 3 h (the longest step) | A few GB |
| 6. Video module | `make nro` extracts `Engine.Render.Core2.PlatformNvn.nro` from the RomFS and rewrites it | 5 to 20 min | Less than 1 GB |
| 7. Runtime | `make prepare` compares all files with the expected values and makes the tables. `make runtime` compiles the runtime. | 10 to 30 min | A few GB |
| 8. App | `make app` builds the launcher, the shader translator, SPIRV-Cross and `FC 26.app` | 3 to 10 min the first time | Small |
| First start | The game checks its data and makes the shader cache | A few minutes | The cache becomes larger as you play |

## Where the files are

| What | Where |
|---|---|
| The app | The `--app` path. The app is only the launcher. You can put it in `~/Applications` or `/Applications`. |
| Extracted game data and the runtime | The work folder (`--work`): `extracted/`, `rewritten/`, `build-update/` |
| Build logs | `<work>/logs/build/<step>.log` |
| Profile and saves | `~/Library/Application Support/MacNativeGames/FC26/profile` |
| Game log | `~/Library/Logs/MacNativeGames/fc26.log` |
| Shader cache | `<work>/build-update/shader-cache/rt-update` |
| App options | The app saves them at each change (domain `org.macnativegames.fc26`) |

`"FC 26.app/Contents/MacOS/FC 26" --dry-run` shows the paths and the options of the app. It does not start the game.

## Usual problems

| Message or symptom | What to do |
|---|---|
| "the Xcode Command Line Tools are not installed" | Run `xcode-select --install`. Then run the build again. |
| "/opt/homebrew/opt/opus... not found" or "...libvpx..." | Install Homebrew ([brew.sh](https://brew.sh)). Then run `brew install opus libvpx`. |
| "you must have Python 3.10 or newer", or the package installation fails | Run `brew install python` and run the build again. You can also give a different Python with `--python /path/python3`. If the problem continues, delete `<work>/venv` and run the build again. |
| "the Terminal runs under Rosetta" | Quit Terminal. In Finder, open the Get Info window of Terminal and clear "Open using Rosetta". Open Terminal again. |
| "not sufficient disk space" | Make disk space free, or use a work folder on a different disk (APFS, no spaces in the path). |
| "--work must not contain spaces" | Use a path with no spaces, for example `~/FC26-work`. |
| Step 3 or 4 fails (keys, title, hash) | Make sure that the files are the FC 26 **1.0.0** base game and the **1.89.6e65** update. Make sure that `prod.keys` is from your console and is current. |
| `make prepare` tells you that a size or a SHA-256 is different | The files are not the expected files. They are a different version, or the dump is damaged. Dump them again from your console. |
| The rewrite (step 5) stops, or the Mac becomes very slow | The Mac does not have sufficient memory. Close other apps and run the same command again. The build does only the missing work again. |
| Step 8 fails during the SPIRV-Cross download | Step 8 needs internet access. Connect the Mac and run the build again. |
| The app opens and then closes | Read the end of `~/Library/Logs/MacNativeGames/fc26.log`. The work folder must be at the same path as during the build. |
| Small stops in the first matches | The game translates new shaders the first time. The stops go away when the shader cache is full. |

[AGENTS.md](AGENTS.md) has a longer list of error messages and their corrections.

## What operates

- Menus, **Kick-off** and **Career**. You can play a full match to the final whistle and go forward in the calendar.
  You can save, quit and open the game again with your progress.
- 30 frames per second, or **optional 60 fps**. At 60 fps the Mac becomes hotter.
- Sound, keyboard and controller.
- These options in the app:
  - macOS **Game Mode**, when you play in full screen;
  - **economy mode**, with the handheld settings of the Switch: 720p and less heat;
  - **"More attentive AI" (experimental)**. It turns on AI calculations that the Switch version keeps in its economy
    mode.

## Limits

- The port operates only on version 1.89.6e65, on the 1.0.0 base game. The build does not accept other versions.
- The port has no online functions: no EA servers, no Ultimate Team and no online modes.
- The scene with the players in a circle before kick-off is sometimes too bright.
- The gameplay is the gameplay of the Switch version. Some movement functions of the PlayStation 5 version are off.
- New shaders can cause small stops the first time.
- The work on the port continues.

## For developers

`build.sh` only checks, orders and continues the targets of [games/fc26/Makefile](games/fc26/Makefile) and the scripts
in `games/fc26/scripts/`. Each script shows its options with `--help`.

The synthetic tests use no game data. To run them, use this command:

```sh
cd games/fc26 && make test PY=python3
```

For more information, read [games/fc26/README.md](games/fc26/README.md), [games/fc26/docs](games/fc26/docs) and
[CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT). The native approach comes from this
  project: the rewriter, the Horizon host, NVN on Metal and the launcher. This port adapts it for FC 26.
- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT). It started this method to run Switch games
  natively. The NSO rewriter, the host and the NVN-on-Metal layer started as its generic parts.
- **[nxnative](https://github.com/seedds/nxnative)** (MIT): variable shader constants, the GPU profiler and
  synchronization repairs.
- **Ryujinx** (MIT): the Maxwell-to-SPIR-V shader translator and parts of the audio. Its service code is a reference.
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** (Apache-2.0): SPIR-V to Metal Shading Language.
- **deko3d** (zlib), **[bcdec](https://github.com/iOrange/bcdec)** (MIT), **libopus** and **libvpx** (BSD).

[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) gives the license and the files of each project. This project uses the
MIT license ([LICENSE](LICENSE)).
