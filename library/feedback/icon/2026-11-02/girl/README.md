# 美少女とペンタブのペンと CD のアイコン

顔: Animagine XL 4.0（CPU、bfloat16、832x832、24 段、guidance 5、Euler a）。tools/icon/draw_girl.py
言葉: 1girl, solo, beautiful girl, portrait, head and shoulders, three-quarter view, face turned to the left, looking to the side, long flowing hair, detailed beautiful eyes, gentle smile, delicate features, simple white background, masterpiece, high score, great score, absurdres
ペンと CD: tools/icon/app_icon.py（ペンは Pillow で円柱の陰影を付けて描く。CD は Inter Display Black Italic）

ペンの形は、ペンタブ用のペンに合わせた。グリップが一番太く後ろに行くほど細い軸、横のボタン 2 つ（持つ角度で左側）、
短い円すいの先から出る丸い先の POM（低摩擦プラスチック）の芯（太さ約 1mm）。ワコムの形と名前は写していない。

| 絵 | 判定 | 崩れ |
|---|---|---|
| girl-base-s11.jpg | 土台 | 斜め 45 度ではなく横顔に近い |
| girl-base-s12.jpg | 土台 | 右向き。アイコンでは左右を反転して使う。胸元の紐が途中で切れる |
| girl-pc-s12.jpg | 採用（PC 用、chatdraw/icon/app.png） | 胸元の紐が途中で切れる |
| girl-mobile-s11.jpg | 採用（スマホ・タブレット用、chatdraw/icon/mobile.png） | 顔が横顔に近い |
