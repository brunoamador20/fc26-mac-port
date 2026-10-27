# EA SPORTS FC 26 native runtime (story 2: boot to nnMain). Self-contained: the Horizon host (runtime/), the rewriter
# (third_party/d2r), the NVN-on-Metal layer (third_party/d2r_gfx), the shader translator (prebuilt/) and the scripts are
# this folder's own copies, from the kit's earlier fork of games/totk (CHANGELOG.md); nothing here reads another game's folder.
# The game's identity and module list are in assets/game.json (scripts/game_config.py). Everything generated goes to the
# work folder. Inputs come from scripts/extract_exefs.py, scripts/extract_romfs.py and the rewrite (story 1), then:
#   make prepare   # scripts/prepare_runtime.py: tables, RomFS index, fonts config (PREPARE_FLAGS=--record the first time)
#   make runtime   # <work>/build/fc26-native (OUT=<dir>: prepare + runtime into another folder, e.g. a second version's)
#   make probe     # modules mapped and linked, cross-module calls on 4 threads (no game code beyond that)
#   make boot      # run it from the work folder (cwd: extracted/ and rewritten/ are read relative to it)
#   make boot-nnmain  # story 2's check: stop with a JSON verdict at the original nnMain's entry
# The whole sequence, from the NSPs to the app, is build.sh (extract, merge_update_romfs.py, rewrite, nro, prepare, app).

PY ?= python3
GAME_CONFIG := "$(PY)" scripts/game_config.py
ifndef WORK
WORK := $(shell $(GAME_CONFIG) work)
endif
VERSION := $(shell $(GAME_CONFIG) version_dir)
MODULES := $(shell $(GAME_CONFIG) modules)
BINARY := $(shell $(GAME_CONFIG) binary)
TITLE_ID := $(shell $(GAME_CONFIG) title_id)
DISPLAY_VERSION := $(shell $(GAME_CONFIG) display_version)
# An empty answer (a wrong PY=, e.g. "~" that zsh leaves unexpanded after "=") would turn rewrite into a no-op and clean
# into rm -rf <work>/build/: stop instead.
ifneq ($(words $(VERSION) $(BINARY) $(firstword $(MODULES))),3)
$(error scripts/game_config.py gave no values with PY=$(PY): check PY (in zsh use $$HOME, not ~, after =))
endif
OUT := $(WORK)/build
NATIVE_OPT ?= -O2

GFX_SRC := $(wildcard third_party/d2r_gfx/gfx/nvn/*.c third_party/d2r_gfx/gfx/nvn/*.m third_party/d2r_gfx/gfx/nvn/*.S third_party/d2r_gfx/gfx/tex/*.c third_party/d2r_gfx/gfx/tex/*.m)
GFX_OBJECTS := $(patsubst %,$(OUT)/obj/%.o,$(GFX_SRC))
GFX_HEADERS := $(wildcard third_party/d2r_gfx/gfx/nvn/*.h third_party/d2r_gfx/gfx/nvn/include/*.h third_party/d2r_gfx/host/*.h)
GFX_FLAGS := -std=gnu11 -Wno-error -Wno-unused-function -Wno-unused-parameter -fobjc-arc -Ithird_party/d2r_gfx/gfx/nvn/include

RUNTIME_SRC := $(wildcard runtime/*.c runtime/*.m runtime/*.S runtime/ro/*.c)
RUNTIME_HEADERS := $(wildcard runtime/*.h runtime/ro/*.h)
GENERATED := $(OUT)/runtime_tables.h $(OUT)/romfs_config.h $(OUT)/shared_fonts_config.h

.PHONY: check-config prepare runtime probe probe-ro boot clean rewrite test
check-config:
	$(GAME_CONFIG) check

PREPARE_FLAGS ?=
prepare:   # prepare_runtime.py runs the check-config checks itself
	"$(PY)" scripts/prepare_runtime.py --work "$(WORK)" --out "$(OUT)" $(PREPARE_FLAGS)

$(GENERATED):
	@echo "missing $@: run make prepare" && false

$(OUT)/obj/%.o: % $(GFX_HEADERS) Makefile
	@mkdir -p "$(dir $@)"
	xcrun clang $(NATIVE_OPT) -g -Wall -Wextra $(GFX_FLAGS) -c "$<" -o "$@"

$(OUT)/$(BINARY): $(RUNTIME_SRC) $(RUNTIME_HEADERS) $(GENERATED) $(GFX_OBJECTS) Makefile
	xcrun clang -std=c11 $(NATIVE_OPT) -g -Wall -Wextra -Werror -Wno-deprecated-declarations \
	  -Ithird_party/d2r_gfx/gfx/nvn/include -I$(OUT) -I/opt/homebrew/opt/opus/include/opus -I/opt/homebrew/opt/libvpx/include \
	  $(RUNTIME_SRC) $(GFX_OBJECTS) /opt/homebrew/opt/opus/lib/libopus.a /opt/homebrew/opt/libvpx/lib/libvpx.a \
	  -framework Metal -framework MetalFX -framework Foundation -framework QuartzCore -framework ImageIO -framework CoreGraphics \
	  -framework CoreText -framework UniformTypeIdentifiers -fobjc-arc -framework Cocoa -framework CoreVideo -framework CoreFoundation \
	  -framework AudioToolbox -framework GameController -framework CoreHaptics -framework IOKit -o "$@"

runtime: $(OUT)/$(BINARY)

# The rewrite for Apple silicon (story 1): each module of assets/game.json -> <work>/rewritten/<version>/<name>.patched.bin
# (+ .fixups.tsv, .gates.tsv), with the variables the kit's builds use (game_config.py rewrite-env). MODULES=sdk rewrites
# one. main's 43.8 M-instruction text needs the rewriter that works in chunks (story 1, BRIEFING): without it the old one
# grew past 18 GB, so main is refused here unless patch_nso.py has it. Heavy: one module at a time, under a memory limit.
rewrite:
	@mkdir -p "$(WORK)/rewritten/$(VERSION)"
	@for m in $(MODULES); do \
	  if [ "$$m" = main ] && ! grep -q '^class LazyInsns' third_party/d2r/patch_nso.py; then \
	    echo "refusing to rewrite main with this patch_nso.py: it has no chunked disassembly (story 1, docs/BRIEFING.md)"; exit 1; fi; \
	  echo "rewrite $$m"; \
	  env $$($(GAME_CONFIG) rewrite-env) "$(PY)" third_party/d2r/patch_nso.py "$(WORK)/extracted/$(VERSION)/exefs/$$m" "$(WORK)/rewritten/$(VERSION)" $$m || exit 1; \
	done

# The video module (story 3): Engine.Render.Core2.PlatformNvn.nro is loaded by the game at run time (nn::ro), so it is
# taken out of the RomFS, wrapped as an NSO, rewritten like main and sdk, and registered for runtime/ro
# (<work>/rewritten/<version>/PlatformNvn.patched.bin + nro_manifest.tsv). Needs the RomFS (merge_update_romfs.py).
NRO_NAME := Engine.Render.Core2.PlatformNvn.nro
.PHONY: nro
nro:
	"$(PY)" scripts/romfs_file.py "$(WORK)/extracted/$(VERSION)/romfs" "$(NRO_NAME)" "$(WORK)/nro/$(VERSION)/$(NRO_NAME)"
	"$(PY)" scripts/nro_to_nso.py wrap "$(WORK)/nro/$(VERSION)/$(NRO_NAME)" "$(WORK)/nro/$(VERSION)/PlatformNvn.nso"
	@mkdir -p "$(WORK)/rewritten/$(VERSION)"
	env $$($(GAME_CONFIG) rewrite-env) "$(PY)" third_party/d2r/patch_nso.py "$(WORK)/nro/$(VERSION)/PlatformNvn.nso" "$(WORK)/rewritten/$(VERSION)" PlatformNvn
	"$(PY)" scripts/nro_to_nso.py register "$(WORK)/nro/$(VERSION)/$(NRO_NAME)" "$(WORK)/rewritten/$(VERSION)" PlatformNvn

# Analysis ELF of every ExeFS module (assets/game.json analysis_modules) for reading the code: <work>/extracted/<version>/elf.
.PHONY: analysis
analysis:
	"$(PY)" scripts/prepare_modules.py "$(WORK)/extracted/$(VERSION)/exefs" --output "$(WORK)/extracted/$(VERSION)/elf"

# The runtime shader translation the graphics layer starts on first use: <work>/build/shader-service/totk_xlate (the
# repository's prebuilt NativeAOT translator, checked against its SHA-256) and <work>/build/spirv-cross/spirv-cross,
# built like build_app.py does (same pinned commit, sources and flags as SPIRV-Cross's CMake Release build).
SPIRV_CROSS_COMMIT := aa217aeb6c9f0ace7a0ab233b28807edf45eb165
SPIRV_CROSS_SOURCES := main.cpp spirv_cfg.cpp spirv_cpp.cpp spirv_cross.cpp spirv_cross_parsed_ir.cpp spirv_cross_util.cpp \
  spirv_glsl.cpp spirv_hlsl.cpp spirv_msl.cpp spirv_parser.cpp spirv_reflect.cpp
.PHONY: shader-tools
shader-tools: $(OUT)/shader-service/totk_xlate $(OUT)/spirv-cross/spirv-cross
$(OUT)/shader-service/totk_xlate: prebuilt/macos-arm64/totk_xlate prebuilt/macos-arm64/totk_xlate.sha256
	@mkdir -p "$(dir $@)"
	test "$$(shasum -a 256 "$<" | cut -d' ' -f1)" = "$$(cut -d' ' -f1 "prebuilt/macos-arm64/totk_xlate.sha256")"
	cp "$<" "$@" && chmod +x "$@"
$(OUT)/spirv-cross/spirv-cross:
	@mkdir -p "$(WORK)/src" "$(dir $@)obj"
	test -d "$(WORK)/src/SPIRV-Cross" || git clone -q https://github.com/KhronosGroup/SPIRV-Cross.git "$(WORK)/src/SPIRV-Cross"
	git -C "$(WORK)/src/SPIRV-Cross" checkout -q $(SPIRV_CROSS_COMMIT)
	for f in $(SPIRV_CROSS_SOURCES); do xcrun clang++ -O3 -DNDEBUG -std=c++11 -arch arm64 -Wno-deprecated-declarations \
	  -c "$(WORK)/src/SPIRV-Cross/$$f" -o "$(dir $@)obj/$$f.o" & done; wait
	xcrun clang++ -arch arm64 $(addprefix $(dir $@)obj/,$(addsuffix .o,$(SPIRV_CROSS_SOURCES))) -o "$@"

# FC26_LOG: where stderr goes (the host is loud on purpose; every abort names what is missing: service, command, SVC,
# symbol). probe prints its JSON verdict on stdout. boot runs headless and silent by default (automatic runs make no sound:
# TOTK_AUDIO_OFF for the audio renderer's device, FC26_AUDIO=0 for AudioOut); add TOTK_VERIFY_STARTUP=nnmain to BOOT_ENV
# to stop with a JSON verdict at the original nnMain's entry (story 2's goal), =1 to stop when nnMain sets its focus mode.
FC26_LOG ?= $(WORK)/logs/boot.log
PROBE_LOG ?= $(WORK)/logs/probe.log
BOOT_ENV ?= TOTK_HEADLESS=1 TOTK_AUDIO_OFF=1 FC26_AUDIO=0
probe: runtime
	@mkdir -p "$(dir $(PROBE_LOG))"
	cd "$(WORK)" && ./build/$(BINARY) rewritten/$(VERSION) probe 2> "$(abspath $(PROBE_LOG))"; s=$$?; echo "exit $$s; log: $(PROBE_LOG)"; exit $$s
probe-ro: runtime
	@mkdir -p "$(dir $(PROBE_LOG))"
	cd "$(WORK)" && ./build/$(BINARY) rewritten/$(VERSION) probe-ro 2> "$(abspath $(PROBE_LOG))"; s=$$?; echo "exit $$s; log: $(PROBE_LOG)"; exit $$s
boot: runtime
	@mkdir -p "$(dir $(FC26_LOG))"
	cd "$(WORK)" && env $(BOOT_ENV) ./build/$(BINARY) rewritten/$(VERSION) boot 2> "$(abspath $(FC26_LOG))"; s=$$?; echo "exit $$s; log: $(FC26_LOG)"; exit $$s
# Story 2's check: boot (headless, silent) until the original nnMain's entry, then a JSON verdict on stdout. What the host
# lacks before that is listed by: grep '\[fc26-missing\]' <work>/logs/boot.log
.PHONY: boot-nnmain
boot-nnmain:
	$(MAKE) boot BOOT_ENV="$(BOOT_ENV) TOTK_VERIFY_STARTUP=nnmain"

# This folder's synthetic tests (no game data): config, RomFS index, unknown service / command messages, shader cache, pre-island.
test:
	"$(PY)" -m unittest discover -s tests -v

# RomFS offline configuration package (Data/nxcert.ini, Scripts/BootIni/MemoryInit.ini) -> <work>/extracted/<version>/romfs-patches
# Overlays served in place of the originals (runtime/romfs.c, TOTK_ROMFS_PATCHES).
ROMFS_DIR ?= $(WORK)/extracted/$(VERSION)/romfs
ROMFS_PATCHES_DIR ?= $(WORK)/extracted/$(VERSION)/romfs-patches
.PHONY: offline-config romfs-patches
offline-config:
	"$(PY)" scripts/make_offline_config.py --work "$(WORK)" --romfs "$(ROMFS_DIR)" --output "$(ROMFS_PATCHES_DIR)"

romfs-patches: offline-config

# The shader cache (docs/SHADERS_NUVEM.md): what each run compiled during play (RUNS: the runs' logs, first run first;
# FRAMES: their DM_NVN_TSV tables, optional) and whether the shader keys repeat between starts (DUMPS: two or more
# TOTK_CTL_DUMP files).
RUNS ?=
FRAMES ?=
DUMPS ?=
.PHONY: shader-report shader-keys
shader-report:
	@test -n "$(RUNS)" || { echo 'RUNS="<log of run 1> <log of run 2>" (docs/SHADERS_NUVEM.md)'; exit 2; }
	"$(PY)" scripts/shader_cache_report.py $(RUNS) $(if $(FRAMES),--frames $(FRAMES))
shader-keys:
	@test -n "$(DUMPS)" || { echo 'DUMPS="<TOTK_CTL_DUMP of start 1> <of start 2>" (docs/SHADERS_NUVEM.md)'; exit 2; }
	"$(PY)" scripts/shader_key_check.py $(DUMPS)

# Offline shader pre-translation (docs/SHADER_SEED.md): the game's shaders out of its .cas (decompressed by fc26-native's
# "oodle" mode, i.e. the game's own Oodle), then translated into a shader cache. SEED: extracted shaders (game data);
# CACHE: the cache to fill (rt-<chain> with its fc26-cache.id; no run may hold it). One SEED per version: each version's
# RomFS has its own .cas (the update's merged one has the base's Data/ and its Patch/).
SEED ?= $(WORK)/shader-seed-fc26/$(VERSION)
.PHONY: shader-seed shader-seed-translate
shader-seed: runtime
	"$(PY)" scripts/shader_seed.py scan --out "$(SEED)" --native "$(OUT)/$(BINARY)" --romfs "$(WORK)/extracted/$(VERSION)/romfs" --rewritten "$(WORK)/rewritten/$(VERSION)"
shader-seed-translate:
	@test -n "$(CACHE)" || { echo 'CACHE=<shader cache folder> (docs/SHADER_SEED.md)'; exit 2; }
	"$(PY)" scripts/shader_seed.py translate --out "$(SEED)" --cache "$(CACHE)" --translator "$(OUT)/shader-service/totk_xlate" --spirv-cross "$(OUT)/spirv-cross/spirv-cross"

# The slow pre-island proof (docs/ILHAS_NUVEM.md): build a > 140 MiB synthetic NSO, rewrite it at the real ±128 MiB
# reach so a pre-island is forced, and prove every branch is in range and round-trips (+ structck). Not in `make test`.
.PHONY: island-giant
island-giant:
	"$(PY)" tests/synth_giant.py --mib 144 --every 256 --structck

# exefs patches (mods/<display version>/<name>/exefs/*.pchtxt) -> <work>/patches, applied when FC26_PATCHES names them.
# FC 26 has none yet: the mechanism is kept, the table is empty.
.PHONY: patches app
patches:
	"$(PY)" scripts/prepare_patches.py --work "$(WORK)"

# The app: a small launcher bundle (settings window, then the game) that runs the game from the work folder, which it
# names in Info.plist (FC26WorkFolder): nothing large is copied. Its icon comes from the game's own control data
# (GAME=<NSP> KEYS=<prod.keys>), or the app goes without one. Not needed for story 2.
APP ?= FC 26.app
GAME ?=
KEYS ?=
# The app runs the runtime built for VERSION (the update, since story H1: `make prepare runtime OUT=<work>/build-update`)
# with that runtime's own shader cache; both are relative to the work folder. The base game's stays in build/.
APP_RUNTIME ?= build-update
APP_SHADER_CACHE ?= $(APP_RUNTIME)/shader-cache/rt-update
$(OUT)/launcher: app/launcher.m assets/game.json Makefile   # BINARY, VERSION, APP_RUNTIME and APP_SHADER_CACHE are compiled in
	@mkdir -p "$(dir $@)"
	xcrun clang -std=gnu11 -O2 -Wall -Wextra -Werror -fobjc-arc -DFC26_BINARY='"$(BINARY)"' -DFC26_VERSION_DIR='"$(VERSION)"' \
	  -DFC26_RUNTIME_DIR='"$(APP_RUNTIME)"' -DFC26_SHADER_CACHE='"$(APP_SHADER_CACHE)"' app/launcher.m -framework Cocoa -o "$@"
$(OUT)/AppIcon.icns:
	@if [ -n "$(GAME)" ] && [ -n "$(KEYS)" ]; then cd scripts && "$(PY)" extract_app_icon.py "$(GAME)" --keys "$(KEYS)" --title $(TITLE_ID) --output "$(abspath $@)"; \
	 else echo "no GAME= / KEYS=: the app gets no icon"; fi
# `make app` builds the runtime the app runs: OUT defaults to <work>/APP_RUNTIME (build-update) instead of <work>/build, so
# `make prepare runtime OUT=<work>/build-update` followed by `make app` agree without repeating OUT. OUT=<dir> still wins.
# The shader translator and SPIRV-Cross go to <work>/build: the runtime looks for them there whatever its own folder is
# (runtime/shader_cache_mac.m, third_party/d2r_gfx/gfx/nvn/totk_shader_rt.m). Without them the game stops at its first shader.
app:
	$(MAKE) shader-tools OUT="$(WORK)/build"
	$(MAKE) app-bundle OUT="$(WORK)/$(APP_RUNTIME)"
.PHONY: app-bundle
app-bundle: runtime $(OUT)/launcher $(OUT)/AppIcon.icns
	rm -rf "$(APP)" && mkdir -p "$(APP)/Contents/MacOS" "$(APP)/Contents/Resources"
	cp "$(OUT)/launcher" "$(APP)/Contents/MacOS/FC 26"
	[ -f "$(OUT)/AppIcon.icns" ] && cp "$(OUT)/AppIcon.icns" "$(APP)/Contents/Resources/" || true
	printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	  '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	  '<plist version="1.0"><dict>' \
	  '<key>CFBundleExecutable</key><string>FC 26</string>' \
	  '<key>CFBundleIdentifier</key><string>org.macnativegames.fc26</string>' \
	  '<key>CFBundleName</key><string>FC 26</string>' \
	  '<key>CFBundlePackageType</key><string>APPL</string>' \
	  '<key>CFBundleShortVersionString</key><string>$(DISPLAY_VERSION)</string>' \
	  '<key>CFBundleVersion</key><string>1</string>' \
	  '<key>CFBundleIconFile</key><string>AppIcon</string>' \
	  '<key>LSMinimumSystemVersion</key><string>26.0</string>' \
	  '<key>LSApplicationCategoryType</key><string>public.app-category.sports-games</string>' \
	  '<key>NSHighResolutionCapable</key><true/>' \
	  '<key>FC26WorkFolder</key><string>$(abspath $(WORK))</string>' \
	  '</dict></plist>' > "$(APP)/Contents/Info.plist"
	codesign --force --sign - "$(APP)"
	@echo "built $(APP) (game data stay in $(abspath $(WORK)))"

# Install the (small) app where Launchpad and Spotlight look: /Applications, or ~/Applications when that is not writable.
INSTALL_DIR ?= $(shell [ -w /Applications ] && echo /Applications || echo $(HOME)/Applications)
.PHONY: install
install: app
	mkdir -p "$(INSTALL_DIR)" && rm -rf "$(INSTALL_DIR)/$(APP)" && cp -R "$(APP)" "$(INSTALL_DIR)/"
	/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$(INSTALL_DIR)/$(APP)"
	@echo "installed $(INSTALL_DIR)/$(APP)"

clean:
	rm -rf "$(OUT)/obj" "$(OUT)/$(BINARY)"

# hle_nvn includes the optional runtime clock probe outside GFX_HEADERS.
$(OUT)/obj/third_party/d2r_gfx/gfx/nvn/hle_nvn.c.o $(OUT)/obj/third_party/d2r_gfx/gfx/nvn/totk_nvn_ext.c.o: runtime/time_probe.h
