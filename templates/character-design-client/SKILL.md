---
name: character-design
description: この作品のキャラクターやモンスターのデザインを描く・描き足す・選び直す・ドット絵にするときに使う。「○○のデザインを作って」「この系統の進化を描いて」「ドット絵にして」と言われたとき。道具は Maguro-JP/CharacterDesigner にあり、そのリポジトリを足して使う。ゲームのコードを直す作業には使わない。
---

# キャラクターデザインの作り方（この作品用）

デザインを描く道具と決まりは Maguro-JP/CharacterDesigner にある。このリポジトリには、決まったデザイン（決定稿）と
この作品の状態だけを置く。道具の使い方を変えたら CharacterDesigner 側を直す（ここに写して直さない）。

## 1. 準備（新しいセッションで1回）

1. CharacterDesigner をセッションに足して clone する（add_repo で Maguro-JP/CharacterDesigner）
2. CharacterDesigner で `sh tools/gen/setup.sh`（画像生成の部品を .cache/gen に入れる。数 GB、初回 十数分）
3. 決定稿を描いた絵の置き場に写す: `mkdir -p .cache/gen/out/<作品> && cp <このリポジトリ>/{{DESIGN_DIR}}/base/*.png .cache/gen/out/<作品>/`

## 2. どの道具をどう使うか（すべて CharacterDesigner で動かす）

| やること | 道具 | 使い方 |
|---|---|---|
| 1人を試しに描く | `tools/gen/design.py draw` | `PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py draw out.png "<英語の説明>" --n 4` |
| 設定集の全員を描く | `design.py batch` | `PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py batch casts/{{CAST}}.json .cache/gen/out/<作品>` |
| 一覧図にする | `design.py sheet` | `python3 tools/gen/design.py sheet casts/{{CAST}}.json .cache/gen/out/<作品> sheet.png` |
| ドット絵にする | `design.py pixel` | `python3 tools/gen/design.py pixel <絵> <出力>.sprite.json --preset monster96`（高さ 96、24 色） |

- 設定集（`casts/{{CAST}}.json`）に1人1行。人は `gender`（male / female / androgynous）と `age`（child / teen / adult / middle / elder）、
  人でない者は `kind: "creature"`。体型・肌・皮膚・刺青・骨格・耳・輪郭・鼻・比率・筋肉・脂肪・角・亜人間は `traits`（一覧と効き目は
  CharacterDesigner の `tools/gen/traits.json` と `docs/knowledge/traits.md`）
- モデル: 人は SD1.5 系のアニメ風（中年・老人は自動で SDXL 系）、モンスターは SDXL 系。2つを同時に動かさない（メモリ不足で強制終了される）
- 系統（進化）は、先にベースの1体を決めて `chosen` に seed を書き、ほかの段階に `"from": "<ベースの id>"` を書いて派生させる
- 1枚 約1分（CPU）。長く回すときは裏で流し、終わってから見る

## 2.5 描いた絵の一部だけを直す（服やほかを変えない）

| やること | 使い方 |
|---|---|
| 部位を塗り分ける | `PYTHONPATH=.cache/gen/lib python3 tools/gen/edit.py parts <絵>`（顔・腕・脚・髪・服・靴） |
| 肌の色を変える | `edit.py recolor <絵> <出力> --region skin --color '#4a7ad0'`（画像生成なし） |
| 部位だけ描き直す | `edit.py inpaint <絵> <出力> --region skin_arms --strength 0.85 --prompt "<英語>"` |

- 範囲の外は元の画素を貼り戻し、範囲の外で変わった画素の数を毎回出す（0 でなければ失敗）
- 確かめたパターン（肌の色、腕の刺青、体型、角など）は CharacterDesigner の `library/patterns.json` に、コマンドと見本の絵つきで入っている。
  設定集で `"patterns": ["名前"]`、または `command` のとおりに流す。効き目の記録は `docs/knowledge/traits.md`
- 体の部品は、服を着た姿ではなく素体（`"framing": "body"`、無地の肌着）で決める。服に引っ張られないため
- まだできないもの: 鱗、角や耳を後から足す、服の着せ替え（traits.md の最新の結果を見る）

## 3. 検品

- 指定していないところ（服、ポーズ、髪、ほかの部位）が変わった絵を「できた」と言わない。変わった点を添えて報告する
- 描いた絵は1枚ずつ見る。落とすのは体の破綻（頭・脚・翼・尾の数、途切れ、融合、人型にしない者の二足立ち）だけ。
  色や細部が設定と違う絵は落とさず、違う点を添えて候補に残す（決めるのは利用者）
- 落とした絵は設定集の `rejected` に `{"画像の名前": "理由"}`。もう一度 batch すると足りない分だけ次の seed で描く
- 検品表: CharacterDesigner の `docs/knowledge/monster-design.md`

## 4. 決まったら

- 利用者が選んだ seed を `chosen` に書く（CharacterDesigner の設定集）
- 決定稿の絵とドット絵を、このリポジトリの `{{DESIGN_DIR}}/` に置いて push する。状態の表（`{{DESIGN_DIR}}/README.md`）を直す

## やらないこと

- 自前の図形（SVG の部品）でキャラクターを組む・下絵にする（利用者の評価: Claude の図形デザインは嫌い）
- 既存作品の特定のキャラクターを写す
