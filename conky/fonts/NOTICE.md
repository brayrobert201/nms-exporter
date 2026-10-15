# Fonts

`NMS-Glyphs-Mono.ttf` draws the sixteen portal glyphs: the characters `0-9` and
`A-F` are the symbols, so a twelve-character portal code renders as the
glyphs you see in the game. It comes from the No Man's Sky Community
Developers' tools (for example github.com/NMSCD/amiinthefade, `src/fonts/`),
where it ships alongside GPL-3.0 code; the font file itself carries no licence
statement of its own. It is not used for anything but the glyph row on the
traveller screen. `install.sh` puts it in `/usr/local/share/fonts/nms/` so
conky (via fontconfig) can find it; fontconfig family `NMS Glyphs`, style
`Glyphs-Mono`.
