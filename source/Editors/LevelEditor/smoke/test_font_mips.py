"""The atlas of a distance-field font has MipLevels mip levels below its full size (3 by default), and its PixelPadding is what the count needs (the compiler uses the padding as it is set and warns when it is too small). The MTSDF font of the example project (PixelRange 3, PixelPadding 5: the 3 mip levels need about 8 - 3) is recompiled and what the compiler said and what the texture descriptor it wrote asked for are read back.
(The font compiler is its own executable: build plugins/xfont.plugin/build/xfont_compiler.vs2022 first when xfont_compiler.cpp changed.)
"""
import re
import time

from harness import REPO

PROJECT = REPO / "example.lionprj"
FONT_DESC = PROJECT / "Descriptors/Font/01/00/5549D8C8E9220001.desc/Descriptor.txt"          # Arial, MTSDF
FONT_LOG = PROJECT / "Cache/Resources/Logs/Font/01/00/5549D8C8E9220001.log/Log.txt"
TEXTURE_DESC = PROJECT / "Cache/Descriptors/Texture/93/EB/D28D2B241BAFEB93.desc/Descriptor.txt"   # the atlas, a virtual resource of the font


def test_the_atlas_of_a_distance_field_font_has_mips_and_the_padding_they_need(level):
    FONT_LOG.unlink(missing_ok=True)       # what is read back is from this compile, not from an earlier one
    FONT_DESC.touch()                      # the compile queue picks the font up again
    deadline = time.time() + 120
    line = ""
    while time.time() < deadline and "mip level" not in line:
        time.sleep(2.0)
        m = re.findall(r"Atlas dimensions: (\d+) x (\d+).*glyph padding (\d+)px for (\d+) mip level", FONT_LOG.read_text(errors="replace")) if FONT_LOG.exists() else []
        line = "mip level" if m else ""
    assert m, "the font compiler said nothing about the padding and the mips (is xfont_compiler built from the current source?)"
    width, height, padding, mips = map(int, m[-1])
    assert mips == 3
    assert padding == int(re.search(r"PixelPadding\"\s+;s32\s+(\d+)", FONT_DESC.read_text())[1]), "the padding is the one the user set: the compiler never changes it"
    assert padding >= 2 ** mips - 3, "and it is enough for the mips of this font (the PixelRange band of 3 pixels counts for part of the gap): the descriptor sets it for them"

    text = TEXTURE_DESC.read_text(errors="replace")
    assert re.search(r"GenerateMips\"\s+;bool\s+1", text), "the atlas gets mips"
    assert int(re.search(r"MinSize\"\s+;s32\s+(\d+)", text)[1]) == min(width, height) >> mips, "the mip chain ends after MipLevels levels below the full size"
