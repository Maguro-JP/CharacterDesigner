---
name: character-design
description: 「○○風のキャラクターデザインを作って」「この作風で描いて」「新しい職業を足して」「16ビット機風にして」と言われたとき、このリポジトリで作風を調べて決まりに落とし、部品で組んで描き、検品して出すときに使う。styles/<作風>.json と characters/<名前>/parts.json を書き、tools/build.py・check.py・compare.py で描いて確かめる。描画器そのものを直す作業や、ドット絵以外の画像生成には使わない。
---

# キャラクターデザイン

「本当にその作風だ」と言える水準で出す。数字が通っただけで良しとしない。

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
```

比較画像を実際に開いて見る。見るもの:

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
