# 模型ごとの頼み方（札との照らし合わせ）

描くアプリ（chatdraw）の模型の一覧（`chatdraw/catalog.json`）と世代の表（`chatdraw/models.py` の `FAMILIES`）を、
各模型の札（Hugging Face のモデルカード）の使い方と 1 件ずつ照らした表。2026-11-01 に札を引いて照らした。

頼み方が札と違うと、模型は頼んだ物を描かないか、崩れた絵を出した。世代の決まり文句（タグの後ろの `masterpiece, best quality`、
24 工程、CFG 5）を全部の模型に当てていたので、札が別の質のタグ・工程・描き方を指定する模型ほど外れた。
直しは描く仕組み（`engine.prompt_args`、`use_scheduler`、`fit_tokens`）と目録の値に入れ、試験は `chatdraw/tests/test_perfamily.py`。

## 世代ごとの決まり

| 世代 | 頼みの形 | negative | 札との違いと直し |
|---|---|---|---|
| SDXL | タグ | 効く | CLIP は 75 語片より後ろを捨てる。頭の決まり文句と質のタグで頼みの後ろが切れ、頼んだ物が描かれなかった。収まらないときは質のタグ、頭の決まり文句の順に外して頼みを残す（`fit_tokens`） |
| SD1.5 | タグ | 効く | 同じく 75 語片。札の CLIP skip 2 は diffusers の `clip_skip=1`（diffusers の SD1.5 は既定で最後の層を使う） |
| FLUX.2 klein | 文 | 受けない | 札どおり（4 工程、guidance 1.0） |
| FLUX.1 schnell | 文 | 受けない | 札どおり（4 工程、guidance 0、max_sequence_length 256）。元の置き場は同意（gated）が要り、1 つのファイルの FLUX.1 を読むのに設定を借りる先もそこだったので、トークンの無い利用者は読めなかった。借り先を Apache-2.0 の写し（unsloth/FLUX.1-schnell）に替えた |
| Chroma | 文 | 効く | 札の negative に替えた |
| Z-Image | 文 | 受けない | 札どおり（9 工程、guidance 0） |
| Qwen-Image | 文 | 効く（true_cfg_scale） | 札の大きさは 1:1 で 1328×1328。1024 に縮めて描いていたので札の大きさに替えた。札の negative（中国語）を英語に直して持つ |
| Lumina 2（Neta Lumina） | タグと文 | 効く | 札の例は頭に「You are an assistant designed to generate anime images based on textual prompts. <Prompt Start>」を付ける。部品の既定の system_prompt は別の文なので、札の文を system_prompt で渡す。工程は札の 50 |
| SD3.5 | 文 | 効く | 目録に無い（手で置いた物だけ）。設定の借り先は同意が要る。写しを置いてよいライセンスではないので元のまま |

## 模型ごとに直した所

| 模型 | 札 | 直した所 |
|---|---|---|
| Animagine XL 4.0（フォルダーと 1 つのファイルの両方）、4.0 Zero | [札](https://huggingface.co/cagliostrolab/animagine-xl-4.0) | 質のタグを `masterpiece, high score, great score, absurdres`（札は後ろに置く）、negative を札の文、工程 28 |
| Animagine XL 3.1 | [札](https://huggingface.co/cagliostrolab/animagine-xl-3.1) | 頭に `masterpiece, best quality, very aesthetic, absurdres`、negative を札の文（A1111 の括弧は diffusers が読まないので外した）、工程 28、CFG 7 |
| Animagine XL 3.0 | [札](https://huggingface.co/cagliostrolab/animagine-xl-3.0) | 頭に `masterpiece, best quality`、negative を札の文、工程 28、CFG 7 |
| NoobAI XL 1.1 | [札](https://huggingface.co/Laxhar/noobai-XL-1.1) | 札の頭の決まり文句と negative が無かったので足した。工程 28、CFG 5.5 |
| NoobAI XL 1.0 | [札](https://huggingface.co/Laxhar/noobai-XL-1.0) | negative を札の文 |
| NoobAI XL V-Pred 1.0 | [札](https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0) | 札どおり（Euler の v_prediction、zero terminal SNR、rescale 0.7） |
| Illustrious XL early release | [札](https://huggingface.co/OnomaAIResearch/Illustrious-xl-early-release-v0) | negative を札の文、工程 28 |
| DreamShaper XL Lightning | [札](https://huggingface.co/Lykon/dreamshaper-xl-lightning) | 札の例は DPMSolverMultistep、4 工程、CFG 2。24 工程・CFG 5 で描いていた。描き方を読んだ後に替える（`use_scheduler`）。写真寄りなのでアニメの質のタグを足さない |
| Playground v2.5 | [札](https://huggingface.co/playgroundai/playground-v2.5-1024px-aesthetic) | 札の既定の描き方（EDM DPM++）の CFG は 3、工程 50 |
| Juggernaut XL v9 | [札](https://huggingface.co/RunDiffusion/Juggernaut-XL-v9) | 工程 35。札は重い negative を勧めないので質のタグを足さない |
| RealVisXL V5.0 | [札](https://huggingface.co/SG161222/RealVisXL_V5.0) | 工程 30。質のタグを足さない |
| SDXL base、DreamShaper XL、DreamShaper 8、Realistic Vision、SD1.5 | 各札 | 写真・汎用なのでアニメの質のタグを足さない。DreamShaper 8 は札の 25 工程 |
| Counterfeit V2.5 | [札](https://huggingface.co/gsdf/Counterfeit-V2.5) | 札の例は DPM++ 2M Karras、20 工程、CFG 10、negative に extra fingers, fewer fingers（EasyNegative は埋め込みなので持たない） |
| Anything V5 | [札](https://huggingface.co/genai-archive/anything-v5) | 札の Euler a、20 工程、CFG 7、CLIP skip 2 |
| Pony Diffusion V6 XL | [配布元の説明](https://civitai.com/models/257749) | 頭の score タグがあるので質のタグを足さない。CLIP skip 2 は SDXL の diffusers の既定と同じなので渡さない（渡すと 3 つ目の層になる） |
| Kohaku XL Zeta | [札](https://huggingface.co/KBlueLeaf/Kohaku-XL-Zeta) | CFG 3.5〜6.5 の中の 5 |
| Neta Lumina 1.0 | [札](https://huggingface.co/VirtualAddressExtension/Neta-Lumina-v1.0-diffusers) | system_prompt を札の文、工程 50 |
| Chroma1-HD | [札](https://huggingface.co/lodestones/Chroma1-HD) | negative を札の文 |
| Qwen-Image-2512 | [札](https://huggingface.co/Qwen/Qwen-Image-2512) | 大きさ 1328、negative を札の文の英訳 |
| FLUX.1 schnell | [札](https://huggingface.co/black-forest-labs/FLUX.1-schnell) | 設定の借り先を同意の要らない写しに |

札に頼み方の指定が無い模型（Illustrious 系の混ぜ物、Raehoshi、AnimeBoysXL、MeinaMix など）は世代の決まりのまま。
目録の模型はすべて、取る分のファイル（`FILES` の形）で部品がそろうことを Hugging Face の一覧で確かめた（欠けは無かった）。

## 確かめていないこと

直した頼み方で実際に描いた絵は見ていない（この環境に GPU が無い）。工程や CFG を札の値に替えた模型の点（score）は付け直していない。
