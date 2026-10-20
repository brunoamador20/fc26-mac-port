# Hair and cloth timing in 1.4.3

The native real-time patch updates FrameRateMgr and the global frame ratio.
That keeps ordinary actor movement and animation tied to elapsed time. It does
not cover every clock the game constructs: some actor animation paths build a
separate cloth/hair clock from a time factor, with `seconds = factor / 30` and
`ratio = factor`, once per rendered frame. At 120 FPS, a factor of one advances
this clock by four seconds per real second.

`runtime/game_patches_v143.c` now uses the measured frame seconds and 30 Hz ratio
for that independent clock. The actor's original time factor is retained. The
ordinary animation arguments, nonpositive-clock fallback and original callee
are retained. This is a clock correction, not a frame-rate cap or a change to
Havok solver parameters.

The 1.4.3 compiler inlines the animation update in two paths:

| Main offset | Original operation | Correction |
| --- | --- | --- |
| `0x246eac` | Factor times nominal 1/30; ratio at `sp+0x364` | Measured seconds and ratio times the same factor |
| `0x345904` | Factor times nominal 1/30; ratio at `sp+0x114` | Measured seconds and ratio times the same factor |
| `0x24944c` | Call `0x2a0e40` with independent clock in s2/s3 | Scale only s2/s3 by the measured 30 Hz ratio |
| `0x28bc98` | Same call, including both transform branches | Same correction before the original call |

The third caller, `0x2afac18`, already passes measured time and is left alone.
All four instruction words and the unused text padding are checked before the
patch is installed. The inline veneers preserve the time-factor registers;
the delegated veneer preserves the original link register and tail-calls the
original function. The new veneers follow the existing aspect-ratio veneers.
`TOTK_CLOTH_REALTIME=0` disables only this correction for diagnostic comparison;
`TOTK_REALTIME=0` disables both real-time patches as before.

## Verification

From an external build work tree with the player's verified 1.4.3 code inputs:

```sh
.venv/bin/python scripts/prepare_runtime.py --version v143
.venv/bin/python scripts/verify_v143_timing.py
```

The fixture compiles the production C patch and executes its emitted ARM64
instructions in Unicorn. It checks 108 main-timing cases and 144 secondary-clock
cases: 15–120 FPS, four time factors including zero and slow motion, both inline
paths and both delegated callers. It checks ordinary-clock preservation, stack,
condition flags, live registers and return addresses. Original unpatched code
is a negative control: all four paths reproduce a 4x clock at 120 FPS. The
already-correct third caller must remain byte-identical.
Four corrupted-instruction controls also verify that each new patch site
rejects an unexpected game instruction.

On 2026-10-20, the rebuilt Mac runtime passed the native cross-module/timer
probe and loaded a copied save into the Great Sky Island. The test reached
14,700 rendered frames, including a recent 300-frame window with a median
8.29 ms frame time, then exited cleanly through the normal window-close path.
All 51 files in the player's normal save/profile directory matched their
pre-test hashes. The repository suite passed 87 tests, with one Metal-device
test skipped in the sandbox. This is a startup/gameplay smoke test, not a
quantitative measurement of the visible hair oscillation frequency.

This test establishes the clock arithmetic and patch ABI. It does not establish
that every physics subsystem, shrine mechanism or cutscene is frame-rate
independent. The reported symptom and this change concern the separate actor
animation clock used for hair and clothing.

## External reference

[ChucksFeedAndSeed's Dynamic FPS 1.5.3 release notes](https://www.reddit.com/user/ChucksFeedAndSeed/comments/14fe0ca/release_totk_dynamic_fps_v153_release_physics/)
identify the same hair/cloth speed issue and distinguish its animation-rate hook
from the separate Havok solver fix. The author's original mod was inspected
statically to locate the older animation-update path. The 1.4.3 sites above were
then traced in the player's game code; no mod executable is installed or added
as a dependency. The native patch only scales the independently constructed
clock, because this runtime already corrects the ordinary clock.
