# 作ったデザインと続きの作り方

このフォルダには、依頼された作品のデザインのうち、決まったもの（決定稿）と、次に選ぶ候補を置く。
描いた絵の全部は置かない（1枚 約 1MB）。候補は同じ設定集・同じ seed で描き直せる。

作り方の決まりと手順:

- 手順: `.claude/skills/character-design/SKILL.md` の「作品の登場人物をまとめて頼まれたとき」
- モンスターの書き方と検品表: `docs/knowledge/monster-design.md`
- 作品ごとのデザインの決まり: `docs/designs/<作品>.md`
- 設定集（指示文、決定稿 `chosen`、検品で落とした理由 `rejected`、利用者が選び直した絵 `overruled`）: `casts/<作品>.json`

## 準備（新しいセッションで1回）

```sh
sh tools/gen/setup.sh          # 画像生成の部品を .cache/gen に入れる（数 GB、初回 十数分）
O=.cache/gen/out/digimon       # 描いた絵の置き場（git の外）
mkdir -p $O && cp designs/digimon/base/*.png $O/   # 決定稿を置く。派生の手本はここから読まれる
```

モンスターは SDXL 系（DreamShaper XL Lightning）で描く。初回に約 7GB を取得する。
系統の派生には IP-Adapter（h94/IP-Adapter の sdxl_models と image_encoder、約 3.2GB）も取得する。
2つのモデルを同時に動かさない（メモリ 15GB を超えて強制終了される）。

## DigiMon（`casts/digimon.json`、決まりは `docs/designs/digimon.md`）

| 系統 | ベース（成長期） | 状態 |
|---|---|---|
| トルネ | `base/tor-3-xl-9.png` | 決定 |
| ハク | `base/hak-3-xl-10.png` | 決定 |
| エンボウ | `base/emb-3-xl-9.png` | 決定 |
| カメロ | `base/kam-3-xl-9.png` | 決定 |
| ライトリ | `base/rai-3-xl-7.png` | 決定 |
| ゴロン | 未定 | 候補 `candidates-gor-yor.jpg`（16、15 を推す。どちらもロボット寄り） |
| ヨル | 未定 | 候補 `candidates-gor-yor.jpg`（7、11 を推す） |

- ドット絵: `pixel96/<id>.sprite.json`（高さ 96、24 色）。見本は `pixel96/<id>-x3.png`、64 との比較は `pixel-64-96.png`
  作り方: `python3 tools/gen/design.py pixel <絵> <出力>.sprite.json --preset monster96`
- 決定稿の候補一覧: `candidates-chosen-lines.jpg`（選ばれなかった案も含む）

### 次にやること

1. ゴロンとヨルのベースを利用者に選んでもらい、`casts/digimon.json` の `chosen` に seed を書く
   （候補の絵は `PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py batch casts/digimon.json $O` で同じ seed のまま描き直せる。
   ベース以外の段階まで描かないよう、ベースだけの設定集を切り出して流す）
2. 各段階に `"from": "<系統のベースの id>"` を書き、ベースを手本に派生させる（`from_scale` 既定 0.6）。
   派生はまだ一度も実際に描いていない（コードと試験のみ）。1系統で試してから広げる
3. 描いた絵を検品表で見て `rejected` に理由を書く。色や細部の不一致では落とさず、違う点を添えて候補に残す
4. 決まった絵を `--preset monster96` でドット絵にする

## RuleCrawler（`casts/rulecrawler-*.json`）

- 迷宮定石の探索者: 決定稿 `rulecrawler/joseki-explorer-7.png`（アニメ風、SD1.5 系）
- 深層ギルドの主（モンスター16体と人4体）、迷宮指南の妖怪と主人公: `rulecrawler/*-unreviewed.jpg`。描いたが検品していない
- 深層ギルドの職（10職×男女）: 男女を骨格から描き分ける書き方に直したあと、まだ描き直していない
