# 空気感と環境の光（エフェクトと光の使い方）

絵の「どこにいるか」は、人物より先に光と空気で伝わる。ここは、空気感ごとに何を足すと伝わるかを決まりに落としたもの。
道具は `tools/gen/atmosphere.py`（描いた絵に後から掛ける）と、描く言葉に足す言葉（下の表の「描く言葉」）。
数字は目安で、絵ごとに強さで調整する。

## 共通の決まり

- 空気遠近: 遠い物ほど空の色（多くは青灰）に寄り、明暗の差と彩度と細部が減り、縁がぼける。手前ほど濃く鋭い
- 光の筋（光芒・ゴッドレイ）は、空気中の粒（ほこり・湿気・煙）に光が当たって見える。粒の無い所に筋は出ない。
  筋は光源から放射状に広がり、遮る物（窓枠・葉・山）の隙間からだけ出る。筋の中に粒を散らすと空気が見える
- 光源は1つの主光と、補助の光。主光の色と、影の色（補色に寄る）で温度を決める。暖かい主光なら影は冷たく、逆も同じ
- 足すのは「光の層（明るくする: スクリーン・加算）」と「空気の層（全体を一色に寄せる: 霞）」と「影の層（暗くする: 乗算）」の3つ。
  絵の上に別の層で置き、強さで混ぜる（下絵は壊さない）

## 空気感ごとの決まり

| 空気感 | 光 | 空気 | 色 | 描く言葉（Animagine） |
|---|---|---|---|---|
| 神々しい光 | 上から斜めに太い光の筋。光源の周りに光のにじみ（ブルーム）。人物の縁に光の縁取り | 薄い霞。筋の中に光の粒 | 暖かい白〜金。影は薄い青 | god rays, light rays, divine light, backlighting, glowing, light particles |
| ほこりっぽい | 細く鋭い光の筋（窓から） | 黄土色の霞で遠くを潰す。粒（ほこり）を多く散らし、筋の中は明るく | 彩度を落とし、黄土に寄せる | dust, dust particles, hazy, sunbeam, abandoned, muted colors |
| 木漏れ日 | 楕円の光の斑点（葉の隙間の形でなく、太陽の像なので丸〜楕円）。斜めの細い筋 | 緑がかった湿った空気、薄い霞 | 光は暖かい黄、影は緑〜青 | dappled sunlight, komorebi, sunlight filtering through leaves, forest, light spots |
| 地下 | 火の光（橙〜赤）が近くで強く、離れると急に落ちる。上からの光は無い | 煙で暗く、周りは黒に沈む（周辺減光が強い） | 光は暖かい橙、影は冷たい青黒。全体の彩度は低い | underground, dungeon, cave, torchlight, dark, dim lighting, warm light |
| 宇宙 | 暖かい主光（恒星）と冷たい補助光。星雲の色の縁取り（リムライト） | 空気は無い（霞を足さない）。背景は黒に近く、星の点 | 黒〜紺の地、星雲の紫・青・桃 | space, starry sky, nebula, galaxy, rim light, cosmic |
| 霞（遠近） | 光は弱め | 空の色で全体を均一に覆い、下（地面）より上（遠く）を濃く | 青灰 | atmospheric perspective, fog, mist, depth |

## 確かめていないこと・限り

- 木漏れ日の斑点が丸〜楕円になるのは、葉の隙間がピンホールの働きをして太陽の像を映すため（物理の知識から書いた。今回の検索では絵の解説の出典は取れなかった）
- 後から掛けるエフェクトは、絵の中の物の前後を知らない。光の筋は人物の前にも重なる（人物の後ろにだけ出すには、人物を切り出したレイヤーで抜く）

## 出典

- 光の筋と空気中の粒、空気遠近: [Volumetric lighting（Wikipedia）](https://en.wikipedia.org/wiki/Volumetric_lighting)、[Atmospheric Perspective in Digital Art（TourBox）](https://www.tourboxtech.com/en/news/atmospheric-perspective.html)
- ペイントソフトでの光の筋（ブラシと描画モード、フィルター）: [Krita Artists](https://krita-artists.org/t/how-would-i-directly-paint-a-sunray-or-god-ray-in-krita/72894)、[ibisPaint 講座](https://ibispaint.com/lecture/index.jsp?no=150)、[CGarchitect: Volumetric effects / god rays](https://cgarchitect.com/features/articles/6d94fcde-mastering-the-art-of-volumetric-effects-god-rays)
- 地下の火の光（暖かい色、近くだけ照らす）: [Science Friday: Lighting design for your paleolithic cave](https://www.sciencefriday.com/segments/lighting-design-for-your-paleolithic-cave/)、[artnet](https://news.artnet.com/art-world/prehistoric-cave-art-proto-cinema-1994505)
- 宇宙の光（暖かい主光と冷たい補助光、星雲の色の縁取り、低い環境光）: [Daz3D: Tips & Tricks For Space Scenes](https://www.daz3d.com/forums/discussion/13170/)、[ImagineFX: rim light](https://www.pressreader.com/australia/imagine-fx/20141010/281865821712703)
- 木漏れ日（光の斑点、印象派の題材）: [LuceLight: Komorebi](https://www.lucelight.it/en/notizia.php/138334-komorebi-and-the-emotional-potential-of-an-optical-accessory)
