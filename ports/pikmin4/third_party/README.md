# Third-party code in this repository

Every piece keeps its license; the license file sits next to the code. All are compatible with the port's
GPL-3.0-or-later.

| Folder | What | From | License |
|---|---|---|---|
| `maxwell_shader/` | The Ryujinx 1.3.2 shader translator, unchanged apart from the patches below (Ryujinx Team and contributors) (`Ryujinx.Graphics.Shader`, `Ryujinx.Common`, `Spv.Generator`) | MacNativeGames `vendor/ryujinx` @b75be8c (Ryujinx 1.3.2, unmodified there), with the four patches of `shader_translator/patches/` applied here | MIT (`maxwell_shader/LICENSE.txt`) |
| `shader_translator/` | MacNativeGames' `totk_xlate`: the service around that translator that turns the game's NVN shaders into SPIR-V; built as `ultrs-shaders.exe` by `tools/build_xlate.py` | MacNativeGames `games/totk/tools/totk_xlate` @b75be8c, without its macOS build script | MIT (`shader_translator/LICENSE`) |

Elsewhere in the tree: `src/gfx/tex/bc7enc/` (bc7enc and rgbcx, Rich Geldreich, MIT) and the files ported from
MacNativeGames (MIT), LASRecomp (MIT) and B2recomp (GPL-3.0), each named in its header comment;
`tools/shaders/inventory.py` (MacNativeGames, MIT).
