# アプリのアイコンを作る道具

- draw_girl.py: 顔の絵を Animagine XL 4.0 で描く（`python3 draw_girl.py <種>...`、出力 girl-s<種>.png）。fp32 では 14GB を超えて落ちたので bfloat16 で読む
- app_icon.py: 顔の絵にペンタブのペンと CD を重ね、角の丸い四角に切る（icon2-a.png、icon2-b.png）
- profile_icon.py: 図形で組んだ横顔の試作（戻した）

記録と絵は library/feedback/icon/2026-11-02/。
