# AtelIer の拡張・単体のアプリ・ほかの AI サービスから使う口

CharacterDesigner は AtelIer のために設計するが、単体のアプリとしても動き、ほかの AI サービスからも使えるように設計する。
使われ方ごとに中身を作り分けると同じ処理が何か所にも分かれて直し漏れが出るので、中身は 1 つにして入口だけを分ける。

## 決まり

| 層 | 中身 |
|---|---|
| 中身の処理 | UI に頼らない部品（Python の関数・クラス）。窓・メニュー・AtelIer を読み込まない |
| 入口 1: AtelIer の拡張 | `extension.json` とメニュー。拡張の置き場（`C:\ProgramData\AtelIer\extensions\character_designer\`）に置かれ、AtelIer が読み込む |
| 入口 2: 単体のアプリ | 自分のウィンドウと Setup.exe。AtelIer が無くても起動する |
| 入口 3: ほかの AI サービスから使う口 | MCP のサーバーと、コマンドで呼べる口。中身の処理をそのまま呼ぶ |

- 置き場と設定は、どの入口から使っても同じにする。入口ごとに置き場を持つと、同じ人の設定や作った物が入口ごとに分かれるため
- 言葉の模型は共通の置き場 `C:\LLM` に置く
- AtelIer が無くても動き、AtelIer があれば拡張として載る
- 次は私の推測: ほかの AI サービスから使う口は MCP のサーバー（標準入出力で話す形）にし、コマンドの口は `python -m character_designer <操作>` で JSON を返す形にして、2 つが同じ操作の一覧を使う。単体のアプリの Setup.exe は自分の Python を持ち、AtelIer の拡張として入れるときだけ AtelIer の Python で動かす

AtelIer の側の決まりは、AtelIer の `docs/knowledge/integration.md` の「拡張の設計」と「インストーラーどうしの連携」。

## 今のコードが持っている入口

この表はコードを読んで書いた物で、動かして確かめてはいない。

| 層・入口 | 今 | 根拠 |
|---|---|---|
| 中身の処理 | 一部ある | `character_designer/chara_design.py`・`chara_file.py`・`chara_batch.py` は窓を持たないが、関数の中で `atelier`（`atelier.files.paths`、`atelier.ai`、`atelier.qc`、`atelier.files.project_file`）と `PySide6.QtGui.QImage` を読む。`pyproject.toml` の依存も `atelier` だけ。AtelIer が無いと動かない |
| 入口 1: AtelIer の拡張 | ある | `character_designer/extension.py`（`EXTENSION`、メニューを足す）、`pyproject.toml` の `atelier.extensions` の組、`packaging/character_designer/build.sh` が `extension.json` を書き、`installer.nsi` で置き場に入れる Setup.exe を組む |
| 入口 2: 単体のアプリ | 無い | 自分のウィンドウ（`QMainWindow`）も、単体で起動する入口（`__main__.py`、`project.scripts`）も無い。Setup.exe は AtelIer の拡張として入れる物だけ |
| 入口 3: ほかの AI サービスから使う口 | 無い | MCP のサーバーは無い。`tools/` に `argparse` や `__main__` を持つ開発用の台本（`tools/showcase.py`、`tools/engine/turnaround.py` など）はあるが、中身の処理を呼ぶ口ではない |

足りない物は、中身の処理から `atelier` と `PySide6` を外すこと（AtelIer の部品に頼る所を、中身の側の口に替える）、単体のウィンドウと Setup.exe、MCP のサーバーとコマンドの口の 3 つ。この文書ではコードを変えていない。
