---
name: character-design
description: 「○○なキャラクターを作って」「○○風のキャラクターデザインを作って」「この作風で描いて」「新しい職業を足して」「ドット絵にして」「リアル風にして」と言われたとき、このリポジトリでキャラクターデザインを出すときに使う。まずアニメ風のデザインを画像生成で描いて見せ（tools/gen/design.py draw）、派生（リアル風、ドット絵、3D）は指示を受けてからその絵から作る。箱庭ドットの職業を部品で組む作業（styles/*.json、characters/*/parts.json、tools/build.py）もここ。描画器そのものを直す作業には使わない。
---

# キャラクターデザイン

「本当にその作風だ」と言える水準で出す。数字が通っただけで良しとしない。

## 0. 頼まれたときの流れ

1. まずアニメ風のデザインを描いて見せる。種を変えて数枚出し、選んでもらう
   `PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py draw out.png "<人物の説明（英語）>" --n 4`
   （初めての環境では `sh tools/gen/setup.sh`。CPU で1枚 約1分）
2. 派生は指示を受けてから、選ばれた絵から作る。文章から作り直さない（同じ人物を保つため）
   - リアル風: `design.py restyle in.png out.png --style real`
   - ドット絵（等身を保つ少ない色）: `design.py pixel in.png out.sprite.json --preset survivor`
   - 箱庭ドット: 頭を大きくする変換が要る（未完成）。部品で組む場合は下の 1〜3
   - 3D: `tools/engine/`（Blender＋MakeHuman、試作）
3. 出したものは画像で見せる。並べた図は `tools/vsref.py`、ドット絵の数字は `tools/check.py` と `tools/learn.py score`

## 1. 作風を決まりに落とす

作風が `styles/` に無ければ、先に作る。`styles/diorama.json` が見本。

- `sources`: 何を見て決めたか。記事、インタビュー、実物の画像のページ
- 数えられるもの: `canvas`（大きさの範囲、体格の枠 `frames`）、`proportion.heads_tall`、`palette.max_colors`、`outline`、`cleanup.max_orphan_pixels`
- `render`: 箱庭ドット 用の部品から描き分けるときの変換（キャンバス、`shift`、`transforms`。頭は `parts: "head"`）
- 実物を見られないまま記憶で置いた数字には `"unverified": true` を付け、`docs/reports/pending.md` に見たいサイトのドメインを書く

画像そのものはリポジトリに置かない。置くのは数字と出典だけ。既存のキャラクターを写さない。

## 2. キャラクターを部品で組む

似た職業があれば `base` で継承して、差分だけ書く。書き方は `tools/build.py` の `load_spec` と `frame_spec` の説明にある。

- `remove` `override` `add`（`after` `before` で重ね順）、`materials`、`touchups`（目や鼻の1ドット）
- 動き: `frames`（`dy` 呼吸、`move` 脚の前後、`body_dy` 上下動、`override` 構えの差し替え）。`mirror_frames: true` で右向き
- 体格: `transforms`、子供は `frame: "child"`
- 書いたら `python3 tools/fmt.py characters/<名前>/parts.json`

## 3. 描いて確かめる

```bash
python3 tools/build.py characters/<名前>/parts.json [--style <作風>]
python3 tools/check.py characters/<名前>/sprite.json styles/<作風>.json
python3 tools/compare.py out.png 前=<旧 sprite.json> 後=<新 sprite.json>
python3 tools/anim.py --anim walk out.gif characters/<名前>/sprite.json
python3 tools/faces.py out.png   # 全キャラクターの全コマの頭
python3 tools/vsref.py out.png ref=<手本.png>@x0,y0,x1,y1 me=<sprite.json>@x0,y0,x1,y1   # 手本と同じ倍率で並べる
python3 tools/learn.py score styles/diorama.learned.json characters/*/sprite.json   # 手本の全コマの分布からの外れ
```

直す順番は `tools/learn.py score` で決める。手本の全コマ（728 コマ）から学んだ平均とばらつきに対して、特徴ごとの外れ（z）を出す。1体の手本だけを見て直すと、その1体の癖まで写す。手本のシートを足したら `tools/learn.py fit` で学び直す。

比較画像を実際に開いて見る。比べる相手は自分の前の版ではなく手本。部位を直すたびに `tools/vsref.py` で手本の同じ部位と横に並べ、1ドットの置き方は `--dump` で文字に起こして読む。見るもの:

- 職業と体格が輪郭と色で読めるか。並べたほかのキャラクターと見分けられるか
- 部品が隠れていないか。読めないときは形より先に重ね順を疑う
- 顔の1ドットが意図どおりの位置にあるか。継承した `touchups` が合っているか
- 顔は `tools/faces.py` で全コマ（呼吸、歩き、右向き）を見る。最初の1コマだけで良しとしない
- 目の組み方は `docs/knowledge/tech.md` の「顔の足し算と引き算」に従う。奥の目、黒目、白目は同じ行に揃える
- 舞台の図（`tools/render.py`）で沈んでいないか

色数が上限を超えたら、使うドットの少ない段から素材どうしで色を共有する。

## 4. 残す

- 比較画像と判定を `docs/progress/` に置く（良くなった所、弱い所を両方書く）
- 分かったことは `docs/knowledge/`、決めたことは `docs/knowledge/decisions.md`
- `python3 -m unittest discover -s tests` を終了コードで確かめる（`| tail` の後ろに `&&` をつながない）
