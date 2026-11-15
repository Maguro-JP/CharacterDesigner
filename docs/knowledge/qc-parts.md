# 検品の部品（模型）の表

検品が読む模型の一覧。目録は `chatdraw/qcparts.py` の 1 か所にあり、初回の取得（`chatdraw/setup.py` の `Fetcher.run`）と、
AI のメニューの「検品の部品を取り直す」が、無い物だけを取る。取れなかった物は、初回の取得の最後の画面に 1 行で名前を出す。
大きさは Hugging Face の配布の大きさ（2026-11-14 に API で数えた）。

| 部品 | 模型 | 読む所 | 置き場 | 大きさ | ライセンス |
| --- | --- | --- | --- | --- | --- |
| 部位分け（顔・腕・脚・髪・服の塗り分け、`.parts.png`） | `sayeed99/segformer_b3_clothes`（config.json、model.safetensors） | `tools/gen/edit.py` の `parts`、`chatdraw/sanity.py`、`chatdraw/facefeat.py`、`chatdraw/origqc.py` | HUB（Hugging Face の置き場） | 約 189MB | MIT |
| 人の枠（人数を数える） | `PekingU/rtdetr_r50vd_coco_o365` | `chatdraw/sanity.py` の `count_people` | HUB | 約 172MB | Apache-2.0 |
| 顔と頼んだ物のタグ（顔の外の目、頼んだのに無い物、人数） | `SmilingWolf/wd-vit-tagger-v3`（model.onnx、selected_tags.csv） | `chatdraw/requestcheck.py`、`tools/gen/tagger.py`、`chatdraw/sanity.py`、`tools/gen/facecheck.py` | HUB | 約 380MB | Apache-2.0 |
| 体の点（手の振り分け、顔の向き、2 段で描く姿勢） | `usyd-community/vitpose-base-simple` | `chatdraw/twostage.py` の `keypoints`、`chatdraw/handcheck.py`、`tools/gen/facecheck.py` | HUB | 約 344MB | Apache-2.0 |
| 手（指の数と形） | MediaPipe の `hand_landmarker.task`（中の hand_landmarks_detector.tflite と hand_detector.tflite） | `chatdraw/handcheck.py`、`tools/gen/hands.py` | データの置き場の `gen/mediapipe` | 約 8MB | Apache-2.0 |
| 足（足の指の点） | `yzd-v/DWPose` の `dw-ll_ucoco_384.onnx` | `chatdraw/handcheck.py` の `check_feet`、`tools/gen/feet.py` | データの置き場の `gen/pose` | 約 134MB | Apache-2.0 |

合わせて約 1.2GB。`chatdraw/qcmanual.py` は上の検品を呼ぶだけで、自分の模型は持たない。
自動選択（キャンバスの選択）は、確かめた範囲では模型を読まない。

## 部位分けが毎回落ちていた訳

- 名前: `sayeed99/segformer_b3_clothes` は Hugging Face にあり（API が 200 を返す）、名前は正しかった。
- 道: アプリは起動のときに Hugging Face の置き場を HUB（`chatdraw/paths.py`）にそろえる。開発の手元の取得（`sh tools/gen/setup.sh`）は `.cache/gen/hf` に入れるので、アプリの HUB には入らない。
- 取り方: `tools/gen/edit.py` は読み込みのときに取らない設定（`HF_HUB_OFFLINE=1`）を入れる。アプリの取得はどこも部位分けの模型を取らなかったので、HUB に無いまま取らずに読み、毎回 `OSError: We couldn't connect to 'https://huggingface.co'` で落ちた。網の不具合に見える文言なので、原因が分かりにくかった。
- 直し: 初回の取得で HUB に取る（`chatdraw/qcparts.py`）。取る間だけ取らない設定を外す（検品を先に読んでいると、取る時も取れなかった）。置き場に無いときの文言は、何がどこに無いかと取り直しの入口を書く。
