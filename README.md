# CharacterDesigner

「○○風のキャラクターデザイン」を、作風の決まりに落として描き、検品して出す道具。
最初の到達点は 箱庭ドット（高精細なドット絵を立体の背景に置く作風）。

![手打ちの v3 と部品組みの v4 の戦士](docs/progress/2026-09-29-warrior-v3-vs-v4.png)

## 主な機能

- 部品（楕円、多角形、太さのある線）と素材でキャラクターを組み、光を当てて高い解像度で描き、ドット絵に落とす
- 作風の決まり（`styles/*.json`）と突き合わせ、大きさ・頭身・色数・輪郭・孤立ドットを数える
- 検品用の拡大図と、箱庭ドット風の舞台に置いた図を描き出す
- 版どうしを1枚に並べた比較画像を作る

## 動作環境

- Python 3.11 以上
- Pillow

## セットアップ

1. `pip install pillow`

## 使い方

```bash
# parts.json からドット絵（sprite.json）を書き出す。--preview で縮小前の絵も出す
python3 tools/build.py characters/warrior/parts.json --preview out/

# 別の作風で描く（styles/retro16.json の render）。characters/<名前>/retro16/sprite.json に出る
python3 tools/build.py characters/warrior/parts.json --style retro16

# 作風の決まりで検品する（外れがあれば終了コード 1）
python3 tools/check.py characters/warrior/sprite.json styles/diorama.json

# 拡大図と舞台の図
python3 tools/render.py characters/warrior/sprite.json out/

# parts.json を読みやすい幅に整える（試験で整っているかを見る）
python3 tools/fmt.py characters/*/parts.json

# 動きのコマを GIF と並べ図にする（--anim は idle、walk、right-idle、right-walk）
python3 tools/anim.py out/idle.gif characters/warrior/sprite.json
python3 tools/anim.py --anim walk out/walk.gif characters/swordsman/sprite.json

# 設定資料の色指定（色見本、全コマ、作風の描き分けを1枚に）
python3 tools/sheet.py characters/cleric/parts.json docs/sheets/cleric.png

# 版を並べる
python3 tools/compare.py out/cmp.png v3=characters/warrior-v3-hand/sprite.json v4=characters/warrior/sprite.json
```

## 手元のアプリ（亜人の設定資料）

「白い狐の巫女」のように言葉で頼むと、耳・尾・翼・角の付いた設定資料（4方向）を描いて検品し、通ったものを見本に保存する。
自分の PC だけで動かす。

![言葉で頼むと種の設定が組まれ、3D の下絵で部品の付け根を見られる画面](docs/images/app-wish-to-case.png)

必要なもの: Python 3.10 以上、Node.js 20.19 以上、curl。ディスク 約 8GB（描く処理のモデル 約 7GB、部品 約 1GB）。GPU は無くても動く（CPU）。

1. `sh app/start.sh` を流す（初回は部品の取得に数分。2回目からは数秒で起動する）
2. 表示された `http://127.0.0.1:4173/` を開く
3. 「言葉で頼む」に頼みごとを書くか、種を選び、「描く」を押す
   - 最初の1件はモデルの取得と読み込みに 約 10〜20 分（回線による）。そのあとは1回 約 3 分（CPU）
   - 描き終わったら「回ごとの結果」で落ちた理由を見られる。目で見て良ければ「見本に保存」

| 環境変数 | 用途 | 必須 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 言葉の頼みごとを Claude で読む。無ければ辞書で読む | 任意 |
| `CD_APP_DATA` | 描いた絵の置き場所（既定は `.cache/app/jobs`） | 任意 |
| `PLAYWRIGHT_MODULE` / `CHROMIUM_PATH` | 下絵を撮るブラウザーを指す（無ければ `start.sh` が取る） | 任意 |

### Claude から使う（MCP）

アプリを起動したまま（`sh app/start.sh`）、MCP サーバーを登録すると、Claude に「白い狐の巫女を描いて」と頼めるようになる。
道具は `list_cases`（種の一覧）、`describe`（日本語を種の設定に組む）、`save_case`、`draw`（描く依頼）、`job`（進み具合）、`sheet`（通った絵）。

- Claude Code: リポジトリの場所で
  `claude mcp add characterdesigner -e PYTHONPATH=.cache/app/lib -- python3 -m app.mcp.server`
- Claude Desktop: 設定の `mcpServers` に次を足す（`/path/to/CharacterDesigner` は置いた場所に替える）
  ```json
  "characterdesigner": {
    "command": "python3",
    "args": ["-m", "app.mcp.server"],
    "cwd": "/path/to/CharacterDesigner",
    "env": {"PYTHONPATH": "/path/to/CharacterDesigner/.cache/app/lib"}
  }
  ```


## ディレクトリ構成

| 場所 | 役割 |
|---|---|
| `tools/` | 描画器、検品、描き出し、比較 |
| `styles/` | 作風の決まり（数字と出典） |
| `characters/` | キャラクター。`parts.json` が元、`sprite.json` は書き出し（手打ちの v3 だけは `sprite.json` が元） |
| `docs/progress/` | 周ごとの比較画像と判定 |
| `docs/sheets/` | キャラクターごとの設定資料（色指定） |
| `docs/knowledge/` | 技術・問題・見た目の精度・設計判断の記録 |
| `app/` | 手元のアプリ。`app/server` がサーバー（FastAPI）、`app/web` が画面（Vite + React）、`app/start.sh` が起動、`app/mcp` が Claude から使う MCP サーバー |
| `docs/ROADMAP.md` | 道のり |

## 開発者向け

```bash
python3 -m unittest discover -s tests
# アプリのサーバー（start.sh を一度流したあと）
PYTHONPATH=.cache/app/lib python3 -m pytest app/server/tests app/mcp/tests
# アプリの画面（型チェック込み）
cd app/web && npm run build
```

## ライセンス

未定。
