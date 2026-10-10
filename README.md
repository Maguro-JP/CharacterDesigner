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

## 手元のアプリ

自分の PC だけで動かす。外のサービスや API キーが無くても、日本語の頼みごとから絵まで手元で通る。

![日本語の頼みごとを手元の模型が描く言葉に直し、騎士の少年の絵が出た画面](docs/images/app-free-draw.jpg)

- 自由に描く: 「赤いマフラーの騎士の少年、雪の城の前」のように頼むと、手元の言葉の模型（ローカル LLM）が描く言葉（英語のタグ）に直す。
  描く言葉を見て直してから、形（縦長・横長・正方形）・枚数・seed を選んで描く。肌を見せる絵・性的な絵は描かない
- 亜人の設定資料: 「白い狐の巫女」のように頼むと、耳・尾・翼・角の付いた設定資料（4方向）を描いて検品し、通ったものを見本に保存する

![言葉で頼むと種の設定が組まれ、3D の下絵で部品の付け根を見られる画面](docs/images/app-wish-to-case.png)

必要なもの: Python 3.10 以上、Node.js 20.19 以上、curl。ディスク 約 9GB（描く処理のモデル 約 7GB、言葉の模型 約 1.1GB、部品 約 1GB）。GPU は無くても動く（CPU）。

1. `sh app/start.sh` を流す（初回は部品の取得に数分。2回目からは数秒で起動する）
2. 表示された `http://127.0.0.1:4173/` を開く
3. 「自由に描く」に頼みごとを書いて「描く言葉に直す」→「描く」。亜人の設定資料は、その下の欄で頼むか種を選んで「描く」
   - 最初の1件はモデルの取得と読み込みに 約 10〜20 分（回線による）。そのあとは1回 約 3 分（CPU）
   - 描き終わったら「回ごとの結果」で落ちた理由を見られる。目で見て良ければ「見本に保存」

| 環境変数 | 用途 | 必須 |
|---|---|---|
| （画面） | 「自由に描く」の「言葉の模型 → 入れ替える」で窓口と模型を選ぶ。選んだものは `.cache/app/llm.json` に残り、下の環境変数より優先する。「既定に戻す」で消える | — |
| `CD_LLM_URL` | 手元の言葉の模型の窓口（OpenAI 互換。既定は同梱のもの `http://127.0.0.1:8081/v1`）。Ollama なら `http://127.0.0.1:11434/v1` | 任意 |
| `CD_LLM_MODEL` | 窓口で使う模型の名前（Ollama なら `qwen2.5:7b` など）。省略すると窓口の先頭の模型 | 任意 |
| `CD_LLM_SIZE` | 同梱の言葉の模型の大きさ。取った模型は消さずに並び、画面で選べる（`CD_LLM_DEFAULT=1` で取ったものを既定にする）。`small`（約 0.5GB、読み違いが多い）・既定（約 1.1GB）・`large`（約 2GB、読み違いが少ない） | 任意 |
| `CD_LLM_SKIP` / `CD_LLM_OFF` | `1` で、同梱の言葉の模型を取らない / 手元の模型を使わない | 任意 |
| `ANTHROPIC_API_KEY` | 手元の模型が無いとき、言葉の頼みごとを Claude で読む。どちらも無ければ辞書で読む | 任意 |
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
