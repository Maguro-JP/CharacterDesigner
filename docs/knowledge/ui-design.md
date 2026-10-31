# chatdraw の画面設計（AI 絵の道具の画面から選んだ形）

chatdraw（PySide6 の Windows デスクトップアプリ）の画面を、よく使われている AI 絵の道具と描画アプリの画面と比べ、
このアプリに合う形を決めるための資料。現状の把握は origin/main の `chatdraw/app.py`・`aipanel.py`・`canvas.py`・
`activity.py`・`librarypanel.py`・`manager.py`・`chatpanel.py`・`tour.py`・`keys.py` と、AI タブの画面写しによる。

## 1. 原則（使う人: Windows で 1 人、アニメのキャラクターデザインを作る人）

1. 開いた瞬間に「書いて、描く」だけが見える。Fooocus が示したとおり、最初の画面は言葉の欄と描くボタンと結果だけでよい。設定は「詳しく」を開いた人にだけ出す（段階的開示）。
2. 主役は絵。キャンバスと結果の一覧が画面の大部分を取り、欄は中身に見合う幅にする（CLAUDE.md の「枠を取りすぎない」）。
3. 説明はボタンの中に書かずツールチップに出す。ツールチップには操作のキーも添える（Krita、CLIP STUDIO PAINT と同じ）。
4. 欄（ドック）は利用者が出し入れ・移動・浮かせできる。並べ方は「作業の型」として保存し、メニューから呼び戻せる（Krita の Workspace、CLIP STUDIO PAINT のワークスペース）。
5. 結果の 1 枚ごとに次の操作（もう一度、似た絵、ここを直す、拡大、レイヤーに置く、お気に入り）を付ける。Midjourney と InvokeAI の「結果から次へ」の流れ。
6. 待ちは見えるようにする。描いている間も操作でき、頼みは順番待ちに積める。進み・残り時間・止めるがいつも同じ所にある。
7. 失敗の文は「何が起きたか・どうすれば直るか・押せる直し方」の 3 つで書く（Nielsen の 9 番目、Fluent の InfoBar）。
8. 取り返しのつく操作は確認を出さずに元に戻すで戻せるようにし、確認は消すときだけにする（Apple HIG）。
9. 検品（作画監督）の結果は利用者に要る分だけ出す。内部の点数は出さず、崩れの場所を絵の上に印で示す。

## 2. 提案する画面の割り付け

```
┌メニュー: ファイル 編集 描く 表示 模型 ヘルプ ──────────── [作業の型 ▼] ┐
│道具│                                     │ 右の欄（タブで重ねる）       │
│の縦│          キャンバス                 │  AI / レイヤー / カラー       │
│帯  │   （絵の上に「直す範囲」の筆）      │                              │
│    │                                     │                              │
├────┴─────────────────────────────────────┴──────────────────────────────┤
│ 言葉の欄（2 行、タグの候補）[禁止ワード▸] [作風: サムネイル▼] [描く] [■]│
├─────────────────────────────────────────────────────────────────────────┤
│ 結果の帯: 今回の絵の縮小図が横に並ぶ（★ 似た絵 直す 拡大 置く）  順番待ち 2 │
└状態の行: 模型名・進み・残り時間・メモリ ────────────────────────────────┘
```

- 初めに見えるもの: キャンバス、左の道具、下の言葉の欄、結果の帯、右の欄の AI タブ（作風と大きさだけ）。
- 初めは隠すもの: チャット、履歴（操作）、ブラシの細かい設定、カラーのパレット、ライブラリ、進みのドック（状態の行に寄せる）。「表示」メニューと各欄の右クリックから出す。
- 詳しく（AI タブの「詳しく」を開いた人だけ）: 種（固定・再利用）、手順の数、強さ、CFG、サンプラー、ラフから描く強さ、二段描き、LoRA。
- メニューの並び:
  - ファイル: 新規、開く、最近開いたもの、保存、書き出す（PNG / PSD / 結果をまとめて）、ディレクトリを開く、終了
  - 編集: 元に戻す、やり直す、操作の履歴、切り取り・写し・貼り付け、選択、設定
  - 描く（新設）: 描く、もう一度、似た絵、選んだ所を直す、2 倍に拡大、線画に、ちびキャラに、ドット絵に、止める、順番待ちを見る
  - 表示: 欄の出し入れ、作業の型（保存・呼び出し・初期に戻す）、拡大縮小、比べる表示、全画面
  - 模型: 模型の管理、お気に入りの模型の切り替え、模型を足す
  - ヘルプ: 使い方の案内（ツアー）、キーの一覧、説明書、更新の確認
- いまの `aipanel.py` の「AI プリセット」「画風」の大きなボタンの並び（画面写しで縦の半分を取る）は、縮小図付きの一覧（ドロップダウンかグリッド）1 つにまとめる。

## 3. 場所ごとの具体的な変更

### 言葉の欄（`app.py` の `self.entry`、`aipanel.py` の `AiPanel`）
- 欄をキャンバスの下に移し、2〜4 行に伸びる形にする。いまは右の AI ドックの上にあり、絵から目を離さないと書けない。
- タグの候補: 打った語から Danbooru 式のタグと日本語の語（`jaterms.py`）の候補を出す（NovelAI、a1111 の tag autocomplete）。候補には使われている数を薄く添える。
- 語の重み: 語を選んで Ctrl+↑↓ で `(語:1.1)` を上げ下げ（a1111、Krita AI Diffusion と同じキー）。
- 「模型に渡る言葉」（`AiPanel.preview`）は欄の下に 1 行で畳み、開けば全文を見られる。
- 禁止ワードは「▸ 禁止ワード」で開く欄にし、初めは閉じる。
- いまのお気に入りの語の横スクロールの帯（`fav_button` で固定した語）は、欄の右の ★ からのメニューに移す。
- 声のボタンはツールチップ付きの小さな図にし、Windows 以外では隠す。

### 結果と一覧（`activity.py` の `ActivityPanel` の「描いた絵」、`app.py` の履歴ドック）
- キャンバスの下に横長の「結果の帯」を新設し、今回描いた絵を並べる。押すとキャンバスに出し（置き換え、元に戻すで戻る）、矢印キーで送る。
- 縮小図に乗せたときに操作の図を出す: ★お気に入り、似た絵（同じ言葉で種を少し変える）、もう一度（同じ種）、選んだ所を直す、2 倍に拡大、レイヤーとして置く、言葉と種を欄に戻す（Midjourney の Vary / Upscale / Remix、InvokeAI のギャラリー）。
- 2 枚を選んで比べる表示（左右並べと、境目を動かして見る重ね）。InvokeAI の Compare。
- 「描いた絵」の一覧に絞り込み（お気に入りだけ、模型ごと、日付、言葉で探す）とボードを足す。
- 検品で崩れが出た絵は縮小図の隅に印を出し、開くと崩れの場所を `redpen.py` の赤丸で示す。

### キャンバスとレイヤー（`canvas.py` の `Canvas`・`Layer`、`app.py` のレイヤードック）
- 「直す範囲」の筆: 選んだ範囲か塗った範囲だけを AI に描き直させる（Photoshop の生成塗りつぶし、Krita AI Diffusion の選択範囲、InvokeAI の Inpaint mask）。範囲の外は 1 画素も変えない（CLAUDE.md の決まり）。いまの選択の道具と同じ帯に置く。
- AI が描いた絵は新しいレイヤーとして入れ、レイヤー名に言葉の頭と種を入れる。レイヤー一覧に縮小図を出す。
- 操作の履歴（`activity.py` の「操作」タブ）を、押すとその時点に戻れる一覧にする（Photoshop の History、Krita の Undo History）。
- 範囲を変えずに比べる「前と後」の切り替え（押している間だけ元の絵を出す、`\` キー）。

### 模型の選び方（`manager.py` の `ModelManager`、`app.py` の `model_label`）
- 言葉の欄の横に模型の切り替え（ドロップダウン）を置き、お気に入りと最近使ったものを上に出す。開くと縮小図・作風のタグ・推奨の印を並べる（Civitai、Leonardo.ai の模型一覧）。
- 推奨は動かして確かめ、点の届いたものだけに付ける（CLAUDE.md）。点そのものは出さない。
- 管理画面は「入っているもの / 足せるもの」の 2 つのタブにし、取得の進みを行ごとに出す。消すのは管理画面で選んだときだけ。

### チャット（`chatpanel.py` の `ChatPanel`）
- 初めは隠し、「表示」とキー（Ctrl+Shift+C）で出す。右の欄にタブとして重ねる。
- チャットの返事に「この言葉で描く」「欄に入れる」のボタンを付け、返事から欄へ 1 回で移せるようにする。
- 返事の生成中は止めるボタンを同じ吹き出しに出す。

### ライブラリ（`librarypanel.py` の `LibraryPanel`、`library.py`）
- 「作品」「資料」「好み」を、結果の一覧と同じ縮小図のグリッドにそろえる。資料の絵はキャンバスに参考画像として引きずって置ける（イラストレーターモードの入口）。

### 設定（`settings.py` の `SettingsDialog`）
- 左に項目の一覧、右に中身の形（Windows の設定と同じ）にし、上に検索の欄を置く。
- 各項目に「初期に戻す」。保存場所（C:\LLM）を開くボタン。

### 進みと失敗（`popup.py` の `ProgressPopup`、`notice.py` の `Notice`、進みドック）
- 進みは状態の行と、描いている絵のその場の下書き（途中の絵）で出す。進みのドックは初めは隠す。
- 順番待ち: 描いている間に「描く」を押すと頼みが積まれ、状態の行に件数を出す。押すと順番待ちの一覧（並べ替え・取り消し）。
- 失敗は `Notice` を InfoBar の形にそろえ、「何が起きたか / 直し方 / [直すボタン]」を書く。例: メモリ不足なら「大きさを下げて描き直す」ボタン。英語の例外の文は「詳しく」の中に入れる。

### キー（`keys.py` の `KeyDialog`）
- 初めから入れるキー: Ctrl+Enter 描く、Esc 止める、Ctrl+Shift+V 似た絵、Ctrl+R もう一度、Ctrl+↑↓ 語の重み、← → 結果を送る、F お気に入り、Tab で欄を全部隠す（Krita、Photoshop と同じ）、`\` 前と後、Ctrl+/ キーの一覧。
- キーの一覧は検索できる形にし、ほかの描画アプリの並び（Photoshop 風、CLIP STUDIO PAINT 風）を選べるようにする。

### 使い方の案内（`tour.py` の `Tour`、`tours.py`）
- 初めての起動は 4 歩だけ: 言葉の欄 → 描く → 結果の帯 → 直す範囲の筆。残りは「ヘルプ → 使い方の案内」で機能ごとに選ぶ。
- 欄が隠れていても案内できるよう、案内の歩で欄を一時的に出す。途中でやめても次に続きから選べる。
- 空の画面（何も描いていないとき）に、言葉の例を 3 つ押せる形で出す（Fooocus、Leonardo.ai の空の状態）。

## 4. 足りない機能（効き目と手間で並べた）

| 順 | 機能 | 効き目 | 手間 | 直す場所 |
|---|---|---|---|---|
| 1 | 結果の 1 枚ごとの操作（似た絵・もう一度・直す・拡大・置く・言葉を戻す） | 大 | 小 | `activity.py`、`app.py` |
| 2 | 種の固定と再利用（結果から種を戻す） | 大 | 小 | `aipanel.py`、`engine.py` |
| 3 | タグの候補（日本語の語と Danbooru のタグ） | 大 | 中 | `app.py` の `entry`、`jaterms.py` |
| 4 | 語の重み（Ctrl+↑↓） | 中 | 小 | `app.py` の `entry`、`engine.py` の `Words` |
| 5 | 直す範囲の筆（範囲の中だけ描き直す） | 大 | 中 | `canvas.py`、`engine.py`、`redpen.py` |
| 6 | 順番待ち（描いている間に次を積む） | 大 | 中 | `app.py` の `Job` / `Task` |
| 7 | 作風の縮小図付き一覧 | 中 | 小 | `aipanel.py` |
| 8 | お気に入りとボード、絞り込み | 中 | 小 | `activity.py`、`library.py`、`ratings.py` |
| 9 | 比べる表示（並べ・境目） | 中 | 中 | 新しい欄（`activity.py` から開く） |
| 10 | 落ちたときの復旧（自動保存と再起動時の復元） | 大 | 中 | `project.py`、`app.py` |
| 11 | 途中の絵の表示と残り時間 | 中 | 中 | `engine.py` の `Painter`、`popup.py` |
| 12 | 結果をまとめて書き出す（言葉と種を書いた添え書き付き） | 中 | 小 | `app.py` の書き出す |
| 13 | 作業の型の保存と呼び出し | 中 | 小 | `layouts.py` |
| 14 | 操作の履歴を押して戻る | 小 | 小 | `activity.py`、`commands.py` |
| 15 | 模型のお気に入りと最近使ったもの | 中 | 小 | `manager.py`、`ratings.py` |
| 16 | 失敗の文に直すボタン | 中 | 小 | `notice.py` |
| 17 | 2 倍より大きい拡大と拡大の模型の選択 | 小 | 中 | `upscale.py` |
| 18 | 参考画像を引きずって置く（姿勢・色の参考） | 中 | 中 | `canvas.py`、`app.py` の `Reference` |

## 5. 出典

- Krita AI Diffusion（Generate / Refine / Live / Upscale、選択範囲の描き直し、履歴の帯）: https://docs.interstice.cloud/ と https://github.com/Acly/krita-ai-diffusion
- Krita のワークスペースとドック: https://docs.krita.org/en/user_manual/getting_started/navigation.html
- CLIP STUDIO PAINT のワークスペースとショートカット: https://help.clip-studio.com/en-us/manual_en/
- Photoshop 生成塗りつぶし（選択範囲、3 つの候補、文脈のタスクバー）: https://helpx.adobe.com/photoshop/using/generative-fill.html
- InvokeAI（Unified Canvas、Boards、Gallery、Compare）: https://invoke-ai.github.io/InvokeAI/ と https://support.invoke.ai/
- Fooocus（最小の画面、Advanced の切り替え、Styles）: https://github.com/lllyasviel/Fooocus
- ComfyUI（ノード、順番待ち）: https://docs.comfy.org/
- Midjourney（Vary、Upscale、Remix、Web のギャラリー）: https://docs.midjourney.com/
- NovelAI 画像生成（タグの候補、強調の記法）: https://docs.novelai.net/image.html
- Stable Diffusion WebUI Forge: https://github.com/lllyasviel/stable-diffusion-webui-forge 、語の重みのキーは https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Features
- a1111 タグの候補の拡張: https://github.com/DominikDoom/a1111-sd-webui-tagcomplete
- Leonardo.ai（模型の一覧、空の状態の例）: https://docs.leonardo.ai/
- Apple Human Interface Guidelines: https://developer.apple.com/design/human-interface-guidelines/
- Windows のアプリ設計（Fluent、InfoBar、設定の形）: https://learn.microsoft.com/windows/apps/design/ と https://learn.microsoft.com/windows/apps/design/controls/infobar
- Nielsen Norman Group の 10 の原則: https://www.nngroup.com/articles/ten-usability-heuristics/
- 段階的開示: https://www.nngroup.com/articles/progressive-disclosure/
