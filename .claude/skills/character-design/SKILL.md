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
   - モンスターのドット絵（解像度高め、標準）: `design.py pixel in.png out.sprite.json --preset monster96`
   - 箱庭ドット: 頭を大きくする変換が要る（未完成）。部品で組む場合は下の 1〜3
   - 3D: `tools/engine/`（Blender＋MakeHuman、試作）
3. 出したものは画像で見せる。並べた図は `tools/vsref.py`、ドット絵の数字は `tools/check.py` と `tools/learn.py score`

### 作品の登場人物をまとめて頼まれたとき（何人も、系統や進化がある）

依頼された作品は、デザインを作れるようになるための題材。作品の資料はその作品のリポジトリから読み、
このリポジトリには設定集（`casts/<作品>.json`）と決まり（`docs/designs/<作品>.md`）だけを置く。

1. 作品の資料を読み、作風・共通の印・系統ごとに残す印・段階の形を `docs/designs/<作品>.md` に決める。1体ずつ思いつきで書かない
2. 設定集に1人1行で書く。人は `gender`（male / female / androgynous。男女は体と顔の骨格から描かれる）と `age`（child / teen / adult / middle / elder。中年と老人は自動で SDXL 系）、人でない者は `kind: "creature"`（SDXL 系で描き、人の決まり文句を付けない）。
   モンスターの指示文は `docs/knowledge/monster-design.md` の3節の書き方（元の動物の名詞から、部位の数、3色）
3. 系統があるなら、先に各系統のベースの1体を決める（候補を6案ほど描き、検品し、選んでもらう）。ほかの段階はベースを手本に派生させる。
   系統ごとに別々に描くと、同じ系統で違う生き物が生まれる
4. `design.py batch casts/<作品>.json <出力>` → 1枚ずつ検品表で見る（指定していないところが変わった絵を「できた」と言わない。変わった点を添えて報告する） → 落とした絵は `rejected` に理由を書く → もう一度 batch（足りない分だけ描く）
   → `design.py sheet` の一覧図で見せる
5. 同じ破綻が続いたら指示文の書き方を直し、`docs/knowledge/monster-design.md` の6節に足す
6. 依頼先のリポジトリ（作品のリポジトリ）に送る。その作品のセッションが自分で続きを作れるようにするため:
   - `templates/character-design-client/SKILL.md` の `{{DESIGN_DIR}}` と `{{CAST}}` を埋めて、依頼先の `.claude/skills/character-design/SKILL.md` に置く
   - 決定稿の絵・ドット絵・候補の一覧と、状態の表（README.md）を依頼先の決めた置き場に置く（DigiMon は `design/beasts/`、RuleCrawler は `docs/designs/`）
   - push の仕方は依頼先の決まりに従う（どちらも main へ直接、1回にまとめる）。決定稿が増えたら、その都度送り直す

やらないこと: 自前の図形（SVG の部品）でキャラクターを組む・下絵にする（利用者の評価: Claude の図形デザインは嫌い）。
2つのモデルを同時に動かす（メモリが足りず強制終了される）。

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
