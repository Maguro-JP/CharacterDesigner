# LoRA と学習セット

アプリ（chatdraw）で LoRA を重ねる仕組みと、参考画像の組（学習セット）を作るときに調べたこと。
作りは `chatdraw/lora.py`、`chatdraw/loradialog.py`、`chatdraw/refs.py` の RefSets、試験は `chatdraw/tests/test_lora.py`。

## ComfyUI の LoraLoader の作り

- ノードの入力は MODEL・CLIP・lora_name（`models/loras` の中のファイル）・strength_model・strength_clip、出力は重ねた MODEL と CLIP
- 中では LoRA の重みを読み、模型の重みに「差分 × 強さ」を足す形の継ぎ当て（patch）を付けた写しを返す。元の模型は変えないので、
  ノードを繋ぎ替えるだけで外せる。いくつも重ねるときは LoraLoader を鎖のように繋ぐ
- UNet と言葉の部品（CLIP）で強さを分けられる。強さは負の値も 1 を超える値も受ける
- ファイルの置き場は `models/loras` の 1 か所で、下の階も一覧に出る

アプリで採った形: 置き場は共有の模型の置き場の `lora/` の 1 か所（下の階も見る）。重ねるのは diffusers の
`load_lora_weights(フォルダー, weight_name=, adapter_name=)` で名前を付けて読み、`set_adapters([名前…], adapter_weights=[強さ…])`
でまとめて効かせる（ComfyUI の鎖に当たる）。元の模型を変えずに `unload_lora_weights` で外せる。UNet と言葉の部品の強さは分けず、
強さは 0〜1.5 にした（1.5 を超えると崩れが増える LoRA が多いため。私の推測で、数で確かめてはいない）。

## Civitai の API で LoRA の情報を取る

- `GET https://civitai.com/api/v1/models/{モデル ID}`: `type`（LORA、LoCon など）、`name`、`modelVersions[]`（新しい順）
- `GET https://civitai.com/api/v1/model-versions/{版 ID}`: 1 つの版だけ
- 版の中身: `baseModel`（土台の模型。例 `SD 1.5`、`SDXL 1.0`、`Pony`、`Illustrious`、`Flux.1 D`）、
  `trainedWords`（きっかけの言葉）、`images[].url`（見本の画像）、`files[]`（`name`、`primary`、`downloadUrl`）
- ファイルは `https://civitai.com/api/download/models/{版 ID}`。年齢の確認の要る物などはトークン（`Authorization: Bearer`）が要る
- ページの URL は `https://civitai.com/models/{モデル ID}/<名前>?modelVersionId={版 ID}`

アプリで採った形: `baseModel` を系統に直し（Pony・Illustrious・NoobAI は SDXL の上に作られているので sdxl）、
`trainedWords` と見本の画像の URL を LoRA の隣の .json に残す。きっかけの言葉は描くとき頼みの前に足す。取ってくるだけで、何も上げない。

## 系統の見分け方

.json に系統が無い（手で置いた）LoRA は、.safetensors の頭の重みの名前だけを読んで見分ける。
`double_blocks`・`single_transformer_blocks` は FLUX、`lora_te2_`・`text_encoder_2.` は SDXL、diffusers の形の UNet だけの物は
「一番上の段（down_blocks.0）に注意があれば SD1.5、深い段に transformer_blocks が 2 つ以上あれば SDXL」で分ける。
合わない系統の LoRA は選べなくし、理由をツールチップに出す。分からない物は選べるようにし、読めなければ描くときに外す。

## 学習セット

模型ごと・キャラクターごとに参考画像の組を残す（絵は写さず道だけ）。描くときは組の絵を 1 枚に並べて IP-Adapter に渡す。
IP-Adapter の部品が無い世代（FLUX など）や部品を取れないときは、知らせて参考画像なしで描く。
手元で LoRA を学習させる所までは作らない。kohya の形（`<繰り返し>_<名前>/` に絵と同じ名前の .txt）で書き出し、外の道具に渡す。
