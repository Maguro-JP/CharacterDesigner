# 使えそうなイラストの模型（2026-10-24 JST に調べた）

調べ方: 2026 年の比較記事を 2 回検索して候補を集め、Hugging Face の API で 1 つずつ、形（diffusers のフォルダーか 1 つのファイルか）、ライセンスの表示、取られた数、最後の更新日を見ました。どの模型も、まだ絵を描かせてはいません（Actions の model-verify で確かめます）。

「アプリ」の列の意味は次のとおりです。

- そのまま: 今の chatdraw で取って使えます（diffusers の形の SDXL）
- 手で置く: 1 つのファイルだけなので、手で置く模型（0.2.6）として使えます。ただし本物のファイルで読み込めるかは、まだ確かめていません
- 対応が要る: SDXL ではない作りなので、今の chatdraw では読めません

## 候補

| 模型 | Hugging Face | 系統 | アプリ | ライセンスの表示 | 取られた数 | 更新 | 記事での扱い |
|---|---|---|---|---|---|---|---|
| Animagine XL 4.0 | cagliostrolab/animagine-xl-4.0 | SDXL | そのまま（今の既定） | openrail++（商用可） | 56 万 | 2025-02 | 定番の 1 つ |
| NoobAI-XL 1.1 | Laxhar/noobai-XL-1.1 | SDXL（Illustrious の派生） | そのまま | other（記事では商用不可） | 30 万 | 2025-09 | タグの効きがいちばん良いとされる |
| NoobAI-XL V-pred 1.0 | Laxhar/noobai-XL-Vpred-1.0 | SDXL（v-prediction） | 対応が要る（v-prediction の設定） | other | 4.5 万 | 2025-11 | 色と明暗が良いとされる。描き方の設定が違う |
| Illustrious XL v0.1 | OnomaAIResearch/Illustrious-xl-early-release-v0 | SDXL | そのまま | other | 11 万 | 2025-02 | Illustrious 系の元 |
| Illustrious XL v2.0 | OnomaAIResearch/Illustrious-XL-v2.0 | SDXL | 手で置く（1 ファイル。取るには同意が要る様子） | creativeml-openrail-m | 表示なし | 2025-04 | 公式の安定版。素の土台とされる |
| WAI Illustrious v16 | Ine007/waiIllustriousSDXL_v160 | SDXL（Illustrious の派生） | そのまま | 表示なし（要確認） | 8 千 | 2025-12 | 設定なしで扱いやすいとされる |
| Hassaku XL Illustrious v3.1 | John6666/hassaku-xl-illustrious-v31-sdxl | SDXL（Illustrious の派生） | そのまま | other | 3.4 万 | 2025-10 | 派生の人気どころ |
| Raehoshi illust XL 11 | Raelina/Raehoshi-illust-XL-11 | SDXL（Illustrious の派生） | そのまま | other | 5 千 | 2026-08 | 新しい派生 |
| Kohaku XL Zeta | KBlueLeaf/Kohaku-XL-Zeta | SDXL | そのまま | other | 6 千 | 2025-10 | 独自に学習した物 |
| AAM XL AnimeMix | Lykon/AAM_XL_AnimeMix | SDXL | そのまま | other | 5 千 | 2024-01 | 1 つの記事で最良とされる（ほかの記事と食い違う） |
| Pony Diffusion V6 XL | Runware/Pony_Diffusion_V6_XL | SDXL | そのまま（約 17GB と重い） | 表示なし（元はPony の独自ライセンス） | 6 千 | 2026-02 | 派生と LoRA が多い。決まり文句（score_9 など）が要る |
| Anima | circlestone-labs/Anima | 別の作り（約 2.9B） | 対応が要る | other | 153 万 | 2026-08 | いちばん新しく、新しいキャラクターに強いとされる。8GB に収まる軽い形もある |
| Chroma1-HD | lodestones/Chroma1-HD | 別の作り（Flux 系） | 対応が要る | apache-2.0（商用可） | 6.6 万 | 2025-10 | 味付けの無い土台。そのままではアニメ向きではない |

## 分かったこと

- 2026 年の記事の多くは、手元で描くなら SDXL の Illustrious 系か NoobAI 系がまだ強いと書いています。理由は、派生と追加の部品（LoRA）が多いことと、8GB ほどの GPU で動くことです
- chatdraw の一覧（catalog.json）には、上の SDXL のうち Illustrious XL v2.0 以外がすでに入っています。点が付いているのは Animagine XL 4.0 だけです
- 新しい作りの Anima はいちばん取られていますが、今の chatdraw（SDXL と SD1.5 だけ）では読めません

## 次に確かめること

1. NoobAI-XL 1.1、WAI Illustrious v16、Hassaku XL v3.1、Illustrious XL v0.1 を model-verify で描かせ、絵を見て点を付けます（config/verify-models.txt に入っています）
2. 商用で使うかどうかで選べる模型が変わるので、ライセンスを模型の札で読み直し、画面の札に出すかを決めます
3. Anima と NoobAI V-pred に対応するかを、diffusers の対応状況を調べてから決めます

## 出典

- [Best Anime and Stylized Checkpoints for Local Image Generation (2026)](https://insiderllm.com/guides/best-anime-stylized-checkpoints-local-image-generation/)
- [Best Local Anime Image Model: Illustrious vs NoobAI](https://localaimaster.com/blog/best-local-anime-image-model)
- [Best Anime Civitai Models 2026](https://offlinecreator.com/civitai-anime-models)
- [What Is Illustrious XL? Best Illustrious Model (2026)](https://kenerateai.com/blogs/what-is-illustrious-xl)
- [Best SDXL Models in 2026](https://www.promptzone.com/tara_suzuki/best-sdxl-models-in-2026-realistic-anime-and-all-purpose-checkpoints-116)
- 各模型の Hugging Face の札（上の表の名前）
