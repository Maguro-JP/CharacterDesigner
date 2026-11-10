# 服装の図鑑の見本（途中、2026-10-31）

`casts/fashion-zukan/characters/` の人物を `tools/gen/pipeline.py run <id> <出力> --until face`（`CD_BIBLE=casts/fashion-zukan`）で、人形の下絵、全身、顔の段まで描かせた絵です。手の段は通していません。どれも検品担当が「手以外も直す」と判定した途中の絵です。

| 絵 | 模型 | 種 | 判定 | 残っている崩れ | 設定との違い |
|---|---|---|---|---|---|
| zukan-jogakusei-hakama-s0.jpg | animagine-xl-4.0 | 0 | 戻す | 胸から袖の矢絣の柄がにじんで縦の筋の塊になる。袴の裾がぎざぎざでひだが割れる | 袴が膝丈で、脚が素肌になった |
| zukan-victorian-gentleman-s0.jpg | animagine-xl-3.1 | 0 | 戻す | 上着の後ろの裾が脚の後ろで半透明の灰色になる。手の崩れ | シルクハットが無く、チョッキが黒になった |
| zukan-mods-1960s-s0.jpg | animagine-xl-3.1 | 0 | 戻す | 胸ポケットの白い線が形なしで浮く。膝のしわが四角い塊になる。手の崩れ | ほぼ設定どおり |
| zukan-flapper-1920s-s0.jpg | animagine-xl-3.1 | 0 | 戻す | ドレスの上の方が肌と同じ色で境が弱い。手の崩れ | 釣鐘形の帽子とビーズの房飾りが無く、裾が波形になった |

描く言葉は各人物の設定（`look`、`outfit`、`turnaround.words`）と、`tools/gen/bible.py` の作風の言葉です。
