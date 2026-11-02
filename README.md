# CharacterDesigner

CharacterDesigner の製品は描画アプリ chatdraw です。チャットで頼むと AI がキャラクターデザインやイラストを描き、作画監督が数字で検品し、人がその上に描き足せる Windows のデスクトップアプリです。頼みごとは日本語に限りません。English: [README.en.md](README.en.md)

開発はすべて [chatdraw/](chatdraw/README.md) で行います。配る Setup.exe は `packaging/chatdraw/` と `.github/workflows/chatdraw-*.yml` で組みます。

## 入れ方と使い方

- 入れ方・模型の取り方と手で置く方法・更新・削除・困ったときは [手順書](chatdraw/help/install.md)
- 使い方は [操作方法](chatdraw/help/manual.md)。どちらもアプリの「ヘルプ」メニューから開けます。「ヘルプ」→「使い方ツアー」（F1）と「機能ごとの案内」で画面の上で案内します
- 動かせる模型と、それぞれの大きさ・得意なこと・商用の可否は [docs/models.md](docs/models.md)

## 出来ること

入口はアプリの中の名前のまま書いています。メニューは上の帯、欄は「ウィンドウ」メニューで出し入れします。

### 描く

- 「AI」の欄で頼みの言葉を書いて描く。欄はタブ（描く内容・作風・模型・詳しい設定・加工）に分かれ、描くボタンはタブの外にあります。「🎤」で声で頼めます（Windows の音声入力）
- 作風のプリセット（キャラデザ、ラフを清書、ラフから自由に、イラスト、アイコン、赤ペンで直す）と画風（おまかせ、アニメ、厚塗り、水彩など）
- 「詳しい設定」のタブで枚数・種・参考画像（「参考画像に寄せる」）
- 「AI」メニューの「おまかせ」: 手元の模型から頼みに合い点の高い物を選び、工程ごとに描く・検品する・落ちた所を直すを回します
- 新しく描いた絵はキャンバスを置き換えます（「編集」→「元に戻す」で戻せます）。頼んだ言葉は履歴に残り、履歴の右クリックの「この設定で描き直す」ですぐ頼み直せます

### キャラクターデザイン

「キャラクターデザイン」メニュー: 「描いた人物を設定資料に保存…」「使う人物」「三面図を描く」「表情差分を描く」「設定資料を開く」。

### 直す・広げる・加工する

- 赤ペン（道具の帯、またはキャンバスの右クリックの「道具」）で直す所を囲み、囲みの中だけを AI に直させます。囲みの外は変えません
- 「ファイル」→「画像を開いて直す…」: 手元の絵を開いて、同じように囲んで直します。履歴の右クリックの「編集する（囲んで直す）」も同じです
- キャンバスの右クリックのショートカット。加工を種類ごと（綺麗にする、描き直して整える、拡大、質感、空気感、清書、加工、広げる）に並べ、★ を付けた物とよく使う物を一番上に出します。直しの頼みの言葉も「指示で直す」に登録でき、選ぶと今の絵（囲みがあれば囲みの中）をその言葉で直します。広げるときは広げた所だけを描き、元の絵の画素は変えません
- 「AI」の欄の「加工」のタブ: 「ちびキャラに」「線画に」「ドット絵に」「絵を 2 倍に拡大」。元の絵は残し、新しいレイヤーに重ねます
- 履歴の右クリックの「3D に進む…」: 絵から厚みのある形を作り、Blender で開きます

### 作画監督（検品）

描いた絵の手・足・顔の崩れ、頼んだ物が描けているか、CharacterDesigner 独自の数字の検品（顔の形、影の順序、髪の色など。`tools/gen/measure.py` の数字と、ユーザーの判定から学んだ基準）を、おまかせの流れの中で見ます（`chatdraw/omakase.py`、`chatdraw/origqc.py`）。落ちた所は直して描き直します。

### 模型

- 「AI」メニュー: 絵の模型を選ぶ、「★ お気に入り」、「直しに使う模型」、「模型の管理…」
- 「模型の管理」の窓: 取得・使う・削除・更新、「Hugging Face の名前で足す」、「ファイルを選んで使う…」。行の「…」か右クリックで、非表示・ブロック・停止・削除。ブロックした模型は、おまかせ・推奨・「AI」メニューに出ず、取りにも行きません

### 絵を描く・整える

- 道具（ペン、消しゴム、四角の選択など）、「ブラシ」「カラー」「レイヤー」の欄、「選択範囲」「レイヤー」メニュー
- 「表示」→「テーマ」（「テーマを作る…」で自分の色）、「配置」メニュー（今の配置を保存、書き出し、読み込み）、「ウィンドウ」の「欄の位置」「帯の位置」
- 「表示」→「タイムラプスを記録する」「タイムラプスを見る…」。書き出しは「GIF に書き出す」「動画に書き出す」

### 保存・書き出し・ごみ箱

- 「ファイル」→「保存」「名前を付けて保存…」「書き出す」（「PNG（重ねた 1 枚）…」「PSD（レイヤーごと）…」）、「ディレクトリを開く」
- 消した絵は「ファイル」→「ごみ箱…」から元に戻すか本当に消します
- 「ライブラリー」の欄（作品・資料・好み のタブ）。★ を付けた絵は右クリックの「学習用に集める」で手元に書き出せます（学習そのものはまだアプリにありません）
- 履歴の右クリックの「SNS に送る」
- 「ヘルプ」→「更新を確かめる」

## 描く内容の制限

アプリは、描く内容を最初から規制しません。固定の制限は 1 つだけで、子どもを表す言葉と性的な言葉が並んだ頼み（loli・shota などの語を含む）は描きません（`chatdraw/engine.py` の `refused`）。考え方は [docs/filters.md](docs/filters.md)。ユーザーが自分で入れ切りするフィルターの板は、まだアプリにありません。

## アプリに入れていない道具

`tools/` などに残っている道具は、アプリにまだ入れていない検品・学習・加工の部品です。試験で動くことを確かめていて、アプリに入れるかはユーザーが決めます（候補の一覧は [docs/reports/cleanup-20261031.md](docs/reports/cleanup-20261031.md)）。

- 作画監督の数字と学習（`tools/gen/measure.py`、`tools/gen/faceform.py`、`tools/gen/qc.py`、`tools/gen/occlusion.py`、`tools/gen/normlearn.py`、描き方の比べは `tools/gen/bench.py`）。基準は `styles/anime-norms.json`、ユーザーの基準は設定の置き場の norms.user.json（git に入れない）
- 仕上げの補正（`tools/gen/retouch.py`）、線の清書（`tools/gen/inking.py`）、質感（`tools/gen/materials.py`）、空気感（`tools/gen/atmosphere.py`）
- 言葉の模型で頼みごとを描く言葉に直す（`tools/gen/free_text.py`、`tools/gen/local_llm.py`、取るのは `tools/llm/setup.sh`）
- Blender・MakeHuman の人形と下絵（`tools/engine/`）、部品から組むドット絵の道具（`tools/build.py`、`tools/check.py`、`tools/render.py`）

```bash
PYTHONPATH=.cache/gen/lib python3 tools/gen/measure.py 絵.png --hair "#1e1a24,#a8203c"
```

## 設定

| 環境変数 | 用途 | 必須 |
|---|---|---|
| `CD_HOME` | アプリの設定・部品・記録の置き場所（`chatdraw/paths.py`） | 任意 |
| `CD_DEVICE` | `tools/` の道具が描く場所（`cuda`・`mps`・`cpu`、`tools/gen/device.py`） | 任意 |
| `CD_LLM_URL` / `CD_LLM_MODEL` | `tools/gen/free_text.py` が使う手元の言葉の模型の窓口（OpenAI 互換）と模型の名前 | 任意 |

## 記録

- 地図: [docs/STRUCTURE.md](docs/STRUCTURE.md)、絵の一覧: [library/INDEX.md](library/INDEX.md)
- 見落としの事例: `docs/knowledge/sakkan-cases.md`、描き方で分かったこと: `docs/knowledge/ai-drawing-notes.md`
- 外部の画像生成との比べ: `docs/benchmarks/`
- 決めたことと理由: `docs/knowledge/decisions.md`、道のり: `docs/ROADMAP.md`
- 記録の決まり: [docs/record-policy.md](docs/record-policy.md)、出典: [docs/references.md](docs/references.md)、使っている部品: [docs/third-party.md](docs/third-party.md)

## ディレクトリ構成

| 場所 | 役割 |
|---|---|
| `chatdraw/` | 製品のデスクトップアプリ（PySide6）。試験は `chatdraw/tests/` |
| `packaging/chatdraw/` | Setup.exe の組み方（Actions の `chatdraw-*.yml` が流す） |
| `tools/gen/` | 描く・直す・測る道具。`hands.py`・`tagger.py`・`cdhome.py` はアプリに同梱 |
| `tools/` | ドット絵の描画器と検品、比較、絵の目録 |
| `styles/` | 作風と作画監督の基準（数字と出典） |
| `characters/` | ドット絵のキャラクター（部品と書き出し） |
| `docs/` | 決めたこと、分かったこと、道のり、比べの記録 |
| `config/` | ユーザーの設定の見本。ユーザーの設定そのものはリポジトリに入れない |

## 開発者向け

```bash
# 道具の試験
python3 -m unittest discover -s tests
# アプリの試験（PySide6 のある環境）
QT_QPA_PLATFORM=offscreen python3 -m unittest chatdraw.tests.test_chatdraw
```

## ライセンス

非公開（社内・個人用）。使える人を限り、ソースは公開しない。詳しくは [LICENSE](LICENSE)。配り方の計画は [docs/release-plan.md](docs/release-plan.md)。
