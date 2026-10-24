# 手元の画像生成: 世の中の道具とコードの調べ（2026-10-24 JST）

chatdraw の描く仕組みを、すでに公開されている道具とコードに合わせて作り直すための調べです。

## 調べ方

- 公式の文書: diffusers の「Reduce memory usage」（Context7 で取得）、stable-diffusion.cpp の README（GitHub から本文を取得）、AMD の PyTorch for Windows の発表、InvokeAI の FP8 の文書
- 公開されているコード: ComfyUI の `comfy/model_management.py` を取得して、機械ごとの切り替えと数値の型の選び方を読みました
- ライセンス: 各リポジトリの LICENSE の 1 行目を取得しました
- 手元の測り: SDXL の U-Net を 1 工程動かし、bf16 と fp32 の速さを比べました（結果は下の「測った結果」）

## 既存の道具

| 道具 | 中身 | ライセンス | chatdraw との関係 |
|---|---|---|---|
| diffusers | Hugging Face の Python の部品 | Apache-2.0 | いま使っている。コードを使ってよい |
| ComfyUI | ノードで組む道具。機械ごとの切り替えが細かい | GPL-3.0 | 考え方だけを借りる（chatdraw は非公開のライセンスなので、コードは写さない） |
| Forge | A1111 の作り直し。メモリの使い方が良いとされる | AGPL-3.0 | 考え方だけ |
| A1111（stable-diffusion-webui） | 古くからの定番 | AGPL-3.0 | 模型の置き場の形（`models/Stable-diffusion` など）だけ合わせる |
| Fooocus | 設定の少ない SDXL の道具 | GPL-3.0 | 考え方だけ。2026 年は更新が止まっているとの記事あり |
| InvokeAI | 画面つきの道具 | Apache-2.0 | コードを使ってよい（FP8 で重みを置く仕組みがある） |
| SD.Next | 多機能の道具 | Apache-2.0 | コードを使ってよい |
| stable-diffusion.cpp | C/C++ だけで動く。GGUF の量子化 | MIT | コードも部品も使ってよい。Python から呼ぶ部品（stable-diffusion-cpp-python、MIT）もある |

## 分かったこと

### 1. CPU で描くときの数値の型

ComfyUI は、CPU では fp16 も bf16 も使わず fp32 で描きます。コードには「bf16 works on CPU but is extremely slow」と書かれています（`should_use_bf16` の中の注記）。

chatdraw は、メモリを減らすために CPU でも bf16 で読んでいます（`engine.py` の `load`）。bf16 の計算の命令（AVX512_BF16 や AMX）が無い CPU では、とても遅くなるおそれがあります。家庭用の Intel の CPU の多くには、この命令がありません。

### 2. GPU のメモリが少ない機械

diffusers の公式の方法は 4 段あります。

| 方法 | 効き | 速さ |
|---|---|---|
| `enable_model_cpu_offload()` | 模型の部品（言葉・U-Net・VAE）を、使う間だけ GPU に載せる | 少し遅い |
| `enable_sequential_cpu_offload()` | 部品の中の層ごとに載せ替える。いちばん減る | とても遅い |
| グループごとの退避（`enable_group_offload`） | 層のまとまりごとに載せ替える | 上の 2 つの間 |
| 層ごとの型の切り替え（`enable_layerwise_casting`） | 重みを fp8 で置き、計算のときだけ bf16 に戻す | ほぼ同じ |

VAE の分割（`vae.enable_tiling()`、`enable_slicing()`）で、絵を作る最後の段のメモリも減らせます。ComfyUI は GPU のメモリの量で「とても少ない・少ない・ふつう・多い」の 4 段に分け、自動で切り替えています。chatdraw はどれも使っていません。

### 3. NVIDIA 以外の GPU

- AMD: AMD が Windows 用の PyTorch（ROCm）を出しています。2026-01 の 7.2 では、Radeon RX 9000 と 7000 の一部、Ryzen AI の一部が対象です。RX 6000 は対象外です
- DirectML: ComfyUI のコードに「barely works, is very slow」と警告があります。使わない方が良さそうです
- Intel: PyTorch の XPU で動くと ComfyUI のコードにありますが、Windows で diffusers と組めるかは調べていません
- stable-diffusion.cpp は Vulkan で動くので、NVIDIA・AMD・Intel の GPU を 1 つの作りで扱えます

### 4. 模型の置き場

ComfyUI と A1111 は、`checkpoints`（A1111 は `Stable-diffusion`）、`loras`、`vae`、`controlnet`、`upscale_models` のように種類ごとのフォルダーを持ちます。ComfyUI は `extra_model_paths.yaml` で A1111 の置き場を読めます。chatdraw は手で置く模型を `manual` 1 か所にしているので、ほかの道具の置き場を読めるようにすると、同じ模型を 2 回置かずに済みます。

### 5. stable-diffusion.cpp の対応

README によると、SD1.x・SDXL・SD3.5・FLUX.1・FLUX.2・Qwen Image・Z-Image・Chroma・Anima など、多くの世代に対応しています。LoRA、IP-Adapter（SD1.5 と SDXL）、TAESD、VAE の分割、ESRGAN の拡大もあります。ControlNet は SD1.5 だけです。GGUF の量子化で、CPU や小さい GPU でも動かしやすくなります。

## 頼みを読む部品（言葉の模型）

新しい世代の多くは、頼みを読む所に、チャットに使う言葉の模型と同じ作りの物を使っています。各模型の `text_encoder/config.json` で確かめました。

| 模型 | 頼みを読む部品 |
|---|---|
| SDXL（stable-diffusion-xl-base-1.0） | CLIPTextModel（12 層。画像と言葉を結びつけるための小さな部品） |
| FLUX.2 klein 4B | Qwen3ForCausalLM（36 層） |
| Z-Image Turbo | Qwen3ForCausalLM（36 層） |
| Qwen-Image 2512 | Qwen2_5_VLForConditionalGeneration（28 層。画像も読める作り） |
| Neta Lumina 1.0 | Gemma2Model（26 層） |

言葉の模型は、頼みの文を読んで意味の数字に直す所だけに使い、返事の文は作りません。絵を描くのは別の部品（transformer）です。

## 小さな試験用の模型で描かせた結果

Hugging Face の試験用の小さな模型で、chatdraw の描く仕組み（Painter.paint）を通しました。絵の出来ではなく、読み込みと描く流れが通るかだけを見ています。

| 世代 | 試験用の模型 | 結果 |
|---|---|---|
| Z-Image | tiny-random/z-image | 通った（ZImagePipeline、工程の知らせ 2/2） |
| Qwen-Image | tiny-random/Qwen-Image | 通った（QwenImagePipeline、工程の知らせ 2/2） |
| FLUX.1 | katuni4ka/tiny-random-flux | 通った（FluxPipeline、工程の知らせ 2/2） |
| Chroma | charchits7/tiny-chroma-pipe | 落ちた（メモリを 135GB 求めた。試験用の模型の作りのせいか、chatdraw の渡し方のせいかは、まだ切り分けていません） |
| FLUX.2 | tiny-random/flux2 | 落ちた（FLUX.2 dev の形の試験用の模型で、klein の部品では読めなかった。klein の試験用の模型はまだ見つけていません） |
| Lumina 2 | なし | 試していません |

どの世代も、ラフから描く頼みには「ラフから描く部品がまだありません」と返しました。

## 測った結果

（測り終わったら書きます）

## chatdraw の設計の直し（案）

| 順 | 直すこと | 元にする物 |
|---|---|---|
| 1 | CPU の数値の型を、命令の有無で選ぶ（bf16 の命令が無ければ fp32） | ComfyUI の考え方と、測った結果 |
| 2 | GPU のメモリの量で、退避と VAE の分割を自動で選ぶ | diffusers の公式の方法、ComfyUI の 4 段の考え方 |
| 3 | AMD は ROCm の PyTorch を入れる。DirectML は使わない | AMD の発表、ComfyUI の警告 |
| 4 | ComfyUI と A1111 の模型の置き場を読む | 両方の置き場の決まり |
| 5 | 新しい世代（Anima、FLUX.2 klein、Z-Image）と GGUF は、stable-diffusion.cpp で動かすかを試す | stable-diffusion.cpp（MIT） |

## 出典

- [diffusers: Reduce memory usage](https://github.com/huggingface/diffusers/blob/main/docs/source/en/optimization/memory.md)
- [ComfyUI comfy/model_management.py](https://github.com/comfyanonymous/ComfyUI/blob/master/comfy/model_management.py)
- [stable-diffusion.cpp README](https://github.com/leejet/stable-diffusion.cpp/blob/master/README.md)
- [stable-diffusion-cpp-python（PyPI）](https://pypi.org/project/stable-diffusion-cpp-python)
- [AMD: PyTorch on Windows 7.2 release notes](https://www.amd.com/en/resources/support-articles/release-notes/RN-AMDGPU-WINDOWS-PYTORCH-7-2.html)
- [AMD: The Road to ROCm on Radeon for Windows and Linux](https://www.amd.com/en/blogs/2025/the-road-to-rocm-on-radeon-for-windows-and-linux.html)
- [InvokeAI: FP8 Storage](https://invoke.ai/configuration/fp8-storage/)
- [ComfyUI: model paths](https://www.mintlify.com/Comfy-Org/ComfyUI/configuration/model-paths)
- [How to Share Models Between ComfyUI and A1111](https://comfyui-wiki.com/en/tutorial/basic/link-models-between-comfyui-and-a1111)
- [Fooocus in 2026](https://localaimaster.com/blog/fooocus-guide)
