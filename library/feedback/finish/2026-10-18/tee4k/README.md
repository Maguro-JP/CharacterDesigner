# 4096 画素の仕上げ（Tシャツ・両腕を上げる・種 11）

Animagine XL 4.0。832x1216・28 段で描く → 1.5 倍に描き直す（strength 0.35）→ 顔と髪を 1024 画素で描き直す → Real-ESRGAN anime x4 で長辺 4096 → 1024 画素の区切り 20 個を strength 0.4 で描き直す（形の変わり方 0.001〜0.019、元に戻した区切り 0）。合計 約 52 分。

| 絵 | 判定 | 描かせた言葉 | 種 | 残っている崩れ |
|---|---|---|---|---|
| tee4k-armsup-s11.jpg | 途中 | full body, standing, arms raised above head, young adult woman in her early 20s, plain white t-shirt, blue jeans, sneakers, simple gray background | 11 | 検品の崩れ 1 件（測った値の外れ）。両脚がジーンズの中で 1 本に溶けている |
| tee4k-armsup-clean-s11.jpg | 途中 | 同じ絵に清書（cleanup.py）を掛けた | 11 | 線の粒 440 → 108、線の端 467 → 401、まだら 40.5 → 38.2。脚の溶けは清書では直らない |
