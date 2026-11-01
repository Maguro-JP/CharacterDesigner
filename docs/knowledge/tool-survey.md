# 既製の画像生成・デザインの道具の調べ（2026-11-01）

chatdraw を良くするために、出来の良い既製品が何をどう作っているかを公式の文書と公開元で調べた。
出典は各行の URL と `docs/references.md` の「既製の道具の調べ」。公式の頁が取れず、第三者の解説だけで書いた行は「（第三者）」と付けている。

## ツールごとの要点

| ツール | 模型の管理 | おまかせ・つなぐ流れ | 既存の絵の編集 | 綺麗化 | 画面の作り | 出典 |
|---|---|---|---|---|---|---|
| ComfyUI | 本体は模型の部品（VAE、LoRA、ControlNet）を別々に読む。追加の部品の取得は ComfyUI-Manager | 節点（ノード）をつないだ流れ。前回から変わった節点だけを計算し直す。流れと種を PNG に埋め、絵を落とすと流れが戻る | inpaint、ControlNet、IP-Adapter は節点で組む | 拡大の節点。顔の自動の直しは拡張の Impact Pack の FaceDetailer（検出→SAM で切り分け→描き直し、何回も回せる） | 待ち行列（Ctrl+Enter）。すぐ動く見本の流れ（テンプレート）の一覧 | https://github.com/Comfy-Org/ComfyUI 、https://github.com/ltdrdata/ComfyUI-Impact-Pack |
| Fooocus | 既定・写実・アニメの組（プリセット）で模型と設定をまとめて切り替える | 頼みの言葉を手元の GPT-2 で書き足す（Fooocus V2 の作風）。refiner の切り替えを 1 つの標本化の中で行う | 独自の inpaint の模型、上下左右の outpaint、画像を頼みにする（Image Prompt）、使いやすくした ControlNet | Vary（Subtle／Strong）、Upscale（1.5 倍／2 倍） | 頼みの言葉と「生成」だけの最小の画面。細かい設定は Advanced に隠す。今は不具合の直しだけの保守 | https://github.com/lllyasviel/Fooocus |
| InvokeAI | Model Manager の画面で模型を入れる | 節点の流れ（Workflows）を画面で組む | Unified Canvas（KonvaJS の画布、レイヤー、元に戻す）で inpaint・outpaint | — | ボード付きの画廊。絵の付帯情報から頼みと設定を呼び戻す | https://github.com/invoke-ai/InvokeAI |
| Stable Diffusion WebUI Forge／A1111 | 模型の選び欄 | hires fix（小さく描いてから拡大して描き直す）。1.6.0 から 2 回目に別の模型を使える。ADetailer などの拡張 | inpaint、ControlNet、IP-Adapter、reference-only | Restore faces（CodeFormer など）。Forge は GPU の重みの割り当てを画面で選ぶ | Gradio の画面。Forge は試験の場の扱い | https://github.com/lllyasviel/stable-diffusion-webui-forge 、https://stable-diffusion-art.com/automatic1111/（第三者） |
| ADetailer（拡張） | 検出の模型を選ぶ（顔 face_yolov8n/s、手 hand_yolov8n、人 person_yolov8n/s-seg、MediaPipe の顔、自作の YOLO） | 描く→検出して覆いを作る→覆いの所だけ描き直す、を自動で行う。検出ごとに別の頼みの言葉 | 覆いの膨らませ・縮め、ずらし、上位 k 個だけ、面積の比で絞る。ControlNet を併用 | 顔・手の自動の直し。手は顔ほど効かない（第三者） | — | https://github.com/Bing-su/adetailer 、https://stable-diffusion-art.com/adetailer/（第三者） |
| Krita AI Diffusion | 自分の模型を足せる。作風の組（checkpoint、LoRA、標本化の方法）を作って保存 | 裏で ComfyUI を動かす | 選んだ所の生成の塗りつぶし・拡張・物の追加と削除。Regions（レイヤーで決めた所ごとに別の頼み）。制御のレイヤー（落書き、線画、輪郭、姿勢、奥行き、法線、領域分け）。IP-Adapter で作風と構図を写す | メモリを超えずに 4K・8K へ拡大 | 待ち行列と取り消し、履歴の欄で前の結果と頼みに戻る。Live painting（描くそばから即座に生成） | https://github.com/Acly/krita-ai-diffusion |
| SwarmUI | 模型に星を付けて上に並べる、名前の変更・削除の釦、削除を置き場に移す設定（第三者の写しの更新記録） | 裏は ComfyUI。生の流れの欄も出せる。Grid Generator（設定を並べて一度に比べる） | — | — | 初めての人向けの Generate の欄と、慣れた人向けの欄を分ける。公式の組（プリセット） | https://github.com/mcmonkeyprojects/SwarmUI 、https://newreleases.io/project/github/mcmonkeyprojects/SwarmUI/release/0.9.5-Beta（第三者） |
| NovelAI | 模型はサービスが選ぶ | Multi-Character Prompting（人物ごとに頼みを分ける）、知っている札の候補を出す | Inpaint、Vibe Transfer（参照の絵の作風・雰囲気）、Precise Reference（人物の参照）、Director Tools | Enhance、Upscale | 札の候補の表示 | https://docs.novelai.net/en/image/ |
| Midjourney | 模型の版を選ぶ | Style Reference と作風の番号、Moodboards | Omni Reference（人物・物を参照から持ち込む。1 枚だけ、GPU の時間は約 2 倍）、Vary Region（選んだ所を描き直す）、Pan、Zoom Out、Web の Editor | Upscale、Vary | Web の画面と Editor | https://docs.midjourney.com/hc/en-us/articles/36285124473997 、https://docs.midjourney.com/vary-region 、https://docs.midjourney.com/docs/style-reference |
| Leonardo.Ai | Elements（作風をそろえる部品）（第三者） | — | Canvas Editor（text to image、inpaint／outpaint、image to image、sketch to image、レイヤー）（第三者） | Universal Upscaler（Creativity Strength で足す細部の量を決める）、Alchemy Upscaler（拡大と同時に顔・手を直す） | — | https://intercom.help/leonardo-ai/en/articles/8756274-universal-upscaler 、https://intercom.help/leonardo-ai/en/articles/8952396-post-process-images-with-ai |
| Adobe Photoshop 生成塗りつぶし／Firefly | 模型の選び欄（Firefly と提携先の模型）。参照の絵が使えるかは模型によって変わる（利用者の掲示板） | — | 生成塗りつぶし、生成拡張、参照の絵。構図の参照は Firefly 側 | — | — | https://community.adobe.com/t5/photoshop-ecosystem-discussions/where-is-structure-reference-for-generive-ai-in-photoshop/m-p/15545359（利用者の掲示板。公式の helpx は取れなかった） |
| CLIP STUDIO PAINT | — | — | 自動彩色（線画の上に彩色のレイヤーを作る。ヒントの色・参照のレイヤーを使える。通信が要る）、ポーズスキャナー（写真から姿勢を推して 3D の人形に当てる） | スマートスムージング（拡大のぎざぎざを減らす、通信なし） | 画像生成のパレットは 2022 年に予告のあと見直し | https://tips.clip-studio.com/en-us/articles/2434 、https://celsys.com/en/topic/20190228 、https://www.clipstudio.net/ja/news/202211/29_01/ |
| Civitai の生成 | 公開の模型の一覧（評価、札、成人向けの印）。成人向けを ぼかす・隠す設定（第三者） | — | — | — | Buzz（通貨）で生成 | 公式の頁は取れなかった（第三者の解説だけ） |

## chatdraw に足りない物（効き目の大きい順）

chatdraw にある物は `chatdraw/` を言葉で探して確かめた（inpaint、拡大、ControlNet、IP-Adapter、レイヤー、ツアー、履歴、お気に入り、評価、管理画面はある）。
「無い」としたのは、`chatdraw/` の中で該当の語が見つからなかった物。`tools/gen/detail.py` など道具の側にある物を画面から呼べるかは確かめていない。

| 順 | 何を | どのツールが | どう実装しているか | 出典 |
|---|---|---|---|---|
| 1 | 描いたあとの顔・手の自動の検出と描き直しを、画面の 1 工程として回す | ADetailer、ComfyUI Impact Pack | YOLO で枠を出し、SAM で覆いを作り、覆いを少し膨らませて、その所だけ別の頼みと低めの強さで描き直す。何回も回せる | https://github.com/Bing-su/adetailer 、https://github.com/ltdrdata/ComfyUI-Impact-Pack |
| 2 | 所ごとに別の頼み（地域ごとの頼み、人物ごとの頼み） | Krita AI Diffusion（Regions）、NovelAI（Multi-Character）、InvokeAI | レイヤーや枠で所を決め、所ごとの言葉を注意の重みに分けて渡す | https://github.com/Acly/krita-ai-diffusion 、https://docs.novelai.net/en/image/ |
| 3 | 人物の参照（同じ人物を別の絵に持ち込む） | Midjourney Omni Reference、NovelAI Precise Reference | 参照の絵 1 枚と重みで人物の見た目を保つ | https://docs.midjourney.com/hc/en-us/articles/36285124473997 |
| 4 | 絵に頼み・種・設定を埋め、絵から設定を呼び戻す | ComfyUI、InvokeAI | PNG の付帯情報に流れと種を書く。絵を落とすと同じ設定に戻る | https://github.com/Comfy-Org/ComfyUI |
| 5 | 待ち行列と取り消し | ComfyUI、Krita AI Diffusion | 頼みを列に積み、走っている物を止められる。変わった所だけを計算し直す | https://github.com/Comfy-Org/ComfyUI |
| 6 | outpaint（絵の外へ広げる） | Fooocus、Krita AI Diffusion、Photoshop | 上下左右の向きを選び、広げた所を覆いにして描く | https://github.com/lllyasviel/Fooocus |
| 7 | 頼みの言葉の自動の書き足しと札の候補 | Fooocus（GPT-2 の書き足し）、NovelAI（札の候補） | 手元の小さな言語の模型で言葉を足す。模型が知っている札を入力の候補に出す | https://github.com/lllyasviel/Fooocus 、https://docs.novelai.net/en/image/ |
| 8 | 模型と設定をまとめた組（プリセット）で、初めての人に選ばせない | Fooocus、Krita AI Diffusion、SwarmUI | 既定・アニメなどの組に模型・LoRA・標本化の方法をまとめ、画面は言葉と生成の釦だけにする | https://github.com/lllyasviel/Fooocus |
| 9 | 2 段の描き（小さく描いてから拡大して描き直す。2 回目は別の模型も可） | A1111 hires fix、Fooocus refiner | 1 回目の潜在を拡大し、強さを下げて 2 回目を描く | https://stable-diffusion-art.com/automatic1111/（第三者） |
| 10 | 設定を並べて一度に比べる表 | SwarmUI Grid Generator | 模型・強さ・種を軸にして一覧の表を作る | https://github.com/mcmonkeyprojects/SwarmUI |

`chatdraw/twostage.py` があるので 9 は一部あるかもしれない。中身は確かめていない。

## 調べられなかった物

- Civitai の生成の画面（模型の非表示・止め方）の公式の文書。第三者の解説だけ
- Adobe の公式の helpx の頁（生成塗りつぶしの参照の絵）。利用者の掲示板だけ
- Leonardo.Ai の Elements と Canvas Editor の公式の頁。助けの頁は拡大だけ取れた
- InvokeAI の地域ごとの頼み（Regional Guidance）の公式の頁。公式の文書の場所が invoke.ai に移っていて取れていない
- SwarmUI の模型の一覧の画面の公式の文書（星などは第三者の更新記録の写し）
- NovelAI の各機能の詳しい頁（一覧の頁に名前だけ）
