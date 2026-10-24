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
