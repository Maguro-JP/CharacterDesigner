# 襟巻きの剣士の 3D（三面図から骨付きの VRM と glTF）

入力: `swordswoman-input-s0.jpg`（`library/feedback/settei/2026-10-18/swordswoman/swordswoman-1-main.jpg` の三面図を切り出して横に並べた物）。
道: `python3 tools/engine/chara3d.py swordswoman-input-s0.jpg out/`（膨らませた板の形、numpy と Pillow だけ）。種は使わない（s0）。
数字: 点 9,986、三角形 19,796、.vrm 1.38MB、作る 3.6 秒・撮る 13.1 秒（CPU、最大メモリ 122MB）。

| 絵 | 判定 | 残っている崩れ |
|---|---|---|
| swordswoman-front-s0.jpg | 途中 | 外形の縁が 1 マスごとの階段になる。顔は描いた絵を貼っただけで、写実の顔の不気味さは無い |
| swordswoman-side-s0.jpg | 戻す | 横から見ると板の厚みしか無く、前の絵と後ろの絵が真ん中で半分ずつに割れる。腕の所に梯子のような輪郭線の筋。横の絵は奥行きの幅にだけ使い、色に使っていない |
| swordswoman-back-s0.jpg | 途中 | 背面の絵が貼られる。縁の階段は正面と同じ |
| swordswoman-pose-s0.jpg | 途中 | 左腕を 70 度上げたが、腕が短く見え上がり方が小さい。右腕の後ろの赤い帯が腕と一緒に動き、帯の所に筋が出る。脚の踏み出しはほとんど見えない |

出来たかどうかの判断は利用者に渡す。

## TripoSR の形に同じ骨付けを通した物（Actions の実行 43727450848）

正面の絵だけを TripoSR（コミット 107cefdc、重み 5b521936、CPU）に渡し、出来た形（点 12,501、三角形 24,984）に `--mesh` で骨を付けた。模型の実行 19.6 秒、形の取り出し 13.9 秒。

| 絵 | 判定 | 残っている崩れ |
|---|---|---|
| swordswoman-triposr-front-s0.jpg | 戻す | 前の向きが合わず、正面の写しに横向きが写る（TripoSR の前の軸を読み替えていない）。色は点の色で濁り、顔は読めない |
| swordswoman-triposr-side-s0.jpg | 戻す | 横の写しに後ろ姿が写る（同じ向きのずれ）。厚みと脚の形は板より立体 |
| swordswoman-triposr-back-s0.jpg | 戻す | 同じ向きのずれ |
| swordswoman-triposr-pose-s0.jpg | 戻す | 区分が無いので重みが近さだけになり、腕を上げると垂れた襟巻きとスカートが一緒に持ち上がる |
