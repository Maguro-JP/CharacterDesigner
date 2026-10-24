# 画像生成の模型の調べ（2026-10-24 JST）

## 調べ方と、どこまで確かめたか

- 候補は、2026 年の比較記事と各社の発表を 6 回検索して集めました（出典は最後）
- ライセンスの表示、取るのに同意が要るか（gated）、取られた数は、Hugging Face の API で模型ごとに見ました。表の「ライセンス」「同意」の列はこの値です
- 手元の diffusers 0.42.0 に、その模型を読む部品（パイプライン）があるかを Python で確かめました。表の「diffusers」の列はこの結果です
- 世代の表の SD1.5・SDXL・FLUX.1・Lumina 2 の大きさは、各社が前から発表している値で、今回の検索では確かめ直していません
- 大きさと要る GPU のメモリは、記事の値です。記事どうしで食い違う所が多いので、目安として書いています
- どの模型も、まだ絵を描かせていません

前の版の表には誤りがありました。Anima を「約 2.9B」と書きましたが、模型の札と記事では 2B です。Illustrious XL v2.0 も「取るのに同意が要る様子」と書きましたが、API では同意は要りませんでした。

## 世代ごとの違い

| 世代 | 中身 | 言葉の読み方 | 手元の GPU | アニメ絵 | chatdraw の今の対応 |
|---|---|---|---|---|---|
| SD1.5 | 0.9B の U-Net | CLIP（短いタグ向き） | 4GB で動く | 古い派生が多い | 読める |
| SDXL | 2.6B の U-Net | CLIP 2 つ（タグ向き） | 8GB ほど | いちばん厚い。Illustrious、NoobAI、Animagine など | 読める（ラフの部品、範囲の直し、参考画像も使える） |
| FLUX.1 | 12B の DiT | T5（文で書ける） | 12〜24GB（量子化で下がる） | 素の物は写真寄り | 読めない |
| FLUX.2 | klein 4B / 9B、dev 32B | Qwen3 系 | klein 4B は約 13GB、dev は 80GB 超（記事の値） | 素の物は写真寄り | 読めない |
| Qwen-Image | 20B の DiT | Qwen2.5-VL（文と字が得意） | 量子化で 8〜11GB、そのままは 24GB 超 | 一般向け。字を描くのが得意 | 読めない |
| Z-Image | 6B の DiT | Qwen 系 | 6〜16GB（記事の値） | 写真と字が得意とされる | 読めない |
| Lumina 2 系 | 2.6B の DiT | Gemma | 8GB ほど（未確認） | Neta Lumina がアニメ向け | 読めない |
| Cosmos-Predict2 系 | 2B の DiT | Qwen3 0.6B | 7GB ほど（記事の値） | Anima がアニメ向け | 読めない |

SDXL のアニメの模型は「1girl, red hair」のようなタグで頼みます。FLUX、Qwen-Image、Z-Image、Lumina 2 は文で頼めます。chatdraw は言葉の模型（Qwen3.5）で日本語をタグに直しているので、文で頼む模型に替えるなら、直し方も変える必要があります。

## 模型の一覧

| 模型 | Hugging Face | 世代 | ライセンス（API の表示） | 商用 | 同意 | diffusers 0.42 | 取られた数 |
|---|---|---|---|---|---|---|---|
| Animagine XL 4.0 | cagliostrolab/animagine-xl-4.0 | SDXL | openrail++ | 可（条件付き） | 不要 | 読める | 56 万 |
| NoobAI-XL 1.1 | Laxhar/noobai-XL-1.1 | SDXL | fair-ai-public-license-1.0-sd | 札を読む必要あり | 不要 | 読める | 30 万 |
| NoobAI-XL V-pred 1.0 | Laxhar/noobai-XL-Vpred-1.0 | SDXL（v-prediction） | other | 札を読む必要あり | 不要 | 読める（描き方の設定を替える必要あり） | 4.5 万 |
| Illustrious XL v0.1 | OnomaAIResearch/Illustrious-xl-early-release-v0 | SDXL | other | 札を読む必要あり | 不要 | 読める | 11 万 |
| Illustrious XL v2.0 | OnomaAIResearch/Illustrious-XL-v2.0 | SDXL（1 ファイル） | creativeml-openrail-m | 可（条件付き） | 不要 | 1 ファイルから読む | 表示なし |
| WAI Illustrious v16 | Ine007/waiIllustriousSDXL_v160 | SDXL | 表示なし | 不明 | 不要 | 読める | 8 千 |
| Anima | circlestone-labs/Anima | Cosmos-Predict2 2B | circlestone-labs-non-commercial-license | 不可 | 不要 | 部品はある（Cosmos2TextToImagePipeline）。模型は 1 ファイルの形 | 153 万 |
| Neta Lumina | neta-art/Neta-Lumina | Lumina-Image-2.0 | apache-2.0 | 可 | 不要 | 部品はある（Lumina2Pipeline）。模型は 1 ファイルの形 | 7 千 |
| FLUX.1 schnell | black-forest-labs/FLUX.1-schnell | FLUX.1 | apache-2.0 | 可 | 要る | 読める | 52 万 |
| FLUX.1 dev | black-forest-labs/FLUX.1-dev | FLUX.1 | flux-1-dev-non-commercial-license | 不可 | 要る | 読める | 63 万 |
| FLUX.2 klein 4B | black-forest-labs/FLUX.2-klein-4B | FLUX.2 | apache-2.0 | 可 | 不要 | 読める | 44 万 |
| FLUX.2 klein 9B | black-forest-labs/FLUX.2-klein-9B | FLUX.2 | flux-non-commercial-license | 不可 | 要る | 読める | 19 万 |
| FLUX.2 dev | black-forest-labs/FLUX.2-dev | FLUX.2 | flux-non-commercial-license | 不可 | 要る | 読める | 32 万 |
| Qwen-Image | Qwen/Qwen-Image | Qwen-Image | apache-2.0 | 可 | 不要 | 読める | 30 万 |
| Qwen-Image-2512 | Qwen/Qwen-Image-2512 | Qwen-Image | apache-2.0 | 可 | 不要 | 読める | 5 万 |
| Z-Image Turbo | Tongyi-MAI/Z-Image-Turbo | Z-Image | apache-2.0 | 可 | 不要 | 読める | 68 万 |
| Chroma1-HD | lodestones/Chroma1-HD | FLUX.1 系 | apache-2.0 | 可 | 不要 | 読める | 6.6 万 |
| SD 3.5 Medium | stabilityai/stable-diffusion-3.5-medium | SD3 | stabilityai-ai-community | 年商の条件付き | 要る | 読める | 7 万 |

Qwen-Image 2.1 は、記事によると研究用のライセンス（商用不可）で、diffusers 0.41 以降の別の部品が要ります。API ではまだ見ていません。

## chatdraw の設計への意味

1. アニメのキャラクターデザインには、いまは SDXL の Illustrious 系・NoobAI 系・Animagine が向いています。ラフに沿わせる部品（T2I-Adapter）、範囲の直し（inpaint）、参考画像（IP-Adapter）が SDXL で揃っていて、chatdraw の機能がそのまま使えるためです
2. 新しい世代でアニメ向けなのは Anima（2B、商用不可）と Neta Lumina（Apache 2.0）です。どちらも軽く、diffusers に読む部品があります。ただし模型は 1 ファイルの形なので、diffusers の形に直して読めるかを確かめる必要があります。ラフの部品と範囲の直しは、この世代ではまだ揃っていない見込みです（未確認）
3. FLUX.2 klein 4B、Qwen-Image、Z-Image Turbo は商用でも使えますが、アニメ絵に強いとは書かれていません。文で頼めることと字を描けることが強みです。Qwen-Image は 20B と重く、CPU で描くのは現実的ではありません
4. 商用で使うかどうかで、選べる模型が変わります。模型を選ぶ画面に、商用の可否を出す必要があります
5. 世代を足すには、chatdraw の「sdxl / sd15」の 2 つだけの分け方を、世代ごとの部品の表（読む部品、描く大きさ、ラフの部品の有無、直しの有無）に直す必要があります

## 次に確かめること

1. SDXL の候補 4 つ（NoobAI 1.1、WAI v16、Illustrious v0.1、Hassaku v3.1）を model-verify で描かせ、絵を見て点を付けます
2. NoobAI、Illustrious、Anima のライセンスの本文を読み、商用の可否を確かめます
3. Anima と Neta Lumina を diffusers で読めるかを、1 つずつ Actions で試します

## 出典

- [QwenLM/Qwen-Image（GitHub）](https://github.com/QwenLM/Qwen-Image)
- [Qwen Image VRAM Requirements](https://willitrunai.com/image-models/qwen-image)
- [Qwen-Image-2.1-Turbo Isn't 7B](https://dev.to/alanwest/qwen-image-21-turbo-isnt-7b-the-vram-you-actually-need-to-run-it-locally-3ikp)
- [Qwen-Image-2.1: How to Run Locally（Unsloth）](https://unsloth.ai/docs/models/qwen-image-2.1)
- [FLUX.2 [klein]（Black Forest Labs）](https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence)
- [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
- [How to Run Flux 2 Locally](https://willitrunai.com/blog/how-to-run-flux-2-locally)
- [circlestone-labs/Anima の README](https://huggingface.co/circlestone-labs/Anima/blob/main/README.md)
- [Anima 2B anime model hands-on](https://lilting.ch/en/articles/anima-2b-anime-image-generation)
- [Tongyi-MAI/Z-Image-Turbo の README](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo/blob/main/README.md)
- [neta-art/Neta-Lumina の README](https://huggingface.co/neta-art/Neta-Lumina/blob/main/README.md)
- [Best Anime and Stylized Checkpoints for Local Image Generation (2026)](https://insiderllm.com/guides/best-anime-stylized-checkpoints-local-image-generation/)
- [Best Local Anime Image Model: Illustrious vs NoobAI](https://localaimaster.com/blog/best-local-anime-image-model)
