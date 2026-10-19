# 使っている部品と模型のライセンス

どれもリポジトリには入れず、利用者の PC に初回に取る（`tools/gen/setup.py`、`tools/llm/setup.sh`、`tools/engine/setup.sh`）。
「確かめた」は 2026-10-19 に Hugging Face の模型の情報、または入れた部品の説明書き（Python のパッケージの情報）で読んだもの。
「確かめていない」は、出所の窓口がこの環境から読めず、まだ見ていないもの。

## 描く・読む模型

| 模型 | 使い道 | ライセンス | 確かめ方 |
|---|---|---|---|
| cagliostrolab/animagine-xl-4.0 | 既定の描く模型（SDXL） | CreativeML Open RAIL++-M | 確かめた（HF） |
| Lykon/dreamshaper-xl-lightning | SDXL の速い描画 | CreativeML Open RAIL++-M | 確かめた（HF） |
| Meina/MeinaMix_V11 | SD1.5 の描く模型 | CreativeML Open RAIL-M | 確かめた（HF） |
| latent-consistency/lcm-lora-sdv1-5 | SD1.5 の段数を減らす | CreativeML Open RAIL++-M | 確かめた（HF） |
| diffusers/controlnet-depth-sdxl-1.0-small | 姿勢の下絵（奥行き）で縛る | CreativeML Open RAIL++-M | 確かめた（HF） |
| h94/IP-Adapter | 参考画像を効かせる | Apache-2.0 | 確かめた（HF） |
| depth-anything/Depth-Anything-V2-Small-hf | 奥行きを読む | Apache-2.0 | 確かめた（HF） |
| google/owlv2-base-patch16-ensemble | 持ち物の数と分かれを数える | Apache-2.0 | 確かめた（HF） |
| sayeed99/segformer_b3_clothes | 部位分け | MIT | 確かめた（HF） |
| SmilingWolf/wd-vit-tagger-v3 | 絵をタグで読む | Apache-2.0 | 確かめた（HF） |
| Qwen/Qwen2.5-0.5B・1.5B-Instruct-GGUF | 頼みを描く言葉に直す（手元の言葉の模型） | Apache-2.0 | 確かめた（HF） |
| Qwen/Qwen2.5-3B-Instruct-GGUF | 同上（大きい方） | Qwen Research License（ライセンスの種類は other。商用の利用に制限がある） | 確かめた（HF の種類）。条文は読んでいない |
| Real-ESRGAN（x4plus_anime_6B、x4plus） | AI で拡大する | BSD-3-Clause と記憶 | 確かめていない |
| RTMPose（mmpose の rtmpose-m-body7） | 体の関節を読む | Apache-2.0 と記憶 | 確かめていない |
| MediaPipe の手の模型 | 手を読む | Apache-2.0 と記憶 | 確かめていない |
| U2-Net（rembg 経由） | 背景を外す | Apache-2.0 と記憶（rembg は MIT、確かめた） | 模型は確かめていない |
| Blender、MPFB（MakeHuman） | 人体と立体の形 | Blender は GPL-2.0 以降、MPFB は GPL-3.0、MakeHuman の基本素材は CC0 と記憶 | 確かめていない |

## Python の部品（主なもの）

| 部品 | 版 | ライセンス |
|---|---|---|
| torch（CPU 版） | 2.14.1 | BSD 系（パッケージの情報は Apache-2.0 を含む表記） |
| diffusers / transformers / accelerate / huggingface-hub / safetensors | 0.40.0 / 5.18.0 / 1.15.0 / 1.33.0 / 0.8.0 | Apache-2.0 |
| Pillow | 12.3.0 | MIT-CMU |
| numpy / scipy / scikit-image | 2.4.6 / 1.17.1 / 0.26.0 | BSD 系 |
| onnxruntime | 1.30.0 | MIT |
| rembg / psd-tools | 2.0.85 / 1.23.0 | MIT |
| fastapi / pydantic / mcp | 0.143.0 / 2.14.0 / 2.3.0 | MIT |
| uvicorn / imageio-ffmpeg | 0.54.0 / 0.6.0 | BSD-3-Clause / BSD-2-Clause |

## 配り方への影響

- 描く模型（RAIL 系）は、出来た絵の商用の利用を認めるが、使い道の制限（条文の別表）を利用者にも課す。段 2（有料）に進む前に条文を読み、利用規約に引き継ぐ
- Qwen2.5-3B は商用に制限がある。有料で配る前に、既定の言葉の模型を Apache-2.0 の 0.5B・1.5B に限るか、別の模型に替える
- GPL の部品（Blender、MPFB）は同梱せず、利用者が取る形を保つ
