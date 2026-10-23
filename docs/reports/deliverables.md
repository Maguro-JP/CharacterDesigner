# 成果物

1つずつ完成させる。上から順に、状態が完成でない最初の行が「今の成果物」。
完成条件は、動かして確かめられる文で書く。状態は 未着手・進行中・確認待ち・完成 の4つ。
書き方は `.claude/skills/finish-first/SKILL.md`。

| # | 成果物 | 完成条件 | 状態 | 残り | 更新 |
|---|---|---|---|---|---|
| 1 | アプリのウィンドウで起動する CharacterDesigner | `sh app/start.sh` と Setup.exe から起動すると、ブラウザではなく CharacterDesigner のウィンドウが開いてスタジオが表示される。`grep -rn webbrowser app/` が 0 件で、README の使い方に `http://` を開く手順が無い。`--no-window` でサーバーだけ動く | 未着手 | `app/launch.py` を pywebview のウィンドウにする（`.claude/skills/character-designer-app/SKILL.md` の表の順） | 2026-10-24 |
| 2 | 仕事の進み具合の表示（docs/app/PLAN.md の M2 の残り） | 描いている間、画面に経過した分と何回目かが出る（仮） | 未着手 | 1 が完成してから | 2026-10-24 |
