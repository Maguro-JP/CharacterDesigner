# 服装の図鑑の人物を写実で描いた絵（途中）

写実の模型 RealVisXL V5.0 で、図鑑の人物 14 人を描いた。種は 0、30 歩、832×1216。描いた道具は `tools/gen/fashion_photo.py`（Actions の fashion-photo、実行 41209457557）。
1 人につき 7 枚: 正面（front）、背面（back、正面の絵を IP-Adapter 0.5 の手本にした）、細部 5 枚（head 頭、collar 襟と胸元、waist 腰、hem 裾、feet 足元。正面から切り出して 1024 に広げ、img2img 強さ 0.3 で布目を描き足した）。
判定と崩れは検品担当の結果を書く（検品中）。

| 人物 | 頼んだ服（outfit の頭） | 絵 | 判定 | 崩れ |
|---|---|---|---|---|
| 1947 年の Bar スーツ（New Look） | cream silk tailored jacket with rounded natural shoulders | `photo-bar-suit-1947-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1950年代のサークルスカート | fitted cream silk blouse with small rounded collar | `photo-circle-skirt-1950s-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1920年代のフラッパー | straight loose navy wool jersey dress with dropped waist | `photo-flapper-1920s-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1990年代のヒップホップ | oversized red and navy color-block nylon track jacket | `photo-hiphop-1990s-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 2000 年代〜の違う服を継いだ上着 | hybrid jacket spliced from a beige cotton gabardine trench coat upper and an olive nylon flight bomber lower half | `photo-hybrid-jacket-2000s-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 明治・大正の女学生（矢絣の着物に袴） | matte silk crepe kimono with purple and white yagasuri arrow pattern | `photo-jogakusei-hakama-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1966 年の女性のタキシード | black wool tuxedo jacket with satin peak lapels tailored to a woman's figure | `photo-le-smoking-1966-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1960年代のモッズ | slim three-button navy mohair-wool suit with narrow shoulders and short jacket | `photo-mods-1960s-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1965 年のモンドリアンの服 | sleeveless knee-length straight shift dress | `photo-mondrian-1965-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1993 年〜のプリーツ | permanently micro-pleated polyester column top and matching pleated trousers | `photo-pleats-1993-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 2000〜01 年の細身の男性の形 | very slim black wool suit with narrow shoulders | `photo-slim-suit-2000-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1970 年代半ばの芯の無い上着 | unstructured single-breasted jacket with soft natural sloping shoulders | `photo-unstructured-1970s-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 19世紀の紳士（フロックコートとシルクハット） | sharply tailored black wool frock coat with strong shoulders and nipped waist | `photo-victorian-gentleman-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |
| 1983 年ごろの布を巻くように裁った黒の服 | loose asymmetric black wrapped coat-dress cut like layered kimono panels | `photo-wrapped-black-1983-s0-front.jpg` ほか 6 枚 | 検品中 | 検品中 |

描いた言葉の全文は、人物の設定 `casts/fashion-zukan/characters/<id>.json` の look と outfit に、道具の写真の言葉を足したもの。
