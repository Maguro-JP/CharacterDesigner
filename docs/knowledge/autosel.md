# AI の自動選択（chatdraw/autosel.py）

絵の上を 1 回押す（または四角で囲む）と、押した所の物（髪、顔、服、手、持ち物、背景）を選ぶ。
選択範囲の道具（道具の帯の「自動選択」、キーは A）と、赤ペンの囲み方の「自動選択」の両方で使う。
赤ペンでは選んだ所がそのまま印になり、番号と指示の欄が付く。

## 模型を選んだ理由

| 候補 | ライセンス | 重み | 保守 | transformers で読めるか |
|---|---|---|---|---|
| SAM 2.1 hiera tiny（facebook/sam2.1-hiera-tiny） | Apache-2.0 | 156MB | Meta が更新を続けている（2025-08 に transformers 形式を足した） | 読める（Sam2Model） |
| MobileSAM | Apache-2.0 | 約 40MB | 2023 年から大きな更新が無い | 読めない（別の部品が要る） |
| EfficientSAM | Apache-2.0 | 約 40〜100MB | 2024 年から大きな更新が無い | 読めない |
| SlimSAM（SAM 1 を縮めた物） | Apache-2.0 | 39〜112MB | 2024 年から更新が無い | 読める（SamModel） |

SAM 2.1 tiny にした。ライセンスが商用でも使える形で、保守が続いていて、アプリが既に持っている transformers だけで読めるため
（別の部品を足すと配布が重くなる）。MobileSAM・EfficientSAM は軽いが、読むための部品を足す必要があり、保守も止まっている。

## 置き場と取り方

- 共有の置き場（`paths.HUB`。Windows では `C:\LLM\huggingface`）に、初めて使うときに取る（shared-models の決まり）
- 取るのは config.json、model.safetensors、preprocessor_config.json、processor_config.json の 4 つだけ（元の .pt は取らない。同じ重みが 2 つになるため）
- 取れない・メモリが足りない・読めないときは、部位分け（`facefeat.seg_small` の SegFormer、`.parts.png` と同じ模型）で、
  押した所と同じ部位のつながった所を選ぶ。部位分けも無ければ、押した所の色に近い画素のつながりを選ぶ。
  どの道で選んだかは状態の帯とチャットに 1 行で出す（代わりの道で選んだことを黙らない）

## メモリ

- 読む前に `membudget.budget()` の RAM が 1.2GB（私の推測を含む見積もり）より少なければ読まずに代わりの道へ回す
- `membudget.exclusive("autosel", …)` で、描く模型と同時に載せない。選び終えたら毎回降ろす
- 前処理は自前で書いた（transformers の Sam2 の前処理は torchvision を要求し、アプリの環境に無い）

## 測った数字（CPU、この開発の環境）

- 読み込み 0.5 秒、1 回の推論 8〜17 秒（256×384 の絵。1 回目は遅い）
- 画面の糸を止めないよう、裏の糸（`Window.in_background`）で回す
