# 絵の模型の剪定と自動の点（2026-11-15）

## 一覧に出す物

模型の管理と AI の欄の模型の選択（初回の設定も）に出すのは、推奨に届いた物（点が 60 以上）、手元にある物（「取得済み」）、利用者が足した物だけにした（`chatdraw/models.py` の `shown`）。
点の届かない物、確かめていない物（点 0）、目録から外した物は出さない。崩れた絵しか描けない模型を選ばせないため。
目録（`chatdraw/catalog.json`）から外した物は `retired` に理由を書いて残す。名前で引けるようにして、手元に取ってある物を正しい設定（工程、v-prediction など）で読むため。手元のファイルは消さない（模型の削除は利用者が模型の管理で選んだときだけ）。

## 剪定の前の点（2026-11-15）

点のある物は 3 つだけだった。

| 模型 | 点 | 扱い |
| --- | --- | --- |
| `cagliostrolab/animagine-xl-4.0` | 85 | 推奨（一覧に出す） |
| `Lykon/dreamshaper-xl-lightning` | 75 | 推奨（一覧に出す） |
| `Ine007/waiIllustriousSDXL_v160` | 50 | 推奨に届かない（左手が握りつぶれ、足の指がぼやけた）。一覧に出さない。新しい版 v17 を足した |
| ほかの 54 個 | 0 | 確かめていない。一覧に出さず、毎週の model-verify が点を付ける |

2026-11-14 の model-verify（実行 43614054800）は、11 個のうち描けたのが 4 個（prefect、nova v9、obsession、bonsai binary）で、点はまだ付けていない。
Illustrious XL 1.1・2.0 は、1 つのファイルの模型を置き場の名前（ファイル名の無い形）で渡していて読めなかった。Z-Image と bonsai ternary は Actions の機械（16GB）のメモリに入らず止まった。
noobai V-Pred 1.0、noobai 1.0、holodayo 2.1 は 330 分の枠を使い切って打ち切られた。

## 目録から外した物（24 個）

| 模型 | 理由 |
| --- | --- |
| Animagine XL 3.1 | 2026-11-07 の検証で落とした（人物が描けない、頼んだ服にならない）。新しい版 4.0 がある |
| Animagine XL 3.0 | 古い版。新しい版 4.0 がある |
| Illustrious XL early release v0 | 2026-11-07 の検証で落とした（背景と姿勢が描けない、指と足の指が崩れる） |
| NoobAI XL 1.1 | 2026-11-07 の検証で落とした（頭の無い 2 体目、腕が 3 本） |
| Hassaku XL Illustrious v3.1 | 2026-11-07 の検証で落とした（頭の無い 2 体目、全身で足が切れる） |
| AAM XL AnimeMix | 2026-11-07 の検証で落とした（上げた手が 2 つ重なる） |
| Kohaku XL Zeta | 2026-11-07 の検証で落とした（人の形にならない、顔と腕が崩れる） |
| Animagine XL 4.0（1 つのファイルの版） | 同じ重みが diffusers の形で目録にある |
| FLUX.1 schnell | 古い世代、33.7GB で確かめられない。後継 FLUX.2 klein 4B がある |
| Qwen-Image 2512 | 57.7GB で確かめられない。新しい版がある |
| SDXL base 1.0 | 2023 の土台。アニメ絵と手・指が弱い |
| Playground v2.5 | 写真寄りで目的に合わない |
| DreamShaper XL 1.0 | 古い版。DreamShaper XL Lightning（点 75）がある |
| SD1.5 系の 11 個 | 2022〜2023 の世代。学んだ大きさが 512 で手と指が崩れやすい |

## 足した物（点 0、毎週の model-verify が確かめる）

Hugging Face の API（diffusers の形、2026 に置かれた物）で選んだ。どれも SDXL 系なので、Actions の機械で描ける。

| 模型 | 置いた日 | ライセンス | VRAM・メモリ | 選んだ理由 |
| --- | --- | --- | --- | --- |
| `wssdaas/nova-anime-xl-ilv-19.0` | 2026-07 | 札に記載なし（元の Illustrious 系は faipl-1.0-sd、私の推測） | 6GB・16GB | 目録の Nova Anime XL v9 の新しい版。札の例は 25 工程、CFG 3.5 |
| `frankjoshua/waiIllustriousSDXL_v170` | 2026-06 | 札に記載なし（同上） | 6GB・16GB | v16（点 50）の新しい版 |
| `Raelina/Raehoshi-illust-XL-12` | 2026-10 | other | 6GB・16GB | 目録の 11 の新しい版 |
| `misri/oneObsession_v22` | 2026-06 | 札に記載なし | 6GB・16GB | Illustrious 系の新しい模型（fp16 の版を取る） |

足さなかった物: Anima（circlestone-labs、2026 のアニメの模型）は diffusers に読む部品が無く、独自の部品（AnimaTextToImagePipeline）が要る。元の版は非商用のライセンス。読む世代を足してから載せる。
FLUX.2 klein 9B、Qwen-Image 2.1 などの大きい物は 2026-11-14 の見直し（[model-review-2026-11.md](model-review-2026-11.md)）の通り。

## 点の付け方（自動）

`chatdraw/verify_models.py` と `.github/workflows/model-verify.yml`。毎週金曜 2:23（日本時間）と、手で起動したときに流れる。

1. 確かめる模型: 点が 0 の物と `config/verify-models.txt` に書いた物。外した物と、Actions の機械に入らない物（20GB を超える新しい世代）は除く
2. どの模型も、adherebench の頼み 30 本のうち決まった 5 本（0, 6, 12, 18, 24 番）を種 7 で描く（同じ頼み・同じ種で比べる）
3. 点 = 100 × 描けた語の割合 × 崩れの無い絵の割合。崩れは作画監督（handcheck）の外れ、人数の違い、真っ黒・一色の絵。描けなかった絵と検品できなかった絵も崩れとして数える
4. 描いた絵と数字は artifact（`verify-<模型>`、`model-scores`）に 30 日置く。点は `claude/MODELSCORE-<日付>` のブランチに積み、PR とマージは人が確かめてから行う

前の仕組みは、週 1 回の起動が無く（push だけで流れた）、新しい push で走っている検証が取り消され、読めなかった模型も「成功」で終わっていたので、点が 1 つも付かなかった。
