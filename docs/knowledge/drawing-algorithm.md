# 崩れずに、Animagine 以上の質で描く描き方（設計）

## 分かっていること

同じ頼み（水着の女性、種 7）を 2 つの模型で描かせた結果です（2026-10-24）。

| 模型 | 塗りと線の質 | 崩れ |
|---|---|---|
| Animagine XL 4.0（SDXL） | 高い（利用者の判定） | 組んだ手の指の分かれ目が不明、水着の胸の形が引っ張られる |
| FLUX.2 klein 4B | 簡単な AI の漫画の絵の水準（利用者の判定） | 目立つ崩れは無い。指と足の指は粗い |

SDXL のアニメの模型は、頼みを読む部品が小さい CLIP で、姿勢や手足の数の約束を守る力が弱いです。
FLUX.2 klein は頼みを Qwen3 で読むので、姿勢や形は崩れにくいですが、アニメの塗りの質は届きません。

## 方針: 形と仕上げを分ける

切り貼りも、描いた絵への上塗りもしません。どの段も絵全体を描きます。

| 段 | すること | 使う物 | 理由 |
|---|---|---|---|
| 1. 構図 | 頼みを文で描かせる | FLUX.2 klein 4B（Apache-2.0） | 手足の数と姿勢が崩れにくい |
| 2. 形を取り出す | 1 の絵から奥行きと細い線だけを取る。色と塗りは捨てる | Depth Anything V2 Small（Apache-2.0）、chatdraw.postfx.lineart | 仕上げの模型に、色ではなく形だけを渡す |
| 3. 仕上げ | 2 の形を縛りにして、白紙から絵全体を描く | Animagine XL 4.0 など SDXL のアニメの模型、ControlNet Union ProMax（xinsir、Apache-2.0。奥行き=1、細い線=3） | 塗りと線は SDXL のアニメの模型の質になり、形は 1 に従う |

縛りは工程の前半（6 割）だけに効かせ、後半は模型に細部を任せます（diffusers の `control_guidance_end`）。
縛りを最後まで効かせると、1 の粗い指や線までなぞってしまうためです。

## 試した結果（2026-10-25）

同じ頼み（水着の女性、種 7）を、3 段で描かせました（Actions の実行 40107033810、絵は draw-results ブランチの 40107033810/）。

- 姿勢と体の形は FLUX.2 klein の構図に従い、塗りと線は Animagine XL 4.0 の質で描かれました
- Animagine だけで描いた絵にあった崩れ（組んだ手の指、水着の胸の引っ張られ）は、この 1 枚では出ていません。両手の指の描き分けは少なめです
- 背景（浜辺の線）は構図の絵から変わりました。縛りを工程の前半だけに効かせたためです
- CPU の Actions の機械で、全体に 9427 秒かかりました。1 つの処理の中で FLUX のあとに SDXL を読んだのが重かったとみて、段ごとに別の処理で動かす形に直しました
- 出来の判定は利用者がします。1 枚だけなので、崩れが減ったかどうかは、種を変えて確かめる必要があります

## 設計の見直し（2026-10-25）

複雑な姿勢（振り返り、胸の前で手を組む）の比べで、2 段の仕組みに次の設計の弱さが出ました。

| 弱さ | 起きたこと | 直した設計 |
|---|---|---|
| 1 つのジョブで全段を通していた | 構図の段で 240 分の上限に当たり、絵が 1 枚も残らなかった（実行 40142913883） | 構図と仕上げを別のジョブにし、構図の絵を先に draw-results に置く。頼みに `composition_run` を書けば、前の構図から仕上げだけを描き直せる |
| 構図の段でメモリが足りなかった | 頼みを読む部品（Qwen3、約 8GB）を抱えたまま描き、1 工程に約 23 分かかった | 頼みを 1 回読んだら、その部品を外してから描く |
| 1 回の実行で 1 枚しか比べられなかった | 縛りの強さを変えるたびに構図から描き直し、1 回に数時間かかった | 1 つの構図から縛りの組み合わせ（variants）を何通りも描く。仕上げの模型は 1 回だけ読む |
| 細い線を縛りにしていた | 構図の模型の粗い指や塗りの癖まで、仕上げに渡る | 既定を骨組み（openpose の体・手・顔、Union の 0）と奥行きにする。細い線は比べの 1 通りとして残す |

骨組みは体の向きと手足の位置だけを渡し、指の形や塗りは渡しません。手の骨組みが取れない絵では、手は仕上げの模型が描きます。
どの組み合わせが崩れにくいかは、描いた絵を利用者が見て決めます。

## 先に試すこと（Actions の draw-one）

1. 上の 3 段で同じ頼みを描き、Animagine だけの絵、FLUX だけの絵と並べて、利用者が見る
2. 縛りの強さ（奥行き 0.5、線 0.4、効かせる割合 0.6）を変えた時の、崩れと質の変わり方を見る
3. 構図の段の手の形が崩れているときは、その崩れも縛りとして渡ってしまう。手だけは縛りを弱くするか、姿勢の骨組み（openpose、Union の 0）に替える

## 次の候補（調べた物）

- PAG（Perturbed-Attention Guidance）: diffusers の公式の機能で、学び直しなしに形を整えるとされる。SDXL の一部の描き方だけで使える（[diffusers の文書](https://huggingface.co/docs/diffusers/main/en/using-diffusers/pag.md)）。手に効くかは書かれていないので、試してから決める
- NoobAI 用の ControlNet（Eugeoter の depth、lineart_anime）: NoobAI 系の模型で仕上げるときは、こちらが合う可能性がある
- 高解像度の 2 回目（hires fix）: 描いた絵全体を 1.5 倍にして、弱い強さで描き直す。細部が増える。全体を描き直すので切り貼りではない

## 出典

- [xinsir ControlNet++（Union）の README](https://github.com/xinsir6/ControlNetPlus)（種類の番号: 0 openpose、1 depth、2 太い線、3 細い線、4 normal、5 segment）
- [diffusers: ControlNetUnionModel](https://github.com/huggingface/diffusers/blob/main/docs/source/en/api/models/controlnet_union.md)
- [diffusers: Perturbed-Attention Guidance](https://huggingface.co/docs/diffusers/main/en/api/pipelines/pag.md)
- [ControlNet Union for SDXL（ComfyUI の解説）](https://lilys.ai/ja/notes/comfyui-20260119/controlnet-union-sdxl-one-model)
- [Refiner: Two-stage generation](https://runware.ai/docs/learn/refiner)
