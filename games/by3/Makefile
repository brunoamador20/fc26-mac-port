# Bayonetta 3 native runtime. The Horizon host is this folder's fork of games/totk/runtime (runtime/); the NVN-on-Metal
# layer is compiled from games/totk/third_party/d2r_gfx unchanged. Everything generated goes to the work folder.
# Inputs come from scripts/extract_code.py, scripts/merge_romfs.py and the rewrite (see README.md), then:
#   make prepare   # scripts/prepare_runtime.py: tables, RomFS index, fonts config
#   make runtime   # BY3_build/build/by3-native
#   make boot      # run it from the work folder (cwd: extracted/ and rewritten/ are read relative to it)

TOTK := ../totk
WORK ?= BY3_build
OUT := $(WORK)/build
PY ?= python3
NATIVE_OPT ?= -O2

GFX_SRC := $(wildcard $(TOTK)/third_party/d2r_gfx/gfx/nvn/*.c $(TOTK)/third_party/d2r_gfx/gfx/nvn/*.m $(TOTK)/third_party/d2r_gfx/gfx/nvn/*.S $(TOTK)/third_party/d2r_gfx/gfx/tex/*.c $(TOTK)/third_party/d2r_gfx/gfx/tex/*.m)
GFX_OBJECTS := $(patsubst $(TOTK)/%,$(OUT)/obj/%.o,$(GFX_SRC))
GFX_HEADERS := $(wildcard $(TOTK)/third_party/d2r_gfx/gfx/nvn/*.h $(TOTK)/third_party/d2r_gfx/gfx/nvn/include/*.h $(TOTK)/third_party/d2r_gfx/host/*.h)
GFX_FLAGS := -std=gnu11 -Wno-error -Wno-unused-function -Wno-unused-parameter -fobjc-arc -I$(TOTK)/third_party/d2r_gfx/gfx/nvn/include

RUNTIME_SRC := $(filter-out runtime/frontend_ios.m,$(wildcard runtime/*.c runtime/*.m runtime/*.S))
RUNTIME_HEADERS := $(wildcard runtime/*.h)
GENERATED := $(OUT)/runtime_tables.h $(OUT)/romfs_config.h $(OUT)/shared_fonts_config.h

.PHONY: prepare runtime boot clean
prepare:
	"$(PY)" scripts/prepare_runtime.py --work "$(WORK)"

$(GENERATED):
	@echo "missing $@: run make prepare" && false

$(OUT)/obj/%.o: $(TOTK)/% $(GFX_HEADERS) Makefile
	@mkdir -p "$(dir $@)"
	xcrun clang $(NATIVE_OPT) -g -Wall -Wextra $(GFX_FLAGS) -c "$<" -o "$@"

$(OUT)/by3-native: $(RUNTIME_SRC) $(RUNTIME_HEADERS) $(GENERATED) $(GFX_OBJECTS) Makefile
	xcrun clang -std=c11 $(NATIVE_OPT) -g -Wall -Wextra -Werror -Wno-deprecated-declarations \
	  -I$(TOTK)/third_party/d2r_gfx/gfx/nvn/include -I$(OUT) -I/opt/homebrew/opt/opus/include/opus -I/opt/homebrew/opt/libvpx/include \
	  $(RUNTIME_SRC) $(GFX_OBJECTS) /opt/homebrew/opt/opus/lib/libopus.a /opt/homebrew/opt/libvpx/lib/libvpx.a \
	  -framework Metal -framework MetalFX -framework Foundation -framework QuartzCore -framework ImageIO -framework CoreGraphics \
	  -framework CoreText -framework UniformTypeIdentifiers -fobjc-arc -framework Cocoa -framework CoreVideo -framework CoreFoundation \
	  -framework AudioToolbox -framework GameController -framework CoreHaptics -framework IOKit -o "$@"

runtime: $(OUT)/by3-native

# BY3_LOG: where the boot's stderr goes (the host is loud on purpose; every abort names what is missing).
BY3_LOG ?= $(WORK)/logs/boot.log
boot: runtime
	@mkdir -p "$(dir $(BY3_LOG))"
	cd "$(WORK)" && TOTK_HEADLESS=$${TOTK_HEADLESS-} ./build/by3-native rewritten/v120 boot 2> "$(abspath $(BY3_LOG))"; echo "exit $$?; log: $(BY3_LOG)"

clean:
	rm -rf "$(OUT)/obj" "$(OUT)/by3-native"
