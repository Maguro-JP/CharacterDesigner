---
name: character-designer-app
description: CharacterDesigner のアプリを作る・直すとき。起動（app/launch.py、app/start.sh、Setup.exe）、画面（app/web）、サーバー（app/server）、README の使い方に触るとき、新しい機能の入口を決めるとき、「アプリにして」「ブラウザじゃなくて」「ウィンドウで開いて」と言われたときに使う。CharacterDesigner はデスクトップアプリで、起動するとブラウザではなくアプリのウィンドウが開き、ユーザーが触る機能は全部画面にある。描かせ方の決まりは character-design、一般の決まりは desktop-app。
---

# CharacterDesigner はデスクトップアプリ

ユーザーが決めたこと（2026-10-24）。CharacterDesigner はデスクトップアプリとして作る。
起動するとブラウザではなくアプリのウィンドウが開き、ユーザーが触る機能は全部その画面にある。
開発は CLI ではなく GUI で行う。この決まりに反する案は出さず、言われた形で作る。一般の決まりは `desktop-app`。

## 今の形と、直す先

| 今 | 直す先 |
|---|---|
| `app/launch.py` の `serve()` が uvicorn を起こし、`open_when_ready()` が `webbrowser.open(url)` でブラウザを開く | サーバーは裏のスレッドで起こし、応答が返ったら pywebview のウィンドウで `http://127.0.0.1:<PORT>/` を開く。ウィンドウが閉じたらサーバーと言葉の模型（LLM）を止める |
| `--no-browser` | `--no-window`（サーバーだけ動かす。開発と MCP 用） |
| README の使い方「準備ができるとブラウザーで `http://127.0.0.1:8000/` が開く」「表示された URL を開く」 | 「CharacterDesigner のウィンドウが開く」。URL は書かない |
| Setup.exe は Python の埋め込み版とサーバーの部品を入れる | pywebview の wheel も入れる。WebView2 が無ければ Evergreen Bootstrapper を入れるか、起動時に案内を出す |
| 初回の設定（setupgui）と取得の進みは画面に出る | そのまま。ターミナルの文は開発者向けの記録に留める |

2026-10-24 に `app/launch.py`（pywebview のウィンドウ、`--no-window`）、`app/start.sh`、`packaging/windows/build.sh`（Windows 用の部品）、README を直した。
手元の Windows でウィンドウが開くことは、まだ見ていない（成果物の表の状態は確認待ち）。

## 入口の決まり

- 起動は3つだけ。デスクトップのアイコン（Setup.exe が置く）、`sh app/start.sh`、`python3 app/launch.py`。どれもウィンドウが開く
- サーバーの URL とポートは、ログと開発者向けの説明にだけ書く。ユーザー向けの文に `http://` を書かない
- 新しい機能は `app/web` の画面に置き、`app/server` の API で `tools/` のエンジンを呼ぶ。`tools/*.py` に人向けの入口を増やさない。
  既にある `tools/*.py` のコマンドは開発と検証のツールとして残し、README の使い方の先頭に置かない
- MCP サーバー（`app/mcp`）は Claude 向けの入口で、ユーザー向けの画面の代わりにはしない

## 完成条件（docs/reports/deliverables.md の先頭の行）

- `sh app/start.sh` から起動すると、ブラウザではなく CharacterDesigner のウィンドウが開き、スタジオの画面が表示される
- Windows の Setup.exe から入れてデスクトップのアイコンを開いても同じ
- `grep -rn "webbrowser" app/` が 0 件。README.md と README.en.md の使い方に `http://` を開く手順が無い
- `--no-window` でサーバーだけ動かせる（MCP と開発用）

確かめ方は `verify-before-done`。ウィンドウが開く様子は、起動のログ（pywebview のウィンドウ作成の行）か画面の撮影で示す。
表示の無い環境（CI、コンテナ）では `--no-window` の経路だけをテストし、ウィンドウの確認は手元で行ったことを書く。

## 他のスキルとの関係

- 描かせ方と検品の決まり: `character-design` <!-- ja-proofread: ignore -->
- アプリ一般の決まり（包み方の選び方、配布）: `desktop-app`
- 成果物を1つずつ完成させる: `finish-first`
- ユーザーの決めたことに反抗しない: `follow-instructions`
