# Fonts

`segmdl2_compat.ttf` stands in for Segoe MDL2 Assets off Windows. The editor writes its icons as Segoe MDL2
code points, and that font ships only with Windows and can't be redistributed. This font puts a matching icon at
each code point the editor uses. `Build/tools/icon_font` builds it (`icon_map.txt` lists the code points).

A real `segmdl2.ttf` next to the executable or in `~/.local/share/fonts` is used instead when it is there.

The glyphs come from [Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons):

> MIT License. Copyright (c) 2020 Microsoft Corporation.
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation
> the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
> permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of
> the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
> WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
> COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
