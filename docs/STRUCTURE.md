# 置き場所の決まり

## ひと目で分かる地図

```
CharacterDesigner/
├── README.md / README.en.md   使い方（最初に読む）
├── chatdraw/                  製品のデスクトップアプリ（PySide6。開発はすべてここ）
├── tools/
│   ├── gen/                   描く・検品する・学ぶ道具（イラストの本体）
│   ├── engine/                Blender・MakeHuman の人形と下絵
│   └── *.py                   箱庭ドットの道具（build・check・render など）と、整理の道具（library_check・test_audit）
├── styles/                    数字の決まり（作風・頭身・描く前の決まり baseline・宗教文化 cultural・設定画 settei）
├── casts/                     描く題材の一覧（作品の登場人物、ポーズ、体型、ファッションの札）
├── bible/                     設定資料集（人物 characters/・世界観 worlds/）と、その人物の通った絵
├── designs/<作品>/            依頼された作品の決まりと決定稿
├── characters/                箱庭ドットの職業の部品（イラストの人物は bible/）
├── library/                   絵の資産（目録は library/INDEX.md）
│   ├── feedback/<題目>/<日付>/<組>/  利用者に見せた成果物（1 枚ずつ、組ごとの README 付き）
│   ├── samples/<題目>/          見本の絵（people・demi・fashion・handdraw・studio・lineart・imgproc・bible）
│   ├── progress/<日付>/         比べた記録の絵
│   ├── daily/<日付>/            日ごとの作例
│   ├── book/ eyes/ sheets/      作例集・目の資料集・職業の一覧
├── docs/                      案内（ROADMAP・STRUCTURE・references など）
│   ├── knowledge/             分かったこと・決めたこと（decisions.md は 1 か所だけ）
│   ├── reports/               日報・週報・判断待ち（pending.md）・成果物の表（deliverables.md）
│   └── images/                README の画面の絵
├── config/                    利用者ごとの設定の見本
└── tests/                     試験
```

絵がどこに何枚あるかは [library/INDEX.md](../library/INDEX.md)（縮小画つき）。

どのセッションも、資料はこの表の置き場にだけ置く。表に無い種類のものを作るときは、先にこの表へ行を足す。
同じ種類のものを 2 か所に置かない（どちらが新しいか分からなくなり、片方だけ直されて食い違った）。

| 置き場 | 置くもの | 置かないもの |
|---|---|---|
| `chatdraw/` `tools/` `packaging/` `templates/` | 道具（プログラム、アプリ、配布物の作り方、ほかのリポジトリへ配るひな型） | 絵、知見の文章 |
| `chatdraw/icon/` | アプリのアイコンの絵（app.png は PC 用で窓とインストーラーの .ico の元、mobile.png はスマホ・タブレット用） | アイコン以外の絵 |
| `styles/` | 道具が読む数字の決まり（作風、ジャンルの頭身、学んだ基準、模型の癖） | 文章の説明（それは `docs/knowledge/`） |
| `config/` | 利用者ごとの設定の見本（`*.example.json`）と既定 | 利用者の実際の設定（git に入れない） |
| `config/poses/` | 道具が読む姿勢の既定（立体の人形から起こした姿勢の絵） | 描いた絵や比べ図（それは `library/`） |
| `bible/` | 設定資料集（人物 `characters/`、世界観 `worlds/`）と、その人物の通った絵 | ほかの人物の比べ図 |
| `casts/` | 描く題材の一覧（作品ごとの登場人物、言葉の札、体の設計図、ポーズ、体型、描き分けのパターン） | 絵 |
| `characters/` | 箱庭ドットの職業の部品（`parts.json`、`sprite.json`） | イラストの人物（それは `bible/`） |
| `designs/<作品>/` | 依頼された作品のデザインの決まり（`README.md`）と決定稿の絵 | 道具の知見 |
| `library/` | 見本の絵（`samples/<題目>/`。題目は people・demi・fashion・handdraw・studio・lineart・imgproc・bible）、作例集（`book/`）、比べた絵の記録（`progress/<日付>/`）、職業の一覧の絵（`sheets/`）、日ごとの作例（`daily/<日付>/`）、フィードバックの成果物（`feedback/<題目>/<日付>/<組>/` に 1 枚ずつと組ごとの README）。目録は `INDEX.md`（`tools/library_check.py` が書く） | 参考にした作品の画像（置かない。出典だけを `docs/references.md` に） |
| `docs/` 直下 | 使う人向けの案内（README から辿る文書、`ROADMAP.md`、`STRUCTURE.md`、`models.md`、`references.md`、`record-policy.md`、`release-plan.md`、`third-party.md`） | 研究のメモ |
| `docs/knowledge/` | 分かったこと（描かせ方、検品、解剖、作画の決まり）と、決めたこと（`decisions.md`、1 か所だけ） | 絵 |
| `docs/knowledge/learning/` | 学習の記録（self-learn） | |
| `docs/knowledge/fashion/` | 流行のファッション資料（10代〜20代を中心に、系統・季節ごとの服・髪・小物・色と出典。入口は `README.md`）。世界の服装の図鑑は `zukan/`（古代〜現在と伝統衣装。図鑑の人物の設定は `casts/fashion-zukan/characters/`）。描く言葉の札は `casts/fashion.json`、見本の絵は `library/samples/fashion/` | 実在ブランドの写真や他人の画像（言葉と数字と出典だけ） |
| `docs/reports/` | 日報・週報・月報、確かめたいことの一覧（`pending.md`）、成果物の表（`deliverables.md`） | |
| `docs/images/` | README とアプリの案内の画面の絵 | 作例（それは `library/`） |
| `tests/` `tests/fixtures/` | 試験と、試験・精度の測定に使う小さな正解の記録 | 大きな絵（作業場所に置き、記録には道だけ書く） |
| `.worklog/` | 作業中の試行錯誤（git に入れない） | |

利用者に見せた成果物は、作業場所に置いたままにせず `library/feedback/<題目>/<日付>/<組>/<組>-<姿勢か番号>-s<種>.jpg` に 1 枚ずつ残し、組ごとの `README.md` に絵ごとの判定・描かせた言葉・種・残っている崩れを書く。一覧図にまとめない（絵ごとの判定と崩れが書けず、元の大きさで見られない）。設定画は頁ごとに種が違うので `-s<種>` を付けない。決まりは `tools/library_check.py` が見る。作業中の絵（描かせた候補、見せていない絵）は git に入れず、作業場所（scratchpad）に置く。残すのは、見本や比べの記録として選んだ絵だけ。

絵を足したら `python3 tools/library_check.py` を流す。置き方の決まりに外れた絵と壊れた参照があれば止まり、目録 `library/INDEX.md` を書き直す（`tests/test_structure.py` も同じ検査を流す）。
