/* EA SPORTS FC 26 1.0.0 (base game, no update; SDK 19.3.4). The values here must match assets/game.json
   (scripts/game_config.py check, run by scripts/prepare_runtime.py and the tests).
   No game-code address is defined on purpose: no address of another game applies (TotK's GAME_ADDR maps, the earlier fork's sites), so any
   leftover use is a compile error. FC 26 addresses get named defines here when a patch needs one.
   TODO(mac): main's build ID (assets/expected-v1.0.0.json main_build_id, recorded by prepare_runtime.py --record). */
#pragma once
#define GAME_FC26 1
#define TOTK_GAME_VERSION "1.0.0"
#define TOTK_GAME_DIR "v100"
#define GAME_TITLE_ID 0x01004ff021942000ULL
