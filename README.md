# CharacterDesigner

CharacterDesigner の製品は描画アプリ chatdraw（チャットで頼むと AI が描き、人が描き足せる Windows のデスクトップアプリ）です。
開発はすべて [chatdraw/](chatdraw/README.md) で行います。配る Setup.exe は `packaging/chatdraw/` と `.github/workflows/chatdraw-*.yml` で組みます。

キャラクターデザインを AI で描き、作画監督が数字で検品し、判定と指摘から学び続ける。
崩れ（正面に戻すと歪む顔、光より明るい影、指定と違う髪の色など）を人より細かく数字で見つけて、直すか戻す。頼みごとは日本語に限らない。English: [README.en.md](README.en.md)

`tools/` などに残っている道具は、アプリにまだ入れていない検品・学習・加工の部品です。アプリに入れるかは利用者が決めます（候補の一覧は [docs/reports/cleanup-20261031.md](docs/reports/cleanup-20261031.md)）。

## ディレクトリ

どこに何があるかの地図は [docs/STRUCTURE.md](docs/STRUCTURE.md)、絵の一覧（縮小画つき）は [library/INDEX.md](library/INDEX.md)。

## セットアップ

Windows（Setup.exe）: 入れ方・模型の取り方と手で置く方法・更新・削除・困ったときは [手順書](chatdraw/help/install.md)、使い方は [操作方法](chatdraw/help/manual.md) にあります。どちらもアプリの「ヘルプ」メニューから開けます。

動かせる模型と、それぞれの大きさ・得意なこと・商用の可否は [docs/models.md](docs/models.md) にまとめています。

## アプリに入れていない道具

次の道具はリポジトリに残し、試験で動くことを確かめています。アプリに入れるかは利用者の判断を待っています。

- 仕上げの補正（`tools/gen/retouch.py`）、線の清書（`tools/gen/inking.py`）、質感（`tools/gen/materials.py`）、空気感（`tools/gen/atmosphere.py`）
- 言葉の模型で頼みごとを描く言葉に直す（`tools/gen/free_text.py`、`tools/gen/local_llm.py`、取るのは `tools/llm/setup.sh`）
- Blender・MakeHuman の人形と下絵（`tools/engine/`）、ドット絵の道具（下の「ドット絵」）

![左が元の絵、中が水色の体を色で切り出して透明感を掛けた絵、右は後ろの格子で透け具合を見る図](docs/images/material-slime.jpg)

![左から元・透明感・金属感・重厚感・宝石感・無機質感・汚れ](docs/images/material-kinds.jpg)

![左から元・神々しい光・ほこりっぽい・木漏れ日・地下・宇宙・霞](docs/images/atmosphere-moods.jpg)

## 作画監督の数字の検品と学習

描いた絵の「当たり前」を数字で測り、基準から外れた所を挙げる（`tools/gen/measure.py`）。
- 顔の形: 目頭・目尻・目の上下・口の点に頭の型を当てはめ、正面に戻すと歪む量を測る（`tools/gen/faceform.py`）
- 影の順序: 光に背を向けた面の方が明るい部位を挙げる
- 背景と人物の光: 背景の光源が人物の後ろにあるのに、顔が正面から明るい（光が2つあるように見える）
- 髪: 白く飛んだ所と、指定の色（地の色とインナーカラーなど複数）から外れた所
- 左右の対: 左右の靴・腕の色の差（境は判定と指摘から学ぶ）
- 形と数: 両脚が 1 本に溶けた絵、1 人を頼んだのに 2 人の体が混ざった絵、1 つ頼んだ持ち物が 2 つ描かれた絵、頼んでいない服の柄・文字・上着（`tools/gen/qc.py`）
- 隠す構図: 見えない手足や目を、隠れて当たり前（構図の外・後ろ向き・物の陰）、見えないとおかしい（頼んだ動作に要る）、途中で無い、に分けて、後の 2 つだけを崩れにする（`tools/gen/occlusion.py`）
- 描き方の比べ: 同じ言葉と種の組（`casts/bench-stage1.json`）で描き直し、崩れの数を前後で比べる（`tools/gen/bench.py`）

基準（`styles/anime-norms.json`）は、答えの分かっている絵（3D の素体）で較正して決めた。描いた絵への判定と指摘を手本に足すと、
基準を学び直して利用者の基準（`config/norms.user.json`、git に入れない）に書く（`tools/gen/normlearn.py`）。
利用者の指摘は作画監督の判定の 3 倍の重みで数える。どの数字にも結びつかない指摘は、次に作る検品の候補として残る。
測るとき: `PYTHONPATH=.cache/gen/lib python3 tools/gen/measure.py 絵.png --hair "#1e1a24,#a8203c"`。

## 描く内容の制限とフィルター

このアプリは、描く内容を最初から規制しない。描きたくないものは、使う人が自分のフィルターで止める。
設定で外せない制限は1つだけで、子どもを性的に描くこと。詳しくは [docs/filters.md](docs/filters.md)。

| | 誰が決めるか | 中身 |
|---|---|---|
| 利用者のフィルター | 使う人 | 画面の「フィルター」の板で入れ切りと言葉の追加をする（保存先は `config/filters.json`。見本は `config/filters.example.json`）。用意した型（グロテスク・性的な表現・暴力・ホラー）は既定で全部切ってある。入れ切り、止める言葉の追加（どの言語でもよい）、新しいフィルターの追加ができる |
| 固定の制限 | アプリ | 子どもを性的に描くこと（loli・shota などの語、子どもを表す語と性的な語の組み合わせ）。子どものキャラクターも、大人の性的な表現や露出も、それだけでは止めない |

- 止めたときは、どのフィルターか固定の制限かを理由に書いて返す
- 言葉で見る仕組みなので、言い換えや綴りの崩しは拾えない。出来上がった絵の中身は、子どもを表す言葉のある頼みごとでだけ肌の割合を見る

## 設定

| 環境変数 | 用途 | 必須 |
|---|---|---|
| `CD_HOME` | 部品・模型・学んだ基準の置き場所（既定はリポジトリの `.cache`） | 任意 |
| `CD_DEVICE` | 描く場所（`cuda`・`mps`・`cpu`）。省くと NVIDIA の GPU → Apple の GPU → CPU の順に自動で選ぶ | 任意 |
| `CD_LLM_URL` / `CD_LLM_MODEL` | `tools/gen/free_text.py` が使う手元の言葉の模型の窓口（OpenAI 互換）と模型の名前 | 任意 |

## 作画監督の基準と記録

- 基準: `styles/anime-norms.json`（数字と、どの絵で較正したか）、`styles/face-template.json`（顔の形の型）
- 見落としの事例: `docs/knowledge/sakkan-cases.md`
- 描き方で分かったこと: `docs/knowledge/ai-drawing-notes.md`
- 外部の画像生成との週 1 の比べ: `docs/benchmarks/`
- 決めたことと理由: `docs/knowledge/decisions.md`、道のり: `docs/ROADMAP.md`

## ドット絵（後の加工の 1 つ）

出来たイラストや、部品で組んだキャラクターからドット絵を作る。作風の決まりは `styles/*.json` に数字で持つ。

```bash
# 部品（parts.json）からドット絵（sprite.json）を書き出す
python3 tools/build.py characters/warrior/parts.json --preview out/
# 作風の決まりで検品する（外れがあれば終了コード 1）
python3 tools/check.py characters/warrior/sprite.json styles/diorama.json
# 拡大図と舞台の図
python3 tools/render.py characters/warrior/sprite.json out/
# 版を並べる
python3 tools/compare.py out/cmp.png v3=characters/warrior-v3-hand/sprite.json v4=characters/warrior/sprite.json
```

## ディレクトリ構成

| 場所 | 役割 |
|---|---|
| `chatdraw/` | 製品のデスクトップアプリ（PySide6）。試験は `chatdraw/tests/` |
| `packaging/chatdraw/` | Setup.exe の組み方（Actions の `chatdraw-*.yml` が流す） |
| `tools/gen/` | 描く・直す・測る道具。`hands.py`・`tagger.py`・`cdhome.py` はアプリに同梱。`measure.py`（作画監督の数字）、`faceform.py`（顔の形）、`normlearn.py`（学習） |
| `tools/` | ドット絵の描画器と検品、比較、絵の目録 |
| `styles/` | 作風と作画監督の基準（数字と出典） |
| `characters/` | ドット絵のキャラクター（部品と書き出し） |
| `docs/` | 決めたこと、分かったこと、道のり、比べの記録 |
| `config/` | 利用者の設定の見本。利用者の設定そのものはリポジトリに入れない |

## 開発者向け

```bash
# 道具の試験
python3 -m unittest discover -s tests
# アプリの試験（PySide6 のある環境）
QT_QPA_PLATFORM=offscreen python3 -m unittest chatdraw.tests.test_chatdraw
```

## ライセンス

非公開（社内・個人用）。使える人を限り、ソースは公開しない。詳しくは [LICENSE](LICENSE)。配り方の計画は [docs/release-plan.md](docs/release-plan.md)。
