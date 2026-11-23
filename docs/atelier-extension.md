# AtelIer の拡張・単体のアプリ・ほかの AI サービスから使う口

CharacterDesigner は AtelIer のために設計するが、単体のアプリとしても動き、ほかの AI サービスからも使えるように設計する。
使われ方ごとに中身を作り分けると同じ処理が何か所にも分かれて直し漏れが出るので、中身は 1 つにして入口だけを分ける。

## 決まり

| 層 | 中身 |
|---|---|
| 中身の処理 | UI に頼らない部品（Python の関数・クラス）。窓・メニュー・AtelIer を読み込まない |
| 入口 1: AtelIer の拡張 | `extension.json` とメニュー。拡張の置き場（`C:\ProgramData\AtelIer\extensions\character_designer\`）に置かれ、AtelIer が読み込む |
| 入口 2: 単体のアプリ | 自分のウィンドウ。AtelIer が無くても起動する（配るのは下の「配る物」の単体の Setup） |
| 入口 3: ほかの AI サービスから使う口 | MCP のサーバーと、コマンドで呼べる口。中身の処理をそのまま呼ぶ |

- 置き場と設定は、どの入口から使っても同じにする。入口ごとに置き場を持つと、同じ人の設定や作った物が入口ごとに分かれるため
- 言葉の模型は共通の置き場 `C:\LLM` に置く
- AtelIer が無くても動き、AtelIer があれば拡張として載る
- 次は私の推測: ほかの AI サービスから使う口は MCP のサーバー（標準入出力で話す形）にし、コマンドの口は `python -m character_designer <操作>` で JSON を返す形にして、2 つが同じ操作の一覧を使う

AtelIer の側の決まりは、AtelIer の `docs/knowledge/integration.md` の「拡張の設計」と「インストーラーどうしの連携」。

## AtelIer が統括する（配る物と開発の向き）

AtelIer が 6 つのデザイナーを統括する。開発はデザイナーごとのリポジトリで分担するが、CharacterDesigner の開発は AtelIer のためにする
（AtelIer で使われない作り込みは、AtelIer を使う人に届かないため）。AtelIer を使う人は拡張だけを入れ、使う物は AtelIer のタイトルの画面で選ぶ。

配る物は 2 つで、拡張だけの Setup が先、単体の Setup は後に作る。デザイナーごとに Python と PySide6 を持つと、容量がかさみ、同じ物が重なって入るため。

| 配る物 | 中身 | 誰向け |
|---|---|---|
| 拡張だけの Setup | 拡張のコードと、AtelIer の Python に無い依存だけ。AtelIer の Python と PySide6 で動く。小さい | AtelIer を使う人。AtelIer のインストーラーの選べる部品はこちらを入れる |
| 単体の Setup | 自分の Python と PySide6 を持つ | AtelIer を使わない人 |

いま Release（v0.5.38）にある `CharacterDesigner-Setup.exe`（84,670,803 バイト）は、`packaging/chatdraw/build.sh` で Python と PySide6 ごと組んだ単体の物で、拡張だけの物ではない。
AtelIer のインストーラーは名前に `Setup` を含む `.exe` を取るので、今はこの単体の物を入れてしまう。
直し方（私の推測）は、`packaging/character_designer/` で組んだ拡張だけの物を `CharacterDesigner-Extension-Setup.exe` の名前で Release に足し、
AtelIer の `get-extension.ps1` がその名前を先に探す形にすること。詳しくは AtelIer の `docs/knowledge/integration.md` の「拡張の設計」。

### 採用し合う

AtelIer と 6 つのデザイナーは、互いの良い所・使える所（部品、画面、検品、手順、試験、配る仕組み）を採用し合い、同じ物を二度作らない（開発の工数を減らすため）。
共通に使える部品（模型の置き場、言葉の模型、検品、設定の保存、作業ファイル、試験の下ごしらえなど）は AtelIer の側に置き、デザイナーはそれを使う。
逆に、デザイナーで出来た良い物は AtelIer に取り込む。今重なっている物と、どちらを採るかの推奨は、AtelIer の `docs/knowledge/integration.md` の「採用し合う物」。

### タイトルの画面に出す物

AtelIer のタイトルの画面に出す名前・絵・一言は、`extension.json` に持たせる。欄の名前と形は私の推測で、AtelIer の側はまだ読まない
（AtelIer は今 `module`・`attr`・`path` だけを読み、ほかの鍵は飛ばす）。

```json
{"module": "character_designer.extension", "attr": "EXTENSION", "path": ".",
 "title": {"name": "CharacterDesigner", "image": "title.png", "tagline": "（一言）"}}
```

- `title.name`: タイトルの画面に出す名前
- `title.image`: タイトルの画面に出す絵。`extension.json` のあるフォルダーからの道（PNG を私の推測とする）
- `title.tagline`: 名前の下に出す一言

## 今のコードが持っている入口

この表はコードを読んで書いた物で、動かして確かめてはいない。

| 層・入口 | 今 | 根拠 |
|---|---|---|
| 中身の処理 | 一部ある | `character_designer/chara_design.py`・`chara_file.py`・`chara_batch.py` は窓を持たないが、関数の中で `atelier`（`atelier.files.paths`、`atelier.ai`、`atelier.qc`、`atelier.files.project_file`）と `PySide6.QtGui.QImage` を読む。`pyproject.toml` の依存も `atelier` だけ。AtelIer が無いと動かない |
| 入口 1: AtelIer の拡張 | ある | `character_designer/extension.py`（`EXTENSION`、メニューを足す）、`pyproject.toml` の `atelier.extensions` の組、`packaging/character_designer/build.sh` が `extension.json` を書き、`installer.nsi` で置き場に入れる Setup.exe を組む |
| 入口 2: 単体のアプリ | 無い | 自分のウィンドウ（`QMainWindow`）も、単体で起動する入口（`__main__.py`、`project.scripts`）も無い。Setup.exe は AtelIer の拡張として入れる物だけ |
| 入口 3: ほかの AI サービスから使う口 | 無い | MCP のサーバーは無い。`tools/` に `argparse` や `__main__` を持つ開発用の台本（`tools/showcase.py`、`tools/engine/turnaround.py` など）はあるが、中身の処理を呼ぶ口ではない |

足りない物は、中身の処理から `atelier` と `PySide6` を外すこと（AtelIer の部品に頼る所を、中身の側の口に替える）、単体のウィンドウと Setup.exe、MCP のサーバーとコマンドの口の 3 つ。この文書ではコードを変えていない。
