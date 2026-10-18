# 設定画 2026-10-18（剣士 swordswoman）

| 絵 | 判定 | 中身 | 残っている崩れ |
|---|---|---|---|
| swordswoman-1-main.jpg | 戻す | 三面図（正面・横・背面）、5.53 頭身の目盛り、色指定 5 部位、持ち物、注記 | 三面図の服が設定と違う（袴がスカートとタイツ、正面の頭が帽子の形、背面に赤い頭巾）、正面に手が無い |
| swordswoman-2-expressions.jpg | 途中 | 表情 9（怒り・照れ・決意・抜刀・大笑い・ふだん・悲しみ・笑顔・驚き） | 表情の差が小さいもの（ふだんと決意）がある |
| swordswoman-3-details.jpg | 戻す | 部位の拡大 4（目・髪・靴・上着）と線画 | 髪と靴の拡大が全身に近い枠、髪の拡大で目が赤い（設定は茶） |

描かせ方: `bible.py turnaround swordswoman --count 1`（約 29 分）、`bible.py expressions swordswoman`（約 39 分）、`closeup.py swordswoman --only eyes,hair,outfit-upper,outfit-shoes`（約 7 分）、`settei.py`（約 40 秒）。模型は設定資料集の既定（anime）。
