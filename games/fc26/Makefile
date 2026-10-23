# EA SPORTS FC 26 native runtime (story 2: boot to nnMain). Self-contained: the Horizon host (runtime/), the rewriter
# (third_party/d2r), the NVN-on-Metal layer (third_party/d2r_gfx), the shader translator (prebuilt/) and the scripts are
# this folder's own copies, from the kit's earlier fork of games/totk (CHANGELOG.md); nothing here reads another game's folder.
# The game's identity and module list are in assets/game.json (scripts/game_config.py). Everything generated goes to the
# work folder. Inputs come from scripts/extract_exefs.py, scripts/extract_romfs.py and the rewrite (story 1), then:
#   make prepare   # scripts/prepare_runtime.py: tables, RomFS index, fonts config (PREPARE_FLAGS=--record the first time)
#   make runtime   # <work>/build/fc26-native
#   make probe     # modules mapped and linked, cross-module calls on 4 threads (no game code beyond that)
#   make boot      # run it from the work folder (cwd: extracted/ and rewritten/ are read relative to it)
# The whole sequence for the Mac is in docs/ESTORIA2_NUVEM.md.

PY ?= python3
GAME_CONFIG := "$(PY)" scripts/game_config.py
WORK ?= $(shell $(GAME_CONFIG) work)
VERSION := $(shell $(GAME_CONFIG) version_dir)
MODULES := $(shell $(GAME_CONFIG) modules)
BINARY := $(shell $(GAME_CONFIG) binary)
TITLE_ID := $(shell $(GAME_CONFIG) title_id)
DISPLAY_VERSION := $(shell $(GAME_CONFIG) display_version)
OUT := $(WORK)/build
NATIVE_OPT ?= -O2

GFX_SRC := $(wildcard third_party/d2r_gfx/gfx/nvn/*.c third_party/d2r_gfx/gfx/nvn/*.m third_party/d2r_gfx/gfx/nvn/*.S third_party/d2r_gfx/gfx/tex/*.c third_party/d2r_gfx/gfx/tex/*.m)
GFX_OBJECTS := $(patsubst %,$(OUT)/obj/%.o,$(GFX_SRC))
GFX_HEADERS := $(wildcard third_party/d2r_gfx/gfx/nvn/*.h third_party/d2r_gfx/gfx/nvn/include/*.h third_party/d2r_gfx/host/*.h)
GFX_FLAGS := -std=gnu11 -Wno-error -Wno-unused-function -Wno-unused-parameter -fobjc-arc -Ithird_party/d2r_gfx/gfx/nvn/include

RUNTIME_SRC := $(wildcard runtime/*.c runtime/*.m runtime/*.S)
RUNTIME_HEADERS := $(wildcard runtime/*.h)
GENERATED := $(OUT)/runtime_tables.h $(OUT)/romfs_config.h $(OUT)/shared_fonts_config.h

.PHONY: check-config prepare runtime probe boot clean rewrite test
check-config:
	$(GAME_CONFIG) check

PREPARE_FLAGS ?=
prepare: check-config
	"$(PY)" scripts/prepare_runtime.py --work "$(WORK)" $(PREPARE_FLAGS)

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
	  if [ "$$m" = main ] && ! grep -q 'class LazyInsns' third_party/d2r/patch_nso.py; then \
	    echo "refusing to rewrite main with this patch_nso.py: it has no chunked disassembly (story 1, docs/BRIEFING.md)"; exit 1; fi; \
	  echo "rewrite $$m"; \
	  env $$($(GAME_CONFIG) rewrite-env) "$(PY)" third_party/d2r/patch_nso.py "$(WORK)/extracted/$(VERSION)/exefs/$$m" "$(WORK)/rewritten/$(VERSION)" $$m || exit 1; \
	done

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
# symbol). probe prints its JSON verdict on stdout. boot runs headless by default; BOOT_ENV=TOTK_VERIFY_STARTUP=nnmain
# stops with a JSON verdict at the original nnMain's entry (story 2's goal), =1 when nnMain sets its focus mode.
FC26_LOG ?= $(WORK)/logs/boot.log
PROBE_LOG ?= $(WORK)/logs/probe.log
BOOT_ENV ?= TOTK_HEADLESS=1
probe: runtime
	@mkdir -p "$(dir $(PROBE_LOG))"
	cd "$(WORK)" && ./build/$(BINARY) rewritten/$(VERSION) probe 2> "$(abspath $(PROBE_LOG))"; echo "exit $$?; log: $(PROBE_LOG)"
boot: runtime
	@mkdir -p "$(dir $(FC26_LOG))"
	cd "$(WORK)" && env $(BOOT_ENV) ./build/$(BINARY) rewritten/$(VERSION) boot 2> "$(abspath $(FC26_LOG))"; echo "exit $$?; log: $(FC26_LOG)"

# This folder's synthetic tests (no game data): config, RomFS index, unknown service / command messages.
test:
	"$(PY)" -m unittest discover -s tests -v

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
$(OUT)/launcher: app/launcher.m Makefile
	@mkdir -p "$(dir $@)"
	xcrun clang -std=gnu11 -O2 -Wall -Wextra -Werror -fobjc-arc -DFC26_BINARY='"$(BINARY)"' -DFC26_VERSION_DIR='"$(VERSION)"' \
	  app/launcher.m -framework Cocoa -o "$@"
$(OUT)/AppIcon.icns:
	@if [ -n "$(GAME)" ] && [ -n "$(KEYS)" ]; then cd scripts && "$(PY)" extract_app_icon.py "$(GAME)" --keys "$(KEYS)" --title $(TITLE_ID) --output "$(abspath $@)"; \
	 else echo "no GAME= / KEYS=: the app gets no icon"; fi
app: runtime shader-tools $(OUT)/launcher $(OUT)/AppIcon.icns
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
