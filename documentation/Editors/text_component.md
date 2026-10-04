# The Text component

Flat text in the 3D world, drawn from the atlas of a **Font** resource. It lives in the render module (`LIONRender.dll`), like the Primitive: `dependencies/xLIONRender/src/xlionrender_text*.h`.

## What belongs where

| | |
|---|---|
| Font resource | the atlas, the glyph metrics, the kerning, how the atlas is encoded (MTSDF, SDF or BITMAP). The component never says. |
| `Text` component | what to write and how: `Font`, `Text`, `Size`, `Color`, `Opacity`, `HAlign`, `VAnchor`, `WrapWidth`, `LineSpacing`, `Orientation`, `SizeMode`, `DepthMode`, `Sort` |
| `Transform` | where it is |
| renderer | the laid-out glyphs and the GPU data, derived and rebuilt when the text, font, size, wrap or spacing change |

Defaults: faces where the entity faces, sized in the world, depth tested, not sorted.

## Rendering

- The text is a `std::wstring` (UTF-16 on Windows). Through the property system (`SetProperty`, the Inspector) it is UTF-8 and converted by `xproperty::settings::utf8_to_wstring` (not the C runtime: the "C" locale split every accented letter in two).
- A glyph is found by codepoint through the font's perfect hash; a surrogate pair is one codepoint. A codepoint the font lacks is drawn as U+FFFD or `?`, else nothing (counted as `Missing`). No shaping: no right-to-left text, no combining marks, no ligatures.
- BITMAP fonts use the glyphs of the baked size closest to the size the text is seen at (the biggest in the world); they have no kerning baked.
- One glyph is one **instance** of a unit quad (`xlionrender_text_vert.glsl`): the vertex shader places it in the world from the label's origin and axes, the orientation and the size mode. All labels sharing a font and a depth mode are **one draw call**. Instances are rebuilt every frame (camera, transform and color are not in a layout); the layout is cached per entity.
- Order: labels without `Sort` first, grouped by font and depth mode; then the labels with `Sort`, far to near. There is no CPU sort unless asked.
- `Orientation`: `Entity` (the entity's axes, scaled by its scale), `Camera`, `Upright Camera` (turns around the vertical axis only). `SizeMode` `Screen`: `Size` is pixels, the entity's scale is ignored.
- Text is double sided: seen from behind an `Entity` label is mirrored, not missing.
- Limits: 16384 glyphs per draw (a label that does not fit whole is dropped and counted in `Dropped`).

## The core owns a resource manager

Each copy of `LIONCore.dll` (one per Level) owns its own `xresource::g_Mgr`; `xlioncore::resources` (`dependencies/xLIONCore/src/resources/`) starts it with the project path and the device the first time the render module has both, and loads fonts on request (`GetFont`, retried once a second while the font is not compiled yet). The font **instance guid must be odd**: the resource manager tells a guid from a pointer by its lowest bit.

## Commands (for scripts and tests)

- `DescribeText -Scene s -Id e`: lines, quads, missing, bounds (em) of the layout, or why there is none.
- `DescribeTextDraw`: labels and glyphs sent by the last draw, draw calls made, labels dropped.

Tests: `smoke/test_text_layout.py` (layout), `smoke/test_text_render.py` (batching).

## Fonts of the example project

`Assets/arial.ttf` (proprietary; the example project only), `Descriptors/Font/01/00/5549D8C8E9220001.desc` (MTSDF) and `.../03/00/5549D8C8E9220003.desc` (BITMAP, 24 and 48 pixels).
