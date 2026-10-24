# CharacterDesigner（chatdraw）

チャットで頼むと AI が絵を描き、その絵に人が描き足せるデスクトップの描画アプリです。ラフを描いて渡すと、線の形に沿って AI が仕上げます。

![左にデッサンの道具、中央にキャンバス、右に AI の欄と履歴とレイヤーが並ぶ画面](../docs/images/chatdraw-main.jpg)

## 主な機能

- AI で描く: 右の AI の欄に描きたい絵を書いて「描く」を押します。日本語の頼みは、言葉の模型が絵の模型の分かる言葉に直します
- ラフから描く: キャンバスに線を描き、「ラフから」を選んで描くと、線の形に沿って描きます
- 描いている様子: 描いている途中の絵がキャンバスに出ます。工程と残り時間は右の履歴の欄に出ます
- 作画: レイヤー、ブラシ 6 種と筆圧、移動・選択・ぼかし・塗りつぶし・グラデーション・直線・四角・楕円・スポイトなど 14 の道具
- 絵の模型: 好みに合わせて選べます。動作を確かめた模型だけを出し、「AI」メニューでいつでも切り替えられます。「おまかせ」は頼みに合う模型を AI が選びます
- 模型の管理: 「AI」メニューの「模型の管理」で、手元の模型の一覧・削除・推奨の模型の取得・更新ができます
- 欄の配置: 欄は畳む・別ウィンドウにする・隠すができ、「ウィンドウ」メニューの「整列」で初めの配置に戻せます

## 動作環境

- Windows 10 / 11（64 ビット）
- ディスク: 絵の模型 1 つにつき 約 2〜7GB、言葉の模型 約 1.3GB、描く部品 約 1.3GB（NVIDIA の GPU がある機械では 約 4GB）
- GPU は無くても動きます（CPU で 1 枚 約 4〜10 分）

## 入れ方

1. `CharacterDesigner-Setup.exe` を開き、案内に沿って入れます（管理者の権限を求められます）
2. デスクトップかスタートメニューの CharacterDesigner を開きます
3. 初めての起動で、使う絵の模型を選んで「取って使う」を押します。描く部品と模型を自動で取ります

前の版（`%LOCALAPPDATA%\Programs\CharacterDesigner`）が入っていれば、入れるときに模型と描いた物を新しい置き場へ移し、前の版を消します。

## 更新と削除

- 更新: 新しい `CharacterDesigner-Setup.exe` をそのまま入れます。描いた絵・模型・設定は残ります
- 削除: Windows の「アプリ」から CharacterDesigner をアンインストールします。描いた絵と模型は残ります（模型はほかの自作アプリと共有しているため）

## 置き場

| 置き場 | 入っている物 |
|---|---|
| `C:\Program Files\CharacterDesigner` | アプリ本体 |
| `C:\ProgramData\CharacterDesigner` | 描く部品、記録 |
| `C:\LLM\gguf`、`C:\LLM\huggingface` | 模型（自作アプリで共有） |
| ピクチャ\CharacterDesigner | 描いた絵 |

## 設定

「設定」メニューの「設定…」で、描く工程の数・頼みの効き・ラフに沿う強さ・保存先を変えられます。

| 環境変数 | 用途 | 必須 |
|---|---|---|
| `LLM_HOME` | 模型の置き場を `C:\LLM` からほかへ移す | 任意 |
| `CD_HOME` | 部品と記録の置き場を移す | 任意 |

## ディレクトリ構成

| 場所 | 役割 |
|---|---|
| `app.py` | ウィンドウ、メニュー、欄の配置 |
| `canvas.py`、`brush.py`、`colorpanel.py`、`icons.py` | 作画 |
| `engine.py` | 絵の模型と言葉の模型で描く |
| `models.py`、`catalog.json` | 模型の一覧と、確かめた結果 |
| `setup.py`、`manager.py`、`choose.py` | 初回の設定、模型の管理、おまかせの選び方 |
| `paths.py`、`migrate.py` | 置き場と、前の版からの移行 |
| `activity.py` | 工程・進み・履歴の欄 |
| `tests/` | 試験 |

## 開発者向け

```sh
# 試験
PYTHONPATH=.cache/gen/lib QT_QPA_PLATFORM=offscreen python3 -m unittest chatdraw.tests.test_chatdraw

# Setup.exe を組む（Linux の上で。makensis が要る）
sh packaging/chatdraw/build.sh
```

## ライセンス

リポジトリの [LICENSE](../LICENSE) に従います。
