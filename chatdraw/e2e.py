"""入れた版が Windows の上で最後まで動くかを通しで確かめる（GitHub Actions の Windows の機械で流す）。

    python -E -s -m chatdraw.e2e <出力の置き場>

利用者が踏む順に、本物の経路を通す。
1. ウィンドウを開き、画面の中に収まっているか
2. 初回の取得（Fetcher.run）で、描く部品（CPU 版の torch など）を ProgramData に入れ、絵の模型とラフの部品を取る
3. 取った模型で 1 枚描き、絵が保存されるか
4. ラフから描く部品が取れているか
5. 検品の部品（部位分け・人の枠・タグ・体の点・手・足）が初回の取得で入ったか（chatdraw/qcparts.py）

模型は数 GB あるので、形が同じで小さい試験用の SDXL（hf-internal-testing/tiny-stable-diffusion-xl-pipe）を使う。絵の出来は見ない。
結果は report.json に書き、1 つでも落ちたら終了コード 1 で終わる。
"""
from __future__ import annotations

import faulthandler
import json
import os
import sys
import time
import traceback
from pathlib import Path

TINY = "hf-internal-testing/tiny-stable-diffusion-xl-pipe"


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "e2e-out")
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    faulthandler.enable()
    report: dict = {"steps": []}

    def save_report():
        tmp = out / "report.json.tmp"
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out / "report.json")

    def step(name, fn):
        t = time.time()
        print(f"START {name}", flush=True)
        try:
            detail = fn()
            report["steps"].append({"name": name, "ok": True, "seconds": round(time.time() - t, 1), "detail": detail})
            save_report()
            print(f"OK   {name}（{time.time() - t:.0f} 秒）{detail or ''}", flush=True)
            return True
        except Exception:
            error_text = traceback.format_exc()[-3000:]
            report["steps"].append({"name": name, "ok": False, "seconds": round(time.time() - t, 1),
                                    "error": error_text})
            print(f"FAIL {name}\\n{error_text}", flush=True)
            try:
                save_report()
            except Exception:
                print(f"FAIL report.json の保存\\n{traceback.format_exc()[-3000:]}", flush=True)
            return False

    import chatdraw.app as app   # 起動と同じ順に読む（出力の付け替え、環境の切り離し、部品の置き場）
    from PySide6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication([])
    app.dark(qapp)
    from chatdraw import fit
    fit.install(qapp)
    from chatdraw import models
    from chatdraw.models import FILES, ImageModel
    tiny = ImageModel(TINY, "試験用の小さな SDXL", "", "", 0.1, 2, 5.0, files=FILES["bin"], family="sdxl", score=0)
    models.IMAGES = models.IMAGES + (tiny,)

    def window():
        w = app.Window()
        w.show()
        for _ in range(20):
            qapp.processEvents()
            time.sleep(0.05)
        area = w.screen().availableGeometry()
        w.grab().save(str(out / "window.png"))
        return {"frame": list(w.frameGeometry().getRect()), "screen": list(area.getRect())}

    def fetch():
        from chatdraw.setup import Fetcher
        f = Fetcher()
        said, done = [], []
        f.progress.connect(lambda msg, pct: said.append(msg))
        f.finished.connect(lambda err: done.append(err))
        f.run(tiny, None)
        if done and done[0]:
            raise RuntimeError(done[0])
        return {"messages": said[-5:]}

    shot = {}

    def draw():
        from chatdraw.engine import Painter, Studio, Words
        studio = Studio(Words(Path("")), Painter(TINY, steps=2, size=(256, 256)), out)
        prompt, path = studio.draw("1girl, adult woman, bikini", 1, size=(256, 256))
        shot["path"] = path
        if not Path(path).exists():
            raise RuntimeError(f"絵が保存されていない: {path}")
        return {"file": str(path), "prompt": prompt}

    def rough_parts():
        # 試験用の小さな模型は本物と形が違い、ラフの部品（本物の SDXL 用）と組めないので、取れて読めるかだけを見る
        from chatdraw.engine import Painter
        if not Painter(TINY).sketch_ready():
            raise RuntimeError("ラフの部品が手元に無い")
        return {}

    ok = step("ウィンドウを開く", window)
    ok = step("描く部品と模型を取る", fetch) and ok
    ok = step("1 枚描く", draw) and ok
    ok = step("ラフの部品がそろう", rough_parts) and ok

    def qc_parts():
        # 初回の取得（Fetcher.run）が検品の部品も取ったかを、取らずに置き場だけで見る
        from chatdraw import qcparts
        lack = [p.name for p in qcparts.missing()]
        if lack:
            raise RuntimeError("検品の部品が入っていない: " + "、".join(lack))
        return {"parts": [p.key for p in qcparts.PARTS]}

    ok = step("検品の部品がそろう", qc_parts) and ok

    def right_click():
        # 右クリックのメニューを、下のメニューまで全部開いて閉じる（0.5.30 で右クリックからアプリごと落ちた）
        from PySide6.QtCore import QEventLoop, QPoint
        w = app.Window()
        w.show()
        if shot.get("path"):
            w.place(str(shot["path"]))
        seen = []

        def walk(m, depth=0, visited=None):
            # popup() 自身が aboutToShow を発火する。手動で emit すると、
            # 同じ fill が二重に走る。マウス入力も処理するとカーソル位置の項目から
            # サブメニューが自動で連鎖表示されるため、検査中はユーザー入力を除外する。
            if visited is None:
                visited = set()
            if depth > 12 or len(visited) > 120:
                raise RuntimeError("右クリックのメニューが循環しています")
            # id(m) は Python ラッパーの寿命に依存する。QObject 自体で重複を判定する。
            if m in visited:
                return
            visited.add(m)
            title = m.title()
            started = time.monotonic()
            print(f"MENU OPEN depth={depth} title={title!r} actions={len(m.actions())}", flush=True)
            m.popup(QPoint(20, 20))
            qapp.processEvents(QEventLoop.ExcludeUserInputEvents)
            for a in list(m.actions()):
                seen.append(a.text())
                sub = a.menu()
                if sub is not None:
                    walk(sub, depth + 1, visited)
            m.hide()
            qapp.processEvents(QEventLoop.ExcludeUserInputEvents)
            elapsed = time.monotonic() - started
            print(f"MENU CLOSE depth={depth} title={title!r} seconds={elapsed:.2f}", flush=True)
            if elapsed > 15:
                raise RuntimeError(f"右クリックメニューの表示に時間がかかりすぎています: {title!r} ({elapsed:.1f}s)")
        for _ in range(3):
            m = w.build_canvas_menu(QPoint(20, 20))
            walk(m)
            m.deleteLater()
            qapp.processEvents()
        w.close()
        qapp.processEvents()
        return {"items": len(seen)}

    def phases_draw():
        # 工程に分けて描く。最後の工程まで描けて、絵が保存されることを見る（0.5.30 で 1 工程目のあとに落ちた）
        from chatdraw.engine import Painter, Studio, Words
        studio = Studio(Words(Path("")), Painter(TINY, steps=2, size=(256, 256)), out)
        studio.way = "phases"
        _prompt, path = studio.draw("1girl, red hair", 2, size=(256, 256))
        if not Path(path).exists():
            raise RuntimeError(f"絵が保存されていない: {path}")
        return {"phases": len(studio.last_phases or [])}

    ok = step("右クリックのメニューを全部開く", right_click) and ok
    ok = step("工程に分けて 1 枚描く", phases_draw) and ok
    from chatdraw.paths import HOME, HUB
    report["data_home"], report["hub"] = str(HOME), str(HUB)
    report["ok"] = ok
    save_report()
    print(f"exit={0 if ok else 1}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
