# CharacterDesigner

キャラクターデザインを AI で描き、作画監督が数字で検品し、判定と指摘から学び続ける道具。
「○○なキャラクターを作って」と頼むと、イラストのキャラクターデザインを描き、崩れ（正面に戻すと歪む顔、光より明るい影、指定と違う髪の色など）を
人より細かく数字で見つけて、直すか戻す。頼みごとは日本語に限らない。English: [README.en.md](README.en.md)

![スタジオの画面。左で頼み、中央で大きく見て、右で役割の進みと提案を見る](docs/images/app-studio.jpg)

## ディレクトリ

どこに何があるかの地図は [docs/STRUCTURE.md](docs/STRUCTURE.md)、絵の一覧（縮小画つき）は [library/INDEX.md](library/INDEX.md)。

## 主な機能

- 描く: 頼みごとからイラストのキャラクターデザインを描く（手元の画像生成。描く役は外部の画像生成にも差し替えられる）。1.5 倍の描き直し、顔と髪の描き直し、長辺 4096 画素への仕上げ（AI の拡大のあと 1024 画素の区切りごとに描き直して描き込みを足す。形が変わった区切りは使わない）
- 作画監督（検品）: 顔の形・影の順序・背景と人物の光・髪の色・左右の対を数字で測り、基準から外れた所を挙げる。基準は答えの分かっている絵で較正して決める
- 仕上げの補正: 写真の補正の技術（スポット修復・ノイズ除去・レベル補正・フリンジ除去・ジャギー消し・シャープなど）を、工程ごとに効き目と絵を壊していないかを測ってから掛ける（`tools/gen/retouch.py`）
- 学習: 描いた絵への判定と利用者の指摘から、作画監督の基準を学び直す。利用者ごとの基準に合わせられる
- 後の加工: 出来たイラストから、デフォルメ・ちびキャラ、ドット絵、3D、リアル風を作る（加工はオプション。デザインは常にイラストで決める）
- 描く板: 筆圧・レイヤー・線の清書・質感（透明感・金属感など）・空気感（神々しい光・木漏れ日など）。AI の補助は1つずつ入れ切りできる
- Claude から使う: MCP サーバーで、描く・検品する・学ぶ・仕上げるを Claude に頼める
- 描く内容は最初から規制しない。描きたくないものは利用者のフィルターで止める（固定の制限は子どもの性的な描写だけ。[docs/filters.md](docs/filters.md)）

## 動作環境

- Python 3.10 以上、Node.js 20.19 以上、curl
- ディスク 約 9GB（描く処理のモデル 約 7GB、言葉の模型 約 1.1GB、部品 約 1GB）。GPU（NVIDIA、Apple）があれば自動で使う。無くても CPU で動く（1 枚 約 5 分）

## セットアップ

Windows（Setup.exe）:

1. `CharacterDesigner-Setup.exe` を開いて入れる。利用者ごとの場所（`%LOCALAPPDATA%\Programs\CharacterDesigner`）に入るので、管理者の権限は要らない。Python と Node.js も要らない
2. デスクトップの CharacterDesigner を開く。初回は、その PC の GPU に合う描く部品（1〜3GB）と絵の模型（約 7GB）を取る（空きが 10GB より少なければ、取らずに理由を出す）
3. 準備ができると CharacterDesigner のウィンドウが開く（ブラウザーは使わない）

Setup.exe は Linux の上で `sh packaging/windows/build.sh` で組む（NSIS の makensis を使う。出来上がりは `dist/`）。

手元の clone から:

1. `sh app/start.sh` を流す（初回は部品とモデルの取得に 10〜20 分。2 回目からは数秒で起動する）
2. CharacterDesigner のウィンドウが開く。開発でサーバーだけ動かすときは `python3 app/launch.py --no-window`

## 使い方

自分の PC だけで動かす。外のサービスや API キーが無くても、頼みごとから絵まで手元で通る。
頼みごとの言語は問わない（言葉の模型が読む。模型も Claude も使えないときの予備の辞書は日本語の言葉だけを読む）。

1. 「自由に描く」に頼みごとを書いて「描く言葉に直す」→「描く」
   - 最初の1件はモデルの読み込みに数分。そのあとは1回 約 3〜5 分（CPU）
2. 描いた絵は作画監督の数字（下の「作画監督の数字の検品と学習」）で測り、良し悪しを判定すると学習の手本になる
3. 描き足すときは「描く」の板、後の加工（ドット絵など）は下の「ドット絵」

- スタジオ: 頼みごとを7つの役割（安全・読み手・演出・描き手・検品・意地の悪い目・整理）が順に回し、検品で落ちた絵は理由に合わせて直して描き直す。
  通った描く言葉は覚えて、似た頼みごとのときに読み手へ手本として添える。待機中は、通らなかった絵や見本の無い種を手がかりに提案を積む（描くかは自分で決める）。
  画面の配置は `.cache/app/layout.json`（仕切りを掴んで動かすと保存される。壊れていても既定で表示する）
- 自由に描く: 「赤いマフラーの騎士の少年、雪の城の前」「a knight boy with a red scarf」のように頼むと、手元の言葉の模型（ローカル LLM）が描く言葉（英語のタグ）に直す。
  描く言葉を見て直してから、形（縦長・横長・正方形）・枚数・seed を選んで描く。描いた絵は既定で 1.5 倍（1248x1824）に引き伸ばして弱く描き直し、線と細部をはっきりさせる（`tools/gen/hires.py`。CPU で1枚 約6分増える）。そのあと AI の拡大（Real-ESRGAN のアニメ絵用、`tools/gen/upscale.py`）で長い辺 4096 の 4K にする（約5分増える）。描く内容の制限は下の「描く内容の制限とフィルター」
- 描く: 描いた絵を下絵に敷き、レイヤーに手で描き足す。筆圧・パレット・スポイト・戻す/やり直す・レイヤー（塗りと線画を分ける）。
  AI の補助（手ぶれ補正・角を丸める・入り抜き・線の清書）は、1つずつ入れ切りと強さを変えられ、「補助を全部切る」で描いたとおりの線を残せる。
  「線を清書」は、重ねて描いたラフ線を1本の線にまとめて新しいレイヤーに置く（元のラフは隠すだけで消さない）。
  「切り出しと質感」で、下絵から人物・色で選んだ所・部位を「残り」と「切り出し」の2枚のレイヤーに分け、切り出した方に
  透明感（スライム）・金属感・重厚感・宝石感・無機質感・汚れを強さを決めて掛けられる。スライムの透けは、切り出したレイヤーの不透明度を下げるだけでもよい
  「空気感」で、絵全体に神々しい光・ほこりっぽさ・木漏れ日・地下・宇宙・霞を掛け、一番上の新しいレイヤーに置く（隠せば元に戻る）。
  空気感ごとに、描くときに足す言葉も出す。決まりは [docs/knowledge/atmosphere.md](docs/knowledge/atmosphere.md)
- 参考画像: CC ライセンスと public domain の画像（Openverse）を探して手元に置き、1枚を「描くときに使う」に選ぶと、
  スタジオと自由に描くの依頼に画風と色の手本として添える（強さは 0〜1）。作者・ライセンス・元のページを一緒に見せる。
  使う条件（作者の表示、非営利など）は元のページで確かめる。画像は `.cache/app/refs` に置き、リポジトリには入れない
- 亜人の設定資料: 「白い狐の巫女」のように頼むと、耳・尾・翼・角の付いた設定資料（4方向）を描いて検品し、通ったものを見本に保存する

![左が元の絵、中が水色の体を色で切り出して透明感を掛けた絵、右は後ろの格子で透け具合を見る図](docs/images/material-slime.jpg)

![左から元・透明感・金属感・重厚感・宝石感・無機質感・汚れ](docs/images/material-kinds.jpg)

![左から元・神々しい光・ほこりっぽい・木漏れ日・地下・宇宙・霞](docs/images/atmosphere-moods.jpg)

![言葉で頼むと種の設定が組まれ、3D の下絵で部品の付け根を見られる画面](docs/images/app-wish-to-case.png)

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
サーバーは `POST /api/measure`・`POST /api/feedback`・`POST /api/learn`、MCP は `measure`・`feedback`・`learn`。

## 描く内容の制限とフィルター

このアプリは、描く内容を最初から規制しない。描きたくないものは、使う人が自分のフィルターで止める。
設定で外せない制限は1つだけで、子どもを性的に描くこと。詳しくは [docs/filters.md](docs/filters.md)。

| | 誰が決めるか | 中身 |
|---|---|---|
| 利用者のフィルター | 使う人 | 画面の「フィルター」の板で入れ切りと言葉の追加をする（保存先は `config/filters.json`。見本は `config/filters.example.json`）。用意した型（グロテスク・性的な表現・暴力・ホラー）は既定で全部切ってある。入れ切り、止める言葉の追加（どの言語でもよい）、新しいフィルターの追加ができる |
| 固定の制限 | アプリ | 子どもを性的に描くこと（loli・shota などの語、子どもを表す語と性的な語の組み合わせ）。子どものキャラクターも、大人の性的な表現や露出も、それだけでは止めない |

- 止めたときは、どのフィルターか固定の制限かを理由に書いて返す
- 言葉で見る仕組みなので、言い換えや綴りの崩しは拾えない。出来上がった絵の中身は、子どもを表す言葉のある頼みごとでだけ肌の割合を見る

## Claude から使う（MCP）

アプリを起動したまま（`sh app/start.sh`）、MCP サーバーを登録すると、Claude に「白い狐の巫女を描いて」と頼めるようになる。
道具は `list_cases`（種の一覧）、`describe`（頼みごとを種の設定に組む）、`save_case`、`draw`（描く依頼）、`job`（進み具合）、`sheet`（通った絵）。
参考画像は `ref_search`（探す）、`ref_save`（手元に置く）、`ref_list`（一覧）。`studio_draw` の `ref` に置いた画像の id を渡すと、画風と色の手本にして描く。
スタジオは `studio_draw`（頼みごとか描く言葉で頼む）、`studio_job`（役割ごとの出来事と決着）、`studio_image`（絵）、`proposals`・`do_proposal`（待機中の提案と承認）。
自由に描くは `free_describe`（描く言葉に組む）、`free_draw`（`ref` と空気感 `mood` を指定できる）、`free_image`。
仕上げは `ink`（線の清書）、`material`（部位や色で切り出して質感: slime、metal、heavy、gem、inorganic、dirt）、`atmosphere_list`・`atmosphere`（空気感: 神々しい光、ほこり、木漏れ日、地下、宇宙、霞）。
フィルターは `filters_get`・`filters_set`。作画監督の検品と学習は `measure`・`feedback`・`learn`。全体の流れと各道具の引数は `guide` が返すので、Claude は最初にこれを呼ぶ。

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

## 設定

| 環境変数 | 用途 | 必須 |
|---|---|---|
| （画面） | 「自由に描く」の「言葉の模型 → 入れ替える」で窓口と模型を選ぶ。選んだものは `.cache/app/llm.json` に残り、下の環境変数より優先する。「既定に戻す」で消える | — |
| `CD_LLM_URL` | 手元の言葉の模型の窓口（OpenAI 互換。既定は同梱のもの `http://127.0.0.1:8081/v1`）。Ollama なら `http://127.0.0.1:11434/v1` | 任意 |
| `CD_LLM_MODEL` | 窓口で使う模型の名前（Ollama なら `qwen2.5:7b` など）。省略すると窓口の先頭の模型 | 任意 |
| `CD_LLM_SIZE` | 同梱の言葉の模型の大きさ。取った模型は消さずに並び、画面で選べる（`CD_LLM_DEFAULT=1` で取ったものを既定にする）。`small`（約 0.5GB、読み違いが多い）・既定（約 1.1GB）・`large`（約 2GB、読み違いが少ない） | 任意 |
| `CD_LLM_SKIP` / `CD_LLM_OFF` | `1` で、同梱の言葉の模型を取らない / 手元の模型を使わない | 任意 |
| `ANTHROPIC_API_KEY` | 手元の模型が無いとき、言葉の頼みごとを Claude で読む。どちらも無ければ辞書で読む | 任意 |
| `CD_DEVICE` | 描く場所（`cuda`・`mps`・`cpu`）。省くと NVIDIA の GPU → Apple の GPU → CPU の順に自動で選ぶ。指定した場所が無ければ CPU | 任意 |
| `CD_TORCH` | 部品を入れるときの torch の種類（`cuda`・`cpu`・`default`）。省くと NVIDIA の GPU がある Linux は CUDA 版、Mac は普通の版、それ以外は CPU 版 | 任意 |
| `CD_APP_DATA` | 描いた絵の置き場所（既定は `.cache/app/jobs`） | 任意 |
| `CD_HOME` | 部品・模型・学んだ基準の置き場所（既定はリポジトリの `.cache`） | 任意 |
| `PLAYWRIGHT_MODULE` / `CHROMIUM_PATH` | 下絵を撮るブラウザーを指す（無ければ `start.sh` が取る） | 任意 |

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
| `app/` | 手元のアプリ。`app/server` がサーバー（FastAPI）、`app/web` が画面（Vite + React）、`app/start.sh` が起動、`app/mcp` が Claude から使う MCP サーバー |
| `tools/gen/` | 描く・直す・測る道具。`measure.py`（作画監督の数字）、`faceform.py`（顔の形）、`normlearn.py`（学習）、`free_text.py`（描く）、`hires.py`・`detail.py`・`upscale.py`（描き直しと拡大） |
| `tools/` | ドット絵の描画器と検品、比較 |
| `styles/` | 作風と作画監督の基準（数字と出典） |
| `characters/` | ドット絵のキャラクター（部品と書き出し） |
| `docs/` | 決めたこと、分かったこと、道のり、比べの記録 |
| `config/` | 利用者の設定の見本（フィルター）。利用者の設定そのものは git に入れない |

## 開発者向け

```bash
python3 -m unittest discover -s tests
# 画像生成の部品がある環境（sh tools/gen/setup.sh のあと）
PYTHONPATH=.cache/gen/lib python3 -m pytest tests
# アプリのサーバーと MCP（start.sh を一度流したあと）
PYTHONPATH=.cache/app/lib python3 -m pytest app/server/tests app/mcp/tests
# アプリの画面（型チェック込み）
cd app/web && npm run build
```

## ライセンス

非公開（社内・個人用）。使える人を限り、ソースは公開しない。詳しくは [LICENSE](LICENSE)。配り方の計画は [docs/release-plan.md](docs/release-plan.md)。
