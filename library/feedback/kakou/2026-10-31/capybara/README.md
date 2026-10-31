# capybara: 画風と加工の整理で足した 41 の加工

元絵: 動物の毎時の周で描いた 23-real（SDXL、種 1）。`library/feedback/stylize/2026-10-19/capybara/capybara-base-s1.jpg`
加工: `python3 tools/gen/catalog.py 元.png 出力 [名前か組]`（模型なし。768×512 の 1 枚に、目録の全部 64 種で 30 秒、メモリ最大 167 MB）

| 絵 | 判定 | 残っている崩れ |
|---|---|---|
| lineart / lineart-pencil / lineart-color | 通す | 毛並みの線が多い（元絵の毛の描き込みをそのまま拾う） |
| lineart-bold | 通す | 地面の水たまりも被写体と取り、外形の太線が付く |
| manga-shonen | 通す | なし |
| manga-shoujo | 通す | なし |
| manga-gekiga | 途中 | ベタが体の半分を覆う（劇画としては多め） |
| manga-flat | 通す | なし |
| softpastel / gouache / marker / cel-noline | 途中 | 元絵との差が小さい |
| yumekawa / ballpoint / newspaper / risograph / chiyogami / marbling / neontube / lowpoly / postimpressionist / pointillism-fine | 通す | なし |
| woodcut | 途中 | 体の大半が墨になる（暗い毛の動物で彫り跡が少ない） |
| crossstitch | 途中 | 糸の色が淡く、絵が霞んで見える |
| focus-lines / speed-lines / fisheye / vignette / glitch / anaglyph / chromatic / oldphoto / tiltshift / bloom / rays / sparkle / mirror / swirl / wave / koma | 通す | なし |
| kaleidoscope | 途中 | 被写体の一部しか写らない |
