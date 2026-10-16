# 絵を描く模型の入れ替え

絵を描く模型（画像生成のモデル）は、作風ごとに選んで入れ替えられます。新しい模型が出たら、置いて切り替えるだけで使えます。

## 使える模型

いまの道具が描けるのは SDXL 系の模型です。

| 使える | 使えない |
|---|---|
| SDXL 系（Animagine XL、Illustrious XL、Pony Diffusion XL、DreamShaper XL など。名前に XL が付くものが多い） | SD1.5 系、SD3、Flux（描く仕組みが違う） |

置き方は次の 3 通りです。

| 形 | 見分け方 | 置く場所 |
|---|---|---|
| `.safetensors` のファイル 1 つ | 配布サイトでよく見る形。1 つ 約 7GB | `models/` に置く |
| diffusers 形式のフォルダー | 中に `model_index.json` がある | `models/` に置く |
| Hugging Face の名前（例 `cagliostrolab/animagine-xl-4.0`） | 置かずに名前で指定する | `config/models.json` に書く。初めて使うときだけ取る |

`.ckpt`・`.pt`・`.bin` は使いません。読むときに中のプログラムが動きうる形式で、危ないためです。同じ模型の `.safetensors` 版を探してください。

## 手順

1. 模型を `models/` に置きます（ファイルでもフォルダーでも）。
2. 使えるかを確かめます。SDXL 系か、壊れていないか、大きさを見ます。模型の本体は読まないので、すぐ終わります。

   ```
   python3 tools/gen/models.py check 置いた名前
   ```
3. 作風に割り当てます。

   ```
   python3 tools/gen/models.py use anime 置いた名前
   ```
4. 一覧で確かめます。

   ```
   python3 tools/gen/models.py list
   ```

作風の名前は自由に付けられます（`anime`、`real`、`chibi` など）。描くときに `CD_STYLE=real` のように作風を選ぶと、その作風の模型で描きます。何も付けなければ `anime` です。

一度だけ別の模型で描いてみたいときは、割り当てを変えずに `CD_DRAW_MODEL=名前` を付けて描きます。

## Hugging Face の名前で使うとき

模型は既定では外から取りに行きません（ディスクが一杯になった失敗があったため）。初めて使う模型は、`CD_FETCH=1` を付けて一度描くと取ります。取る前に `df -h` で空きを確かめてください。1 つ 約 7GB です。

## 決めておくこと

- `models/` と `config/models.json` は git に入れません（模型は大きく、割り当ては使う人ごとに違うため）。見本は `config/models.example.json` です。
- 新しい模型に替えるときは、今の模型と同じ言葉・同じ種で並べて描き、検品の点数（`qc.score`）で比べてから既定を替えます。
