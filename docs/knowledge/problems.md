# 問題

## 2026-09-29 描画器の初版で剣が消えた

- 起きたこと: 2ドット幅の剣身が、縮小後に輪郭色だけになり、暗い背景で見えなくなった
- 原因: 透明に接するドットを輪郭色に塗り替えていた。幅2の部品は全部が外周になる
- 解決: 輪郭を形の外側に1ドット足す方式に変えた
- 再発防止: `tests/test_build.py` の `test_thin_part_keeps_its_inside`

## 2026-09-29 参考サイトに届かない

- `www.spriters-resource.com` `www.cgworld.jp` 公式サイトがプロキシで 403。`docs/reports/pending.md` の1
