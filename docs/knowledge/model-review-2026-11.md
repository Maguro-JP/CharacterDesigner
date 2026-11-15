# 模型の見直し（2026-11-14）

言語の模型（チャットと訳、`chatdraw/models.py` の `WORDS`）と絵の模型（`chatdraw/catalog.json`）を、Hugging Face の API で 2026-11 までの物を調べた。
大きさは配布の重みの合計。足した模型は点を 0（確かめていない）にした。絵の模型は `config/verify-models.txt` に入れ、毎週の model-verify が描いて確かめる。
言語の模型は model-verify が扱わないので、点 0 のまま推奨にしない（`offered_words` は点の届いた物だけを出す）。

## Bonsai

PrismML（Hugging Face の `prism-ml`）の模型の名前。言語の模型と絵の模型の両方がある。

- 言語: Bonsai（1 ビット、2026-03）、Ternary Bonsai（3 値、2026-04〜07）、Ternary Bonsai 2（3 値、Qwen3.5 が元、2026-09、絵も読める）。GGUF の型のうち PTQ1_0 と PQ2_0 は PrismML の llama.cpp の fork だけが読む。Q2_0 は元の llama.cpp の b11556 以降で読める。
- 絵: Bonsai Image（FLUX.2 klein 4B が元、3 値と 2 値、2026-05）。軽い形（MLX、gemlite）は Mac と CUDA の専用の部品が要る。diffusers でそのまま読めるのは FP16 に広げた `-unpacked` の版で、軽さの利点は無い。

## 言語の模型

| 模型 | ファイル | 大きさ | ライセンス | CPU | GPU | llama.cpp で読めるか | 目録 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ternary Bonsai 2 2B | `prism-ml/Ternary-Bonsai-2-2B-gguf` の Q2_0 | 0.55GB | Apache-2.0 | 動く（配布元の説明） | CUDA・Metal | Q2_0 は b11556 以降 | 足した（点 0） |
| Ternary Bonsai 2 4B | `prism-ml/Ternary-Bonsai-2-4B-gguf` の Q2_0 | 1.21GB | Apache-2.0 | 動く（配布元の説明） | CUDA・Metal | Q2_0 は b11556 以降 | 足した（点 0） |
| Gemma 4 E2B | `unsloth/gemma-4-E2B-it-GGUF` の Q4_K_M | 3.11GB | Apache-2.0 | 動く | 動く | 読める | 足した（点 0） |
| Gemma 4 E4B | `unsloth/gemma-4-E4B-it-GGUF` の Q4_K_M | 4.98GB | Apache-2.0 | 動く | 動く | 読める | 足した（点 0）。Gemma 3 4B に置き換わった印（`replaced_by`）を付けた |
| Qwen3.6 / Qwen3.8 | 27B 以上と MoE だけ | 15GB 以上 | Apache-2.0 | 重い | 要る | 読める | 足さない（訳に使うには大きすぎる） |

アプリに入れる llama-cpp-python（`llama-cpp-python>=0.3.16` の CPU 版）が b11556 以降の llama.cpp を含むかは確かめていない。含まなければ Bonsai の Q2_0 は読めずに落ちる。

## 絵の模型（文から絵を描く模型、編集の模型）

| 模型 | 大きさ | ライセンス | 読む部品（diffusers） | GPU | 目録 |
| --- | --- | --- | --- | --- | --- |
| `prism-ml/bonsai-image-ternary-4B-unpacked` | 16.0GB | Apache-2.0 | Flux2KleinPipeline（世代 flux2） | 8GB 程度（私の推測、FLUX.2 klein 4B と同じ形） | 足した（点 0） |
| `prism-ml/bonsai-image-binary-4B-unpacked` | 16.0GB | Apache-2.0 | Flux2KleinPipeline（世代 flux2） | 同上 | 足した（点 0） |
| `Tongyi-MAI/Z-Image` | 20.5GB | Apache-2.0 | ZImagePipeline（世代 zimage） | 16GB 程度（私の推測） | 足した（点 0）。工程 50、CFG 4（配布元の例） |
| `Qwen/Qwen-Image-2.1`、`-Turbo` | 約 33GB | qwen-research（商用の条件あり） | QwenImage21Pipeline（diffusers 0.42 にある。目録に世代が無い） | 24GB 以上 | 足さない。世代を足すまで。Qwen-Image 2512 に印を付けた |
| `black-forest-labs/flux-3-image-klein` | 約 43GB | flux-kommunity-license、同意が要る | Flux3 の modular pipeline | 要る | 足さない（世代が目録に無い、30GB を超える） |
| `krea/Krea-2-Turbo` | 約 62GB | krea-2-community-license、同意が要る | 世代が目録に無い | 要る | 足さない |
| `MiniMaxAI/MiniMax-H3-Image` | 約 204GB | 独自のライセンス | MiniMaxH3ImagePipeline | 大きい GPU が要る | 足さない（大きすぎる） |
| `OpenMOSS-Team/MOSS-Image-Base` | 約 27GB | Apache-2.0 | MOSSImagePipeline（diffusers 0.42 に無い） | 要る | 足さない（読む部品が無い） |
| `circlestone-labs/Anima` | 1 ファイル | 札を確かめる | ComfyUI の 1 ファイルの形、diffusers の形が無い | — | 足さない |
| 編集: `Qwen/Qwen-Image-Edit-2511` | 約 58GB | Apache-2.0 | QwenImageEditPlusPipeline | 24GB 以上 | 足さない（目録は描く模型だけ。編集の入口は別） |
| 編集: `briaai/Fibo-2.0-edit-turbo`、`black-forest-labs/FLUX.2-klein-9B` | 25〜53GB | 独自・非商用 | — | 要る | 足さない |

CPU で描けるのは、どれも数分から数十分かかる大きさで、確かめていない。

## 古い版の印

消さずに、目録に `superseded_by` と「古い版」のタグを付けた（模型の削除は利用者が模型の管理で選んだときだけ）。

- Animagine XL 3.0・3.1 → Animagine XL 4.0
- Illustrious XL early release v0 → Illustrious XL 2.0
- NoobAI XL 1.0 → NoobAI XL 1.1
- FLUX.1 schnell → FLUX.2 klein 4B
- Qwen-Image 2512 → Qwen-Image 2.1（置き換える先は、まだ目録に無い）
- 言語の Gemma 3 4B → Gemma 4 E4B
