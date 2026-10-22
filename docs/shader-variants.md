# Shader variants from the code, not from play

A game shader is translated for the bind state of a draw (`deps`: texture kinds, image formats, vertex input and
fragment output types). Until 2026-10-22 almost every bound texture slot was a dependency, so one shader had up to nine
variants, and the ones a build did not carry had to be met in play and collected in the shared list
([shader-list.md](shader-list.md)). An iPhone or iPad, which cannot translate, skips draws whose variant it lacks.

## What the variants differed in (measured 2026-10-22)

The shared list then held 51,077 variants of 43,651 shaders; 9,917 were not the default bind state. Comparing the MSL of
every pair of variants of one shader in a Mac translation cache (20,039 variants, SSA numbers normalised), no pair
differed in its logic, only in declarations:

| Difference | Variants | What the MSL shows |
|---|---|---|
| Texture dimension (2D / array / 3D / cube) | 3,804 (38 %) | Nothing: the translator reads the dimension from the sampling instruction; only the recorded deps differed (861 identical pairs) |
| Depth-format texture | 3,620 (37 %) | `depth2d…` declaration. 1,248 of 1,316 depth slots are only compare-sampled (shadow maps) |
| Integer vertex input | 2,364 (24 %) | `uint4` input; 834 of 837 are, in the float variant too, only bitcast to integers or used as indices |
| Integer colour output | 130 (1 %) | `uint4` output |

## What the translator does now (`games/totk/tools/totk_xlate/Service.cs`)

- A texture slot whose kind it did not query (Ryujinx queries it only for size queries, 1D / buffer and bindless) is
  recorded as `"*"`, or `"*_depth"` when a depth-format texture is bound and the code reads it without a compare.
- A slot only ever compare-sampled is declared depth whatever is bound and is no dependency. The old variant cast the
  colour declaration to depth in the shader (`spvDepthCast`), so the GPU samples the same texture the same way.
- A vertex input the request does not answer is typed by its use: `uint` when every value loaded from it is only bitcast
  to an integer, converted to one or used as an index. Measured on the variants the game translated with real answers:
  834 of 837 integer inputs found, no float input taken for an integer one. An answered input keeps its answer.

The runtime (`totk_shader_rt.m deps_match`) and the seed (`prepare_shader_seed.py deps_match`) match `"*"` to any
non-depth answer and `"*_depth"` to any depth one; an unanswered vertex input (not bound) matches any variant.

## The seed

Tears of the Kingdom's seed now translates every shader the build finds for the default bind state (28,769 in 1.4.3,
up from the 12,472 of the startup packages). A shared-list row is translated only when no variant already made serves
its bind state; a row served by another variant goes into `<seed>.aliases.tsv`, and the packaging renames the warm-up
rows through it (`shader_list.py rename`), since rows recorded on a player's Mac name the variant translated there.

What still needs its own variant: a depth texture read without a compare (61 shaders), a queried texture kind other than
2D, an integer colour output, and an integer vertex input used as a float somewhere. The shared list keeps naming those.

Render pipelines (`R` / `B` rows) are not covered: they combine two shaders with render target formats, blending and the
vertex layout, which the game's materials decide, not the shader code. A missing pipeline costs one Metal pipeline build
when first drawn; it never leaves a draw out.
