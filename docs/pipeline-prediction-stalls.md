# Pipeline prediction on the submission thread

## What prediction does

A render pipeline that is not built yet is compiled on the submission thread when a draw needs it. On the first
such miss of a submission, `pso_get` first scans the rest of that submission (`pso_predict_rest`: state only, no
drawing), works out the pipeline keys of the later draws, and starts compiling the missing ones on background
threads. When the submission thread reaches one of those draws it takes the pipeline, or waits for what is left
of its compile (`pso_pend_take`). A scan also guesses the other ways the pass may attach depth / stencil (which
planes a pass attaches is decided only when it begins, `ds_scan`); wrong guesses only cost background work.
`TOTK_PSO_PREDICT=0` turns prediction off.

## What PR #29 changed, and the follow-ups

- **No program is resolved for a guess.** The scan used `prog_get`, which translates and compiles a program the
  first time it is seen. Every new program of a submission was therefore translated and compiled on the
  submission thread before the current draw, while nothing had been started in the background yet. Now a guess
  uses only a program that is already resolved, and only the variant for the binding state at that draw
  (`prog_prediction_stages`); the program's active variant is not changed. New programs are left to their draws.
- **The scan keeps the future pass's render targets** (`R.rt`), so a fragment variant's signature describes the
  pass it will draw in.
- **Bounded.** At most 8,192 commands, 64 keys per queue and 2 ms per scan; keys with the pass's own attachments
  start as soon as they are found, the other attach modes after the scan. `TOTK_PSO_PREDICT_SCAN`,
  `TOTK_PSO_PREDICT_KEYS` (up to 160) and `TOTK_PSO_PREDICT_US` change the three limits; the log prints them once.
  The time is checked between commands, so it is not a hard bound on descriptors or driver calls.
- **Stale guesses are freed.** The pending table has 768 slots. A guess no draw takes (a wrong attach mode, a
  draw that did not happen) used to keep its slot forever; after a few scans the table was full and nothing was
  predicted any more. Now a completed guess no draw took is freed two submissions later. A slot whose compile has
  not finished is never reused: its worker still writes into it.
- **Follow-ups (MacNativeGames):** a program with a stage not translated yet (`missing`, iOS) is not predicted
  (its draws are skipped, and its fragment stage may be absent); a fragment function that exports depth gets no
  guesses without the depth buffer (`pred_guess_wanted`: `ds_scan` attaches the depth buffer for it, so those
  guesses were never used, and `pso_desc` compiled their depth-less library on the submission thread); a
  statistics line every 100 scans (`并行预编 至提交 …`: scans and the budget that ended them, pipelines started,
  pipelines taken by draws and how long draws waited for them, guesses refused because the table was full, stale
  guesses freed).

## Scanning on after a budget

A submission was scanned once, at its first miss. When that scan stopped at a budget (in a world entry almost always
the 8,192 commands), the rest of the submission was never predicted and its new pipelines were compiled on the
submission thread one after another (265 in one frame, 2.6 s, on entering a new area). Now the next miss of the
submission scans again from there, up to 32 times (`TOTK_PSO_RESCANS`, 0 = one scan as before); keys already compiling
are skipped, so each scan moves on. The statistics line also counts the pipelines compiled on the submission thread.

1.2.1, Apple M4 Max, a copy of a save on the Great Sky Island, loaded from the title, a walk and a camera turn, with the
warm-up lists and the pipeline archive off (`DM_PSO_MANIFEST=off TOTK_PIPELINE_ARCHIVE=0`), so the world entry meets its
pipelines for the first time. Old = the build without this change. Runs in this order; Metal's own cache gets warmer
with every run, so compare a run with its neighbours:

| run | pipeline time inside long frames | compile frames over 100 ms | longest compile frame |
|---|---|---|---|
| old | 35.8 s | 35 | 8.7 s |
| new | 5.5 s | 12 | 2.7 s |
| old | 7.1 s | 9 | 5.1 s |
| new | 2.9 s | 8 | 1.35 s |
| old | 2.3 s | 9 | 0.86 s |
| new | 1.05 s | 6 | 0.42 s |

Against the mean of its two neighbours: old 7.1 s / 5.1 s against new 4.2 s / 2.0 s around it, new 2.9 s / 1.35 s
against old 4.7 s / 3.0 s around it (pipeline time / longest compile frame).

The pipelines compiled on the submission thread stay about the same (920-1,040 a run): in a world entry most of them
belong to a binding variant the program has not drawn yet, which a scan cannot see (`prog_prediction_stages`). They get
cheaper because the background compiles of the guesses around them come first. The cost, counted at about submission
21,000: three times the scans (100 -> 300, 0.42 -> 0.58 ms each) and about 2.7 times the background work (about 1,750
-> 4,700 pipelines started, most of them guesses no draw takes). The steady frame after the entry did not change (frame
p50 7.4-7.7 ms, GPU p50 3.6-3.9 ms in both builds). Smaller Macs, iPhone and iPad are untested.

## Programs and binding variants not drawn yet

After PR #29 a scan skipped every draw whose program the game had not drawn yet, or whose binding state needs a variant
the program had not drawn with (`prog_prediction_stages` takes only `pr->sh` / `pr->alt`). In a world entry those are
most of the new pipelines, and their shaders are usually loaded already: the warm-up compiles the prepared shaders'
libraries before the player enters the world, and another program may have loaded the same shader. Their pipelines
were nevertheless compiled one after another at their draws.

Now such a draw is resolved the way the draw will resolve it, without translating or compiling
(`prog_prediction_unseen`): the shader key from the control section and code (`shader_key_of`, the same function
`prog_get` uses), the variant from the translation cache's index with the draw's bound state (`totk_rt_variant_cached`,
the lookup `totk_rt_variant` does before it would translate), and the shader only from `g_shcache`, which holds the
loaded ones. A variant the index does not name, or one no shader is loaded for, is skipped as before. No program is
created and no program's variants change; the draw later resolves the same shader objects, so its pipeline key is
the predicted one and it takes the pipeline from the pending table. The pipeline is built from the same descriptor as
before (`pso_desc` of the same key), so the picture cannot change. Shader keys are kept per program serial, and the
answer for a program and binding signature is kept for the rest of the scan. `TOTK_PSO_PREDICT_UNSEEN=0` turns this
off. The statistics line gets a second line: draws scanned whose program or variant was not resolved, how many of them
were predicted, and the time spent looking them up and building the predicted pipelines' descriptors.

1.4.3, Apple M4 Max, main at 30a1b93 (with PR #166), a copy of a save on the Great Sky Island, a first launch
emulated: Metal's shader caches moved aside for the run and put back afterwards, an empty translation cache (the app's
prepared shaders imported), no pipelines collected by the player, the warm-up finished before loading the save, then a
walk and camera turns. Every run starts from empty caches, so runs need no alternation. `TOTK_ASYNC_SHADERS=0`, so
draws wait for their pipelines (with async shaders on, see below). Frames after the title screen whose long-frame
entry has pipeline or library creation:

| warm-up | build | stall in those frames | pipeline creation on the submission thread | frames over 100 ms | longest frame |
|---|---|---|---|---|---|
| title list only (an area the shared list does not cover) | before | 11.7 / 12.0 s | 9.7 / 9.9 s | 19 / 18 | 3.01 / 2.58 s |
| | this change | 6.1 / 6.0 s | 4.4 / 4.3 s | 14 / 14 | 1.08 / 1.03 s |
| all lists (the shared list covers most of this route) | before | 3.9 / 3.9 s | 2.3 / 2.1 s | 13 / 13 | 626 / 747 ms |
| | this change | 3.5 / 3.7 s | 1.8 / 2.0 s | 13 / 14 | 620 / 643 ms |

The shared list's 1.4.3 rows (0bfbea9) build most of this route's pipelines during the warm-up, so the second pair has
little left to predict; the first pair warms only the title list (`DM_PSO_MANIFEST=build/pso_title.tsv`; the prepared
shaders' libraries are still warmed), as in an area no list covers yet. There, draws took 666-710 pipelines from the
background instead of 244-278, and 295-329 were compiled on the submission thread instead of 787-812; about 12,000 of
18,600 unresolved draws were predicted.

The cost is on the submission thread: looking the unseen draws up took 153-157 ms in a run and building the predicted
pipelines' descriptors 25-27 ms; a scan took 1.5-1.6 ms on average instead of 0.86 ms. More guesses are compiled in
the background and not taken (the same as for the other guesses). The steady frame did not change (frame p50 6.06 ms,
GPU p50 2.48-2.70 ms in both builds). With async shaders on (the default on the Mac) a skippable draw never compiles
on the submission thread, so no scan ran in a run of either build (2.0 s against 2.1 s of creation in long frames,
longest frame 178 ms against 422 ms); a guess is still taken by `apso_defer` through `pso_pend_state`.

Earlier runs of the same route on older bases, before the shared list had 1.4.3 rows: with PR #166 on 43f53b4,
13.3-14.2 s → 8.7-8.8 s of stall, 9.1-9.7 s → 4.2-4.3 s of pipeline creation, longest frame 3.5-3.8 s → 2.4-2.6 s
(native 4K, one run each: 13.1 s → 9.5 s); on d92f463 without PR #166, where one scan per submission stops at its
budget early in a world entry, 11.1 s → 9.8-10.1 s.

## Still done on the submission thread

- `pso_desc` for each guess, but no longer the patched functions it needs: a vertex function patched for varyings the
  fragment reads but the vertex shader does not write (`vs_fn_for`) or a depth-less fragment function
  (`fs_fn_without_depth`) not compiled yet is compiled in the background (`variant_defer`, the async variants' queue),
  and the guess is left to a later scan or to its draw. Predicting unseen programs met many such pairs: in one run
  building the guesses' descriptors took 571 ms on the submission thread, with a 2.0 s frame.
- `ds_scan` at the start of each pass calls `prog_ps_writes_depth` → `prog_get`, which can translate and compile a
  program of that pass. This is the path the pass needs anyway.
- A new program, or a new binding variant, whose shader is not loaded yet: at its draw, translation (when the
  translation cache does not have the variant), library compile and its pipeline compile, one after the other. With
  the warm-up finished this is rare in the world (3-4 libraries in the runs above); before it finishes, or with
  `DM_PSO_MANIFEST=off`, it is most of the stall.

## Checks

`scripts/verify_gfx.py` (`make probe-gfx`, no GPU drawing): prediction leaves the active scissor, conditional
counters and bindings untouched; an unresolved future program is skipped without translation or compilation; a
cached alternate variant is used without being selected; a missing variant is skipped; a program with an
untranslated stage is skipped; a depth-exporting fragment gets no depth-less guess; old completed slots are freed,
recent ones and unfinished ones are kept; an unseen program and an unseen binding variant of a drawn program are
predicted from loaded shaders through the variant index, with the variant of the draw's bound state, without loading a
library, creating the program or adding to its variants, and a variant the index names but no shader is loaded for is
not predicted. `TOTK_PROBE_NEGATIVE=24` (take the active variant whatever the state), `25` (free every slot), `26`
(ignore untranslated stages), `27` (guess depth-less pipelines for depth export), `28` (look the unseen variant up
without the draw's bound state), `29` (record it in the program) and `30` (create the program) each make the probe
fail at its own check.

## In-game comparison (1.2.1, Apple M4, 2026-10-19)

Copies of a field save and of the player's shader cache; warm-up off (`DM_PSO_MANIFEST=off`), so the route meets
many pipelines for the first time; after the save loads, the player is moved to Kakariko, Hateno, Rito and Goron,
40 s each. Long frames are the entries of the long-frame log between the first and the last move.

| | long frames | over 100 ms | over 1 s | total | worst |
|---|---|---|---|---|---|
| before PR #29 | 208 | 40 | 1 | 13.0 s | 1,151 ms |
| PR #29 and the follow-ups | 168 | 40 | 0 | 14.3 s | 682 ms |
| the same, `TOTK_PSO_PREDICT=0` | 224 | 32 | 0 | 14.3 s | 574 ms |

One session each, and another agent built and tested on the same Mac in between (a build overlapped the start of
the first row's session): the rows differ by no more than a session varies. No speed-up is claimed either way.

- Before the change the pending table was full by the end of the loading screen (about 500 guesses in the first
  14 scans, 384 slots); in the world a scan could start only one or two pipelines. Prediction was effectively off.
- With the change: no guess refused, 4,240 stale guesses freed, 5,113 pipelines started in the background and 859
  taken by draws; 120 of 200 scans stopped at the 8,192-command budget (0.51 ms per scan on average).
- Most of the stall on this route is programs seen for the first time: translation, library and then their
  pipeline. Prediction leaves them alone by design, and their cost is the same whether it is paid during the scan
  (before) or at the draw (now). What removes them from play is the shared shader list (`docs/shader-list.md`),
  whose rows the warm-up builds before the world shows.

## The contributor's observation

On an Apple M3 (24 GB, macOS 27.2, game 1.0.0) one session logged 32 long frames above one second, all with
library or pipeline creation; the worst was 10,384.9 ms of submission and presentation with 17.5 ms of GPU time.
With a broader local build (it also prefetched shaders, which is not part of this change) the player found severe
stalls much reduced. That was not a same-route comparison of this change alone.
