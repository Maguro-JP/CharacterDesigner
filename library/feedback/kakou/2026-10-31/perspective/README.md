# perspective: 背景のパースの測り方

`PYTHONPATH=.cache/gen/lib python3 tools/gen/perspective.py 背景.png 重ねた図.png`。元は `bible/worlds/citadel/loc-gate.jpg` と `loc-hall.jpg`。
赤の放射線が見つけた消失点、黄の横線がそこから出した地平線。

| 絵 | 判定 | 数字 | 残っている崩れ |
|---|---|---|---|
| perspective-gate | 途中 | 縦の傾き 1.0 度、集まる割合 0.51 | 奥へ向かう線が少なく、消失点が左の壁の所に出る |
| perspective-hall | 通す | 縦の傾き 7.8 度、集まる割合 0.42 | 柱がすぼまって傾く（広角の 3 点透視）を数字で拾えた |
