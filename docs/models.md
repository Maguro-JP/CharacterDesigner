# 絵を描く模型の入れ替え

絵を描く模型（画像生成のモデル）は、作風ごとに選んで入れ替えられます。新しい模型が出たら、置いて切り替えるだけで使えます。

## 使える模型

アプリが描ける世代と、名前で選べる模型は、この資料の末尾の「アプリで動かせる模型の一覧」にまとめています。
手で置く模型は SDXL 系と SD1.5 系が使えます（FLUX などの新しい世代は、一覧にある名前で選んでください）。

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

<!-- modeldoc:begin -->

## アプリで動かせる模型の一覧

この一覧は `python3 -m chatdraw.modeldoc` で目録（`chatdraw/catalog.json`、`chatdraw/models.py`）から作っています。
点は実際に描かせて確かめた結果で、0 はまだ確かめていない模型です。推奨として選べるのは点の付いた模型だけです。

### 絵を描く模型

| 模型 | Hugging Face の名前 | 世代 | 大きさ | 速さ（CPU で 1 枚） | 点 | 得意なこと | 商用 |
|---|---|---|---|---|---|---|---|
| NoobAI XL V-Pred 1.0 | `Laxhar/noobai-XL-Vpred-1.0` | SDXL | 7.1 GB | － | 0 | アニメ絵。頼んだ通りに描きやすく、手・足・顔の形が崩れにくい | 商用不可（fair-ai-public-license-1.0-sd に NoobAI の追加条項。描いた絵の商用利用も禁止） |
| Animagine XL 4.0 | `cagliostrolab/animagine-xl-4.0` | SDXL | 6.9 GB | － | 85 | アニメ絵。線と塗りが整っていて、キャラクターに強い | 条件付きで商用可（openrail++） |
| Animagine XL 3.1 | `cagliostrolab/animagine-xl-3.1` | SDXL | 6.9 GB | － | 0 | アニメ絵。4.0 より柔らかい塗り | 札を確かめる |
| Animagine XL 3.0 | `cagliostrolab/animagine-xl-3.0` | SDXL | 6.9 GB | － | 0 | アニメ絵。少し前の塗りの雰囲気 | 札を確かめる |
| Illustrious XL 0.1 | `OnomaAIResearch/Illustrious-xl-early-release-v0` | SDXL | 6.9 GB | － | 0 | アニメ絵。キャラクターや服の種類に詳しい | 札を確かめる |
| Illustrious XL 2.0 | `Jommarn/Illustrious-XL-v2.0` | SDXL | 6.9 GB | － | 0 | アニメ絵。Illustrious の新しい版で、細部が細かい | 札を確かめる |
| NoobAI XL 1.1 | `Laxhar/noobai-XL-1.1` | SDXL | 6.9 GB | － | 0 | アニメ絵。絵柄の幅が広く、作家風の指定が効く | ライセンスの本文を読む必要あり |
| Hassaku XL | `John6666/hassaku-xl-illustrious-v31-sdxl` | SDXL | 6.9 GB | － | 0 | アニメ絵。くっきりした線と明るい塗り | 札を確かめる |
| Prefect Illustrious XL | `John6666/prefect-illustrious-xl-v3-sdxl` | SDXL | 6.9 GB | － | 0 | アニメ絵。立体感のある塗り | 札を確かめる |
| WAI Illustrious | `Ine007/waiIllustriousSDXL_v160` | SDXL | 6.9 GB | － | 0 | アニメ絵。整った顔と鮮やかな色 | 札を確かめる |
| AAM XL AnimeMix | `Lykon/AAM_XL_AnimeMix` | SDXL | 6.9 GB | － | 0 | アニメ絵。背景まで描き込む | 札を確かめる |
| Kohaku XL Zeta | `KBlueLeaf/Kohaku-XL-Zeta` | SDXL | 6.9 GB | － | 0 | アニメ絵。イラスト集のような落ち着いた塗り | 札を確かめる |
| blue pencil XL | `GHArt/blue_pencil-XL_V1.0_xl_fp16` | SDXL | 6.9 GB | － | 0 | アニメ絵。淡い色と柔らかい線 | 札を確かめる |
| Raehoshi illust XL | `Raelina/Raehoshi-illust-XL-11` | SDXL | 6.9 GB | － | 0 | アニメ絵。光の表現が華やか | 札を確かめる |
| AnimeBoys XL | `Koolchh/AnimeBoysXL-v3.0` | SDXL | 6.9 GB | － | 0 | アニメ絵。男性キャラクターに強い | 札を確かめる |
| True Pencil XL | `John6666/true-pencil-xl-v100-sdxl` | SDXL | 6.9 GB | － | 0 | 鉛筆画や線画の風合い | 札を確かめる |
| Pony Diffusion V6 XL | `Runware/Pony_Diffusion_V6_XL` | SDXL | 17.6 GB | － | 0 | アニメ絵とカートゥーン。デフォルメに強い | 札を確かめる |
| DreamShaper XL Lightning | `Lykon/dreamshaper-xl-lightning` | SDXL | 6.9 GB | － | 75 | 速い。写実寄りからイラストまで幅広い | 札を確かめる |
| DreamShaper XL | `Lykon/dreamshaper-xl-1-0` | SDXL | 7.1 GB | － | 0 | 写実寄りからイラストまで幅広い | 札を確かめる |
| SDXL 1.0 | `stabilityai/stable-diffusion-xl-base-1.0` | SDXL | 6.9 GB | － | 0 | 元になった基本の模型。素直な絵 | 条件付きで商用可（openrail++） |
| RealVisXL 5.0 | `SG161222/RealVisXL_V5.0` | SDXL | 6.9 GB | － | 0 | 写真のような写実 | 札を確かめる |
| Juggernaut XL 9 | `RunDiffusion/Juggernaut-XL-v9` | SDXL | 6.9 GB | － | 0 | 写実。映画のような光 | 札を確かめる |
| Playground 2.5 | `playgroundai/playground-v2.5-1024px-aesthetic` | SDXL | 6.9 GB | － | 0 | 鮮やかで見栄えのする絵 | 札を確かめる |
| DreamShaper 8 | `Lykon/dreamshaper-8` | SD1.5 | 2.1 GB | － | 0 | 古い世代。軽くて速い。写実からイラストまで | 札を確かめる |
| Counterfeit 2.5 | `gsdf/Counterfeit-V2.5` | SD1.5 | 4.3 GB | － | 0 | 古い世代のアニメ絵。背景がきれい | 札を確かめる |
| Anything V5 | `genai-archive/anything-v5` | SD1.5 | 4.3 GB | － | 0 | 古い世代のアニメ絵の定番 | 札を確かめる |
| MeinaMix 11 | `digiplay/MeinaMix_v11` | SD1.5 | 2.1 GB | － | 0 | 古い世代のアニメ絵。かわいい顔 | 札を確かめる |
| ReV Animated | `stablediffusionapi/revanimated` | SD1.5 | 4.3 GB | － | 0 | 古い世代。絵本やゲームの絵のような 2.5D | 札を確かめる |
| AWPainting | `sam749/AWPainting-v1-2` | SD1.5 | 4.3 GB | － | 0 | 古い世代のアニメ絵。厚塗りの風合い | 札を確かめる |
| Dreamlike Anime | `dreamlike-art/dreamlike-anime-1.0` | SD1.5 | 2.1 GB | － | 0 | 古い世代のアニメ絵。幻想的な色 | 札を確かめる |
| GuoFeng 3 | `xiaolxl/GuoFeng3` | SD1.5 | 4.3 GB | － | 0 | 古い世代。中華風の厚塗り | 札を確かめる |
| ToonYou | `frankjoshua/toonyou_beta6` | SD1.5 | 4.3 GB | － | 0 | 古い世代。カートゥーンの絵 | 札を確かめる |
| Realistic Vision 5.1 | `SG161222/Realistic_Vision_V5.1_noVAE` | SD1.5 | 4.3 GB | － | 0 | 古い世代の写実 | 札を確かめる |
| SD 1.5 | `stable-diffusion-v1-5/stable-diffusion-v1-5` | SD1.5 | 2.1 GB | － | 0 | 古い世代の基本の模型 | 札を確かめる |
| FLUX.2 klein 4B | `black-forest-labs/FLUX.2-klein-4B` | FLUX.2 | 16 GB | － | 0 | 文で頼める新しい世代。4 工程で速い。写真も絵も描く | 商用可（Apache-2.0） |
| Z-Image Turbo | `Tongyi-MAI/Z-Image-Turbo` | Z-Image | 32.8 GB | － | 0 | 文で頼める。8 工程で速い。写真と字が得意 | 商用可（Apache-2.0） |
| Qwen-Image 2512 | `Qwen/Qwen-Image-2512` | Qwen-Image | 57.7 GB | － | 0 | 文で頼める大きな模型。字と細かい指示に強い。GPU が大きくないと重い | 商用可（Apache-2.0） |
| Neta Lumina 1.0 | `VirtualAddressExtension/Neta-Lumina-v1.0-diffusers` | Lumina 2 | 21.2 GB | － | 0 | 新しい世代のアニメ向け。タグと文の両方で頼める | 商用可（Apache-2.0） |
| Chroma1-HD | `lodestones/Chroma1-HD` | Chroma | 27.5 GB | － | 0 | FLUX 系の土台の模型。味付けが無く、何でも描く | 商用可（Apache-2.0） |
| FLUX.1 schnell | `black-forest-labs/FLUX.1-schnell` | FLUX.1 | 33.7 GB | － | 0 | 文で頼める。4 工程で速い。取るには Hugging Face での同意が要る | 商用可（Apache-2.0） |

### 世代ごとにできること

| 世代 | 頼み方 | ラフから描く | 範囲の直し | 参考画像 |
|---|---|---|---|---|
| SDXL | タグ | ○ | ○ | ○ |
| SD1.5 | タグ | ○ | ○ | ○ |
| FLUX.2 | 文 | ○ | － | ○ |
| FLUX.1 | 文 | － | － | － |
| Chroma | 文 | － | － | － |
| Z-Image | 文 | － | － | － |
| Qwen-Image | 文 | － | － | － |
| Lumina 2 | タグ | － | － | － |

### 頼みを描く言葉に直す模型（言葉の模型）

| 模型 | ファイル | 大きさ | 点 | 得意なこと |
|---|---|---|---|---|
| Qwen3.5 2B | `unsloth/Qwen3.5-2B-GGUF` の `Qwen3.5-2B-Q4_K_M.gguf` | 1.3 GB | 100 | 速さと正確さの釣り合いが良い。細かい指定も落とさない |
| Qwen3.5 4B | `unsloth/Qwen3.5-4B-GGUF` の `Qwen3.5-4B-Q4_K_M.gguf` | 2.7 GB | 0 | 長い頼みをさらに正確に直す。少し遅い |
| Qwen3.5 0.8B | `unsloth/Qwen3.5-0.8B-GGUF` の `Qwen3.5-0.8B-Q4_K_M.gguf` | 0.5 GB | 20 | 最も軽い。短い頼み向き |

<!-- modeldoc:end -->
