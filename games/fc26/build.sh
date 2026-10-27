#!/bin/bash
# FC 26 para Mac, de ponta a ponta: dos arquivos do seu console até o "FC 26.app". Retomável: rode de novo o mesmo comando
# depois de uma falha ou interrupção e as etapas já prontas são puladas.
# FC 26 for Mac: this script makes "FC 26.app" from the files of your console. If the script stops, run the same command
# again. The script skips the steps that are complete.
#
#   games/fc26/build.sh --base <base 1.0.0.nsp> --update <update 1.89.6e65.nsp> --keys <prod.keys> \
#                       --work <pasta de trabalho> --app "<pasta>/FC 26.app"
#
# Etapas / steps (the Makefile and the scripts do the work; this file only checks, orders and resumes them):
#   1. Mac, macOS, ferramentas, espaço / Mac, macOS, tools, disk space    5. make rewrite (main, sdk)
#   2. venv Python em <work>/venv (requirements.txt)                       6. make nro (Engine.Render.Core2.PlatformNvn.nro)
#   3. scripts/extract_exefs.py --update -> extracted/v1638400/exefs       7. make prepare runtime OUT=<work>/build-update
#   4. scripts/merge_update_romfs.py     -> extracted/v1638400/romfs       8. make app
# The keys are only passed to the extractors by path: this script never reads or prints them.
set -uo pipefail

FC26_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$FC26_DIR/../.." && pwd -P)"
NEED_GB=45          # só a pasta de trabalho: RomFS 38 GB + reescrita, compilação e cache (os NSPs ficam fora) / work folder only
MIN_RAM_GB=16
MIN_MACOS=26

usage() {
	cat <<'EOF'
Uso / Usage:
  games/fc26/build.sh --base <jogo base 1.0.0.nsp> --update <atualização 1.89.6e65.nsp> \
                      --keys <prod.keys> --work <pasta de trabalho> --app "<pasta>/FC 26.app"

  --base     o jogo base 1.0.0, extraído do seu console / the 1.0.0 base game, from your console
  --update   a atualização 1.89.6e65 (v1638400), extraída do seu console / the 1.89.6e65 update, from your console
  --keys     prod.keys do seu próprio Switch / prod.keys from your own Switch
  --work     pasta de trabalho (~75 GB livres, sem espaços no caminho, fora do repositório)
             work folder (~75 GB free, no spaces in the path, outside the repository)
  --app      onde criar o app, terminando em .app / the path of the app; it must end in .app
  --python   opcional: o Python 3 usado para criar o venv (padrão: python3)
             optional: the Python 3 that makes the venv (default: python3)
  -h, --help esta ajuda / this help

Retomável: rode o mesmo comando de novo e as etapas prontas são puladas. Logs em <work>/logs/build/.
If the build stops, run the same command again. The build skips the completed steps. Logs: <work>/logs/build/.
EOF
}

say()  { printf '\n==> %s\n    %s\n' "$1" "$2"; }
info() { printf '    %s\n    %s\n' "$1" "$2"; }
warn() { printf '\n!!  AVISO: %s\n    WARNING: %s\n' "$1" "$2" >&2; }
die()  { printf '\nERRO: %s\nERROR: %s\n' "$1" "$2" >&2; exit 1; }

trap 'printf "\nInterrompido. Rode o mesmo comando de novo para continuar de onde parou.\nThe build stopped. Run the same command again to continue.\n" >&2; exit 130' INT TERM

# --- argumentos / arguments ---
BASE= UPDATE= KEYS= WORK= APP= PYTHON="${PYTHON:-python3}"
[ $# -eq 0 ] && { usage; exit 2; }
while [ $# -gt 0 ]; do
	case "$1" in
		-h|--help) usage; exit 0 ;;
		--base|--update|--keys|--work|--app|--python)
			[ $# -ge 2 ] && [ -n "$2" ] || die "$1 precisa de um valor." "$1 must have a value."
			case "$1" in
				--base) BASE="$2" ;; --update) UPDATE="$2" ;; --keys) KEYS="$2" ;;
				--work) WORK="$2" ;; --app) APP="$2" ;; --python) PYTHON="$2" ;;
			esac
			shift 2 ;;
		*) usage >&2; die "opção desconhecida: $1" "unknown option: $1" ;;
	esac
done
for pair in "--base:$BASE" "--update:$UPDATE" "--keys:$KEYS" "--work:$WORK" "--app:$APP"; do
	[ -n "${pair#*:}" ] || { usage >&2; die "falta ${pair%%:*}." "Give ${pair%%:*}."; }
done

# Caminho absoluto de algo cuja pasta-mãe existe / absolute path of something whose parent folder exists.
abspath() { local d; d="$(cd "$(dirname "$1")" 2>/dev/null && pwd -P)" || return 1; printf '%s/%s\n' "$d" "$(basename "$1")"; }
inside_repo() { case "$1/" in "$REPO_DIR"/*) return 0 ;; esac; return 1; }

check_input() {   # $1 option, $2 path
	[ -e "$2" ] || die "$1: arquivo não encontrado: $2" "$1: file not found: $2"
	[ -f "$2" ] || die "$1: não é um arquivo: $2" "$1: not a file: $2"
	[ -r "$2" ] || die "$1: sem permissão de leitura: $2" "$1: cannot read the file: $2"
	[ -s "$2" ] || die "$1: arquivo vazio: $2" "$1: the file is empty: $2"
}
check_input --base "$BASE"
check_input --update "$UPDATE"
check_input --keys "$KEYS"
BASE="$(abspath "$BASE")"; UPDATE="$(abspath "$UPDATE")"; KEYS="$(abspath "$KEYS")"
[ "$BASE" != "$UPDATE" ] || die "--base e --update são o mesmo arquivo." "--base and --update are the same file."

case "$WORK" in *[[:space:]]*) die "--work não pode ter espaços no caminho (o Makefile não aceita): $WORK" \
	"--work must not contain spaces, because the Makefile cannot use them: $WORK" ;; esac
parent="$(dirname "$WORK")"
WORK="$(abspath "$WORK")" || die "--work: a pasta onde ela ficaria não existe: $parent" \
	"--work: its parent folder does not exist: $parent"
[ ! -e "$WORK" ] || [ -d "$WORK" ] || die "--work existe e não é uma pasta: $WORK" "--work is not a folder: $WORK"
inside_repo "$WORK" && die "--work tem que ficar fora do repositório (lá vão dados do jogo): $WORK" \
	"--work must be outside the repository, because it will contain game data: $WORK"

case "$APP" in *.app) ;; *) die "--app tem que terminar em .app: $APP" "--app must end in .app: $APP" ;; esac
parent="$(dirname "$APP")"
APP="$(abspath "$APP")" || die "--app: a pasta onde ele ficaria não existe: $parent" \
	"--app: its parent folder does not exist: $parent"
inside_repo "$APP" && die "--app tem que ficar fora do repositório: $APP" "--app must be outside the repository: $APP"
if [ -e "$APP" ]; then   # make app apaga e recria o app: só aceite um FC 26.app feito por este build
	/usr/libexec/PlistBuddy -c 'Print :FC26WorkFolder' "$APP/Contents/Info.plist" >/dev/null 2>&1 || die \
		"$APP já existe e não é um FC 26.app feito por este build; escolha outro caminho ou apague-o você mesmo." \
		"$APP exists and this build did not make it. Use a different path, or delete it yourself."
fi

# --- 1. o Mac / the Mac ---
say "Conferindo o Mac" "Check: the Mac"
[ "$(uname -s)" = Darwin ] || die "isto só roda no macOS." "this script runs only on macOS."
[ "$(uname -m)" = arm64 ] || die "precisa de um Mac com Apple silicon (M1 ou mais novo)." "you must use an Apple silicon Mac (M1 or newer)."
[ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" != 1 ] || die \
	"o Terminal está rodando pelo Rosetta (Intel); abra-o sem o Rosetta." "the Terminal runs under Rosetta (Intel). Open the Terminal without Rosetta."
MACOS="$(sw_vers -productVersion)"
[ "${MACOS%%.*}" -ge "$MIN_MACOS" ] 2>/dev/null || die "precisa do macOS $MIN_MACOS ou mais novo (este é o $MACOS)." \
	"you must have macOS $MIN_MACOS or newer. This Mac has macOS $MACOS."
RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
info "macOS $MACOS, $RAM_GB GB de RAM" "macOS $MACOS, $RAM_GB GB of RAM"
[ "$RAM_GB" -ge "$MIN_RAM_GB" ] || warn \
	"$RAM_GB GB de RAM: funciona, mas a reescrita (etapa 5) usa 4 a 5 GB. Feche os outros apps durante ela." \
	"$RAM_GB GB of RAM is enough, but the rewrite (step 5) uses 4 to 5 GB. Close other apps during step 5."

# --- ferramentas / tools ---
say "Conferindo as ferramentas" "Check: the tools"
xcrun --find clang >/dev/null 2>&1 || die "faltam as Command Line Tools do Xcode. Instale com: xcode-select --install" \
	"the Mac does not have the Xcode Command Line Tools. Install them with: xcode-select --install"
for t in make git codesign; do
	command -v "$t" >/dev/null 2>&1 || die "falta o comando '$t' (vem com as Command Line Tools: xcode-select --install)." \
		"the Mac does not have the '$t' command. Install the Command Line Tools: xcode-select --install"
done
for lib in opus/lib/libopus.a opus/include/opus libvpx/lib/libvpx.a libvpx/include; do   # caminhos fixos do Makefile
	[ -e "/opt/homebrew/opt/$lib" ] || die "falta /opt/homebrew/opt/$lib. Instale o Homebrew (https://brew.sh) e rode: brew install opus libvpx" \
		"/opt/homebrew/opt/$lib not found. Install Homebrew (https://brew.sh), then run: brew install opus libvpx"
done
command -v "$PYTHON" >/dev/null 2>&1 || die "Python 3 não encontrado ('$PYTHON'). Instale com: brew install python" \
	"Python 3 not found ('$PYTHON'). Install it with: brew install python"
"$PYTHON" -c 'import sys, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || die \
	"precisa de Python 3.10 ou mais novo com venv ('$PYTHON' é $("$PYTHON" -V 2>&1)). Instale com: brew install python" \
	"you must have Python 3.10 or newer with venv. '$PYTHON' is $("$PYTHON" -V 2>&1). Install it with: brew install python"
info "clang, make, git, codesign, opus, libvpx, $("$PYTHON" -V 2>&1): ok" "clang, make, git, codesign, opus, libvpx, $("$PYTHON" -V 2>&1): ok"

# --- espaço / disk space ---
say "Conferindo o espaço em disco" "Check: disk space"
probe="$WORK"; [ -d "$probe" ] || probe="$(dirname "$WORK")"
FREE_GB=$(( $(df -Pk "$probe" | awk 'NR==2 {print $4}') / 1048576 ))
USED_GB=0; [ -d "$WORK" ] && USED_GB=$(( $(du -sk "$WORK" | awk '{print $1}') / 1048576 ))
WANT_GB=$(( NEED_GB - USED_GB )); [ "$WANT_GB" -ge 5 ] || WANT_GB=5
info "livre: $FREE_GB GB; já na pasta de trabalho: $USED_GB GB; faltam: ~$WANT_GB GB" \
	"free: $FREE_GB GB. In the work folder: $USED_GB GB. Necessary: ~$WANT_GB GB more."
[ "$FREE_GB" -ge "$WANT_GB" ] || die "pouco espaço: $FREE_GB GB livres em $probe, precisa de ~$WANT_GB GB." \
	"not enough disk space: $FREE_GB GB free at $probe. The build needs ~$WANT_GB GB."

mkdir -p "$WORK/logs/build" || die "não consegui criar $WORK" "cannot make the folder $WORK"
LOGS="$WORK/logs/build"

# Roda uma etapa com log / runs a step with a log: step <log name> <pt> <en> <command...>
step() {
	local name="$1" pt="$2" en="$3"; shift 3
	local log="$LOGS/$name.log"
	say "$pt" "$en"
	info "log: $log" "log: $log"
	{ printf '# %s\n# ' "$(date '+%Y-%m-%d %H:%M:%S')"; printf '%q ' "$@"; printf '\n'; } >>"$log"
	"$@" 2>&1 | tee -a "$log"
	local s=${PIPESTATUS[0]}
	[ "$s" -eq 0 ] || die "a etapa '$name' falhou (código $s). Veja o fim de $log. Corrigido o problema, rode o mesmo comando de novo." \
		"step '$name' failed (exit $s). Read the end of $log. Correct the problem, then run the same command again."
}
skip() { say "$1 (pronto, pulando)" "$2 (complete, skipped)"; }

# --- 2. venv ---
VENV="$WORK/venv"
PY="$VENV/bin/python"
REQ="$FC26_DIR/requirements.txt"
if [ ! -x "$PY" ]; then
	step venv "Criando o ambiente Python em $VENV" "Step 2: the Python environment in $VENV" "$PYTHON" -m venv "$VENV"
fi
if [ ! -f "$VENV/.requirements-ok" ] || [ "$REQ" -nt "$VENV/.requirements-ok" ]; then
	step pip "Instalando os pacotes Python (requirements.txt)" "Step 2: installation of the Python packages (requirements.txt)" \
		"$PY" -m pip install --disable-pip-version-check -r "$REQ"
	"$PY" -c 'import cryptography, lz4.block, capstone' 2>/dev/null || die \
		"os pacotes Python não carregaram; veja $LOGS/pip.log" "the Python packages do not load. Read $LOGS/pip.log"
	cp "$REQ" "$VENV/.requirements-ok"
else
	skip "Pacotes Python" "Python packages"
fi

MAKE_VARS=(PY="$PY" WORK="$WORK")
VERSION="$("$PY" "$FC26_DIR/scripts/game_config.py" version_dir)" || die "scripts/game_config.py falhou." "scripts/game_config.py failed."
MODULES="$("$PY" "$FC26_DIR/scripts/game_config.py" modules)" || die "scripts/game_config.py falhou." "scripts/game_config.py failed."
EXTRACTED="$WORK/extracted/$VERSION"
REWRITTEN="$WORK/rewritten/$VERSION"
OUT="$WORK/build-update"
mkdir -p "$EXTRACTED"

json_pass() { [ -f "$1" ] && "$PY" -c 'import json, sys; sys.exit(json.load(open(sys.argv[1])).get("status") != "pass")' "$1" 2>/dev/null; }

# --- 3. ExeFS da atualização / the update's ExeFS ---
# extract_exefs.py escreve extraction-manifest.json depois dos arquivos: com ele, a extração terminou.
if [ -f "$EXTRACTED/extraction-manifest.json" ] && [ -f "$EXTRACTED/exefs/main" ]; then
	skip "Etapa 3: código da atualização (ExeFS)" "Step 3: the update's code (ExeFS)"
else
	rm -rf "$EXTRACTED/exefs" "$EXTRACTED/extraction-manifest.json"   # restos de uma extração interrompida
	step exefs "Etapa 3: extraindo o código da atualização (ExeFS, menos de 1 minuto)" \
		"Step 3: extraction of the update code (ExeFS, less than 1 minute)" \
		"$PY" "$FC26_DIR/scripts/extract_exefs.py" "$UPDATE" --keys "$KEYS" --update --output "$EXTRACTED/exefs"
fi

# --- 4. RomFS: jogo base + atualização / base game + update ---
if json_pass "$EXTRACTED/romfs/index.json"; then
	skip "Etapa 4: dados do jogo (RomFS)" "Step 4: game data (RomFS)"
else
	if [ -e "$EXTRACTED/romfs" ]; then
		warn "$EXTRACTED/romfs ficou incompleta de uma execução anterior; apagando e refazendo." \
			"$EXTRACTED/romfs is incomplete from an earlier run. The build deletes it and starts the step again."
		rm -rf "$EXTRACTED/romfs"
	fi
	step romfs "Etapa 4: juntando os dados do jogo base e da atualização (RomFS, ~38 GB; a etapa mais longa de disco)" \
		"Step 4: merge of the base game data and the update data (RomFS, ~38 GB, the longest disk step)" \
		"$PY" "$FC26_DIR/scripts/merge_update_romfs.py" "$BASE" "$UPDATE" --keys "$KEYS" --output "$EXTRACTED/romfs"
	json_pass "$EXTRACTED/romfs/index.json" || die "a RomFS terminou sem status pass em index.json." "the RomFS step stopped, but index.json does not have status pass."
fi

# --- 5. reescrita / rewrite ---
# patch_nso.py escreve <módulo>.obs.tsv por último; ele mais novo que o ExeFS = módulo pronto.
todo=
for m in $MODULES; do
	[ -f "$REWRITTEN/$m.obs.tsv" ] && [ "$REWRITTEN/$m.obs.tsv" -nt "$EXTRACTED/exefs/$m" ] || todo="$todo $m"
done
todo="${todo# }"
if [ -z "$todo" ]; then
	skip "Etapa 5: reescrita do código ($MODULES)" "Step 5: code rewrite ($MODULES)"
else
	step rewrite "Etapa 5: reescrevendo o código para o Mac ($todo; a etapa mais longa, usa 4 a 5 GB de RAM)" \
		"Step 5: rewrite of the code for the Mac ($todo). This is the longest step. It uses 4 to 5 GB of RAM." \
		make -C "$FC26_DIR" rewrite "${MAKE_VARS[@]}" MODULES="$todo"
fi

# --- 6. módulo de vídeo / video module (NRO) ---
MANIFEST="$REWRITTEN/nro_manifest.tsv"
if [ -f "$MANIFEST" ] && awk -F'\t' '$2 == "PlatformNvn" {f = 1} END {exit !f}' "$MANIFEST" \
	&& [ "$MANIFEST" -nt "$EXTRACTED/romfs/index.json" ] && [ ! "$REWRITTEN/PlatformNvn.patched.bin" -nt "$MANIFEST" ]; then
	skip "Etapa 6: módulo de vídeo (PlatformNvn)" "Step 6: video module (PlatformNvn)"
else
	step nro "Etapa 6: extraindo e reescrevendo o módulo de vídeo (PlatformNvn)" \
		"Step 6: extraction and rewrite of the video module (PlatformNvn)" \
		make -C "$FC26_DIR" nro "${MAKE_VARS[@]}"
fi

# --- 7. prepare + runtime ---
# prepare_runtime.py apaga os cabeçalhos e escreve romfs_config.h por último: ele mais novo que as entradas = pronto.
fresh=1
[ -f "$OUT/runtime_tables.h" ] && [ -f "$OUT/shared_fonts_config.h" ] && [ -f "$OUT/romfs_config.h" ] \
	&& [ -f "$EXTRACTED/romfs/runtime-index.bin" ] || fresh=0
for input in "$EXTRACTED/extraction-manifest.json" "$EXTRACTED/romfs/index.json" "$MANIFEST" $(for m in $MODULES; do echo "$REWRITTEN/$m.obs.tsv"; done); do
	[ "$fresh" = 1 ] && [ "$OUT/romfs_config.h" -nt "$input" ] || fresh=0
done
if [ "$fresh" = 1 ]; then
	skip "Etapa 7a: tabelas do runtime (make prepare)" "Step 7a: runtime tables (make prepare)"
else
	step prepare "Etapa 7a: conferindo tudo contra os valores esperados e gerando as tabelas (make prepare)" \
		"Step 7a: check of all files against the expected values, then the runtime tables (make prepare)" \
		make -C "$FC26_DIR" prepare "${MAKE_VARS[@]}" OUT="$OUT"
fi
step runtime "Etapa 7b: compilando o runtime (make runtime; o make pula se nada mudou)" \
	"Step 7b: compilation of the runtime (make runtime). If nothing changed, make skips it." \
	make -C "$FC26_DIR" runtime "${MAKE_VARS[@]}" OUT="$OUT"

# --- 8. app ---
# make app usa OUT=<work>/build-update (APP_RUNTIME) sozinho; GAME/KEYS só servem para o ícone do app.
step app "Etapa 8: montando o app (na primeira vez baixa e compila o SPIRV-Cross)" \
	"Step 8: the app (make app). The first time, this step downloads and compiles SPIRV-Cross." \
	make -C "$FC26_DIR" app "${MAKE_VARS[@]}" APP="$APP" GAME="$BASE" KEYS="$KEYS"

for f in build/shader-service/totk_xlate build/spirv-cross/spirv-cross; do   # o runtime procura os dois aqui / the runtime looks here
	[ -x "$WORK/$f" ] || die "falta $WORK/$f: sem ele o jogo fecha no primeiro shader." \
		"$WORK/$f is not there. Without it, the game stops at its first shader."
done

say "Pronto: $APP" "Complete: $APP"
info "Abra o app com dois cliques. A primeira abertura confere os ~38 GB de dados e demora mais." \
	"Double-click the app to open it. The first start checks the ~38 GB of data and takes more time."
info "Não apague nem mova $WORK: o app lê o jogo de lá." "Do not delete or move $WORK. The app reads the game from this folder."
info "Saves: ~/Library/Application Support/MacNativeGames/FC26/profile   Log: ~/Library/Logs/MacNativeGames/fc26.log" \
	"Saves: ~/Library/Application Support/MacNativeGames/FC26/profile   Log: ~/Library/Logs/MacNativeGames/fc26.log"
