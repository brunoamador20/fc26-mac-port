/* EA SPORTS FC 26 update v1638400, display version 1.89.6e65 (its control.nacp; main build id 323f3a9f..., over the
   1.0.0 base's RomFS; SDK 19.3.4). The base's values were "1.0.0" / "v100". The values here must match assets/game.json
   (scripts/game_config.py check, run by scripts/prepare_runtime.py and the tests).
   No game-code address is defined on purpose: no address of another game applies (TotK's GAME_ADDR maps, the earlier fork's sites), so any
   leftover use is a compile error. FC 26 addresses get named defines here when a patch needs one.
   main's build ID is pinned in assets/expected-v<display version>.json (main_build_id), checked by prepare_runtime.py. */
#pragma once
#define GAME_FC26 1
#define TOTK_GAME_VERSION "1.89.6e65"
#define TOTK_GAME_DIR "v1638400"
#define GAME_TITLE_ID 0x01004ff021942000ULL
