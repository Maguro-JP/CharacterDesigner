# CharacterDesigner

「○○風のキャラクターデザイン」を、作風の決まりに落として描き、検品して出す道具。
最初の到達点は HD-2D（オクトパストラベラー系）のドット絵。

![手打ちの v3 と部品組みの v4 の戦士](docs/progress/2026-09-29-warrior-v3-vs-v4.png)

## 主な機能

- 部品（楕円、多角形、太さのある線）と素材でキャラクターを組み、光を当てて高い解像度で描き、ドット絵に落とす
- 作風の決まり（`styles/*.json`）と突き合わせ、大きさ・頭身・色数・輪郭・孤立ドットを数える
- 検品用の拡大図と、HD-2D 風の舞台に置いた図を描き出す
- 版どうしを1枚に並べた比較画像を作る

## 動作環境

- Python 3.11 以上
- Pillow

## セットアップ

1. `pip install pillow`

## 使い方

```bash
# parts.json からドット絵（sprite.json）を書き出す。--preview で縮小前の絵も出す
python3 tools/build.py characters/hd2d-warrior-v4/parts.json --preview out/

# 別の作風で描く（styles/ff6.json の render）。characters/<名前>/ff6/sprite.json に出る
python3 tools/build.py characters/hd2d-warrior-v4/parts.json --style ff6

# 作風の決まりで検品する（外れがあれば終了コード 1）
python3 tools/check.py characters/hd2d-warrior-v4/sprite.json styles/hd2d.json

# 拡大図と舞台の図
python3 tools/render.py characters/hd2d-warrior-v4/sprite.json out/

# parts.json を読みやすい幅に整える（試験で整っているかを見る）
python3 tools/fmt.py characters/*/parts.json

# 動きのコマを GIF と並べ図にする（--anim は idle、walk、right-idle、right-walk）
python3 tools/anim.py out/idle.gif characters/hd2d-warrior-v4/sprite.json
python3 tools/anim.py --anim walk out/walk.gif characters/hd2d-swordsman/sprite.json

# 版を並べる
python3 tools/compare.py out/cmp.png v3=characters/hd2d-warrior/sprite.json v4=characters/hd2d-warrior-v4/sprite.json
```

## ディレクトリ構成

| 場所 | 役割 |
|---|---|
| `tools/` | 描画器、検品、描き出し、比較 |
| `styles/` | 作風の決まり（数字と出典） |
| `characters/` | キャラクター。`parts.json` が元、`sprite.json` は書き出し（手打ちの v3 だけは `sprite.json` が元） |
| `docs/progress/` | 周ごとの比較画像と判定 |
| `docs/knowledge/` | 技術・問題・見た目の精度・設計判断の記録 |
| `docs/ROADMAP.md` | 道のり |

## 開発者向け

```bash
python3 -m unittest discover -s tests
```

## ライセンス

未定。
