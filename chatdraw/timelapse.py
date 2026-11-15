"""タイムラプス（描いた過程の記録）と、その再生・GIF への書き出し。

線を 1 本引くたび、AI の絵を置くたび、AI が描いている途中の工程ごとに、キャンバスの写しを撮る。
写しは縮めてメモリに持ち（1 枚 長い辺 640 画素、最大 1200 枚。超えたら半分に間引く）、同じ写しは足さない。
「タイムラプスを見る」で、アプリの中で再生でき、そのまま GIF か動画（MP4）に書き出せる。
書き出した GIF・動画は「開く」でアプリの中で見られる（外のプレーヤーを探させない）。
動画（MP4）は imageio-ffmpeg、無ければ PATH の ffmpeg で書く。どちらも無い環境では、動く WebP（.webp）を動画の代わりに書く
（Pillow だけで書け、ブラウザと多くの画像ビューアで動く）。

AI が一発で描いた絵は、線を引く過程が無いので記録が 1 枚になり、タイムラプスにならなかった。そこで次の順で過程を作る:
1. 工程に分けて描いたとき（add_phases）は、各工程の絵を順につなぐ
2. 1 回で描いたときは、拡散の途中の絵（on_preview）を順につなぐ
3. どちらも無いときは、仕上がった絵から 線画 → 塗り → 仕上げ の順に逆算して作る（reconstruct）
人が引いた線は、これまでどおり 1 本ごとに写しを撮る。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout)

MAX_SIDE, MAX_FRAMES = 640, 1200


class Recorder:
    def __init__(self):
        self.frames: list[Image.Image] = []
        self.enabled = True
        self._job_start: int | None = None   # AI が描き始めたときの枚数（途中の絵が届いたかを見る）

    def begin_job(self):
        """AI が描き始めた。描き終えた所（end_job）で、途中の絵が 1 枚も届いていなければ逆算して足す"""
        self._job_start = len(self.frames)

    def add_phases(self, images):
        """工程に分けて描いた絵（下絵、線画、塗り、仕上げなど）を順に足す"""
        for im in images:
            self.add(im)

    def end_job(self, final: Image.Image, before: Image.Image | None = None) -> str:
        """AI の絵が仕上がった。途中の絵が 2 枚以上届いていればそのまま、足りなければ逆算した工程を足す。
        返りは使った作り方（"preview" か "reconstruct"、記録しないときは ""）"""
        start, self._job_start = self._job_start, None
        if not self.enabled:
            return ""
        got = len(self.frames) - (start if start is not None else len(self.frames))
        if got >= 2:
            self.add(final)
            return "preview"
        self.add_phases(reconstruct(final, before))
        return "reconstruct"

    def add(self, img: Image.Image):
        if not self.enabled:
            return
        im = img.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        if self.frames and self.frames[-1].size == im.size and self.frames[-1].tobytes() == im.tobytes():
            return   # 何も変わっていない写しは足さない
        self.frames.append(im)
        if len(self.frames) > MAX_FRAMES:
            self.frames = self.frames[::2]

    def clear(self):
        self.frames.clear()

    def export(self, path: str | Path, seconds: float = 15.0) -> int:
        """全体が seconds 秒ほどになる GIF に書き出す。書いた枚数を返す"""
        if not self.frames:
            return 0
        step = max(1, len(self.frames) // 600)   # 600 枚を超える分は間引く
        frames = self.frames[::step]
        if frames[-1] is not self.frames[-1]:
            frames.append(self.frames[-1])
        size = frames[-1].size
        frames = [f if f.size == size else f.resize(size) for f in frames]
        per = max(20, int(seconds * 1000 / len(frames)))
        durations = [per] * (len(frames) - 1) + [2000]   # 最後の絵で 2 秒止める
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
        return len(frames)

    def export_video(self, path: str | Path, seconds: float = 15.0) -> tuple[int, Path]:
        """動画に書き出す。返りは (書いた枚数, 書いた先)。MP4 を書けない環境では、同じ名前の .webp（動く WebP）に書く"""
        path = Path(path)
        if not self.frames:
            return 0, path
        size = self.frames[-1].size
        w, h = size[0] // 2 * 2, size[1] // 2 * 2   # H.264 は偶数の大きさしか受けない
        fps = max(1, min(30, round(len(self.frames) / seconds)))
        frames = [f if f.size == (w, h) else f.resize((w, h)) for f in self.frames]
        frames += [frames[-1]] * (fps * 2)   # 最後の絵で 2 秒止める
        how = video_backend()
        if how == "imageio":
            import imageio_ffmpeg
            writer = imageio_ffmpeg.write_frames(str(path), (w, h), fps=fps, macro_block_size=1)
            writer.send(None)
            for f in frames:
                writer.send(f.tobytes())
            writer.close()
            return len(frames), path
        if how == "ffmpeg":
            import shutil
            import subprocess
            cmd = [shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                   "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = p.communicate(b"".join(f.tobytes() for f in frames))
            if p.returncode == 0:
                return len(frames), path
        # MP4 を書く部品が無い（または ffmpeg が失敗した）。Pillow だけで書ける動く WebP にする
        dst = path.with_suffix(".webp")
        frames[0].save(dst, save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0, quality=80)
        return len(frames), dst


def video_backend() -> str:
    """MP4 を書く手段: "imageio"（imageio-ffmpeg）、"ffmpeg"（PATH の ffmpeg）、"webp"（どちらも無い。動く WebP で代わりに書く）"""
    try:
        import imageio_ffmpeg  # noqa: F401
        return "imageio"
    except ImportError:
        import shutil
        return "ffmpeg" if shutil.which("ffmpeg") else "webp"


def video_available() -> bool:
    """MP4 そのものを書けるか（書けないときも、動く WebP で書き出せる）"""
    return video_backend() != "webp"


RECON_LINE, RECON_FLAT, RECON_FINISH = 6, 6, 6   # 逆算の各段の枚数


def reconstruct(final: Image.Image, before: Image.Image | None = None) -> list[Image.Image]:
    """仕上がった絵から、描いた順（線画 → 塗り → 仕上げ）を逆算した工程の絵を作る。
    線画は明るさの輪郭（暗く細い所）を、上から下へ描き進める形で出す。塗りは色を大きく均した平塗りを線画の下に広げ、
    仕上げは平塗りから仕上がった絵へ少しずつ移す。最後の 1 枚は仕上がった絵そのもの。before（描く前の絵）があれば下地にする"""
    from PIL import ImageChops, ImageFilter
    im = final.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    w, h = im.size
    paper = Image.new("RGB", (w, h), "white")
    if before is not None:
        paper = before.convert("RGB").resize((w, h))
    gray = im.convert("L")
    # 線: 周りより暗い所（明るさの谷）。輪郭の検出だけだと塗りの境目まで線になったので、暗さの差で取る
    dark = ImageChops.subtract(gray.filter(ImageFilter.MaxFilter(5)), gray)
    line = dark.point(lambda v: 0 if v > 28 else 255).filter(ImageFilter.MinFilter(1))
    line_rgb = Image.merge("RGB", (line, line, line))
    ink = ImageChops.multiply(paper, line_rgb)
    flat = im.filter(ImageFilter.ModeFilter(7)).filter(ImageFilter.MedianFilter(5))
    flat = ImageChops.multiply(flat, line_rgb)
    out = []
    for i in range(1, RECON_LINE + 1):   # 線画を上から下へ描き進める
        cut = int(h * i / RECON_LINE)
        f = paper.copy()
        f.paste(ink.crop((0, 0, w, cut)), (0, 0))
        out.append(f)
    for i in range(1, RECON_FLAT + 1):   # 塗りを上から下へ広げる
        cut = int(h * i / RECON_FLAT)
        f = ink.copy()
        f.paste(flat.crop((0, 0, w, cut)), (0, 0))
        out.append(f)
    for i in range(1, RECON_FINISH + 1):   # 平塗りから仕上がった絵へ
        out.append(Image.blend(flat, im, i / RECON_FINISH))
    out[-1] = im
    return out


class PlayerDialog(QDialog):
    """書き出した GIF・動画をアプリの中で見る。GIF は QMovie、動画は QtMultimedia で再生する"""

    def __init__(self, path: str | Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(Path(path).name)
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        self.path, self.movie, self.player = Path(path), None, None
        if self.path.suffix.lower() == ".gif":
            from PySide6.QtGui import QMovie
            self.view = QLabel(alignment=Qt.AlignCenter)
            self.movie = QMovie(str(self.path))
            self.view.setMovie(self.movie)
            self.movie.start()
        else:
            from PySide6.QtMultimedia import QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
            from PySide6.QtCore import QUrl
            self.view = QVideoWidget()
            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.view)
            self.player.setSource(QUrl.fromLocalFile(str(self.path)))
            self.player.setLoops(QMediaPlayer.Infinite)
            self.player.play()
        self.view.setMinimumSize(320, 320)
        lay.addWidget(self.view, 1)
        self.resize(560, 600)


def open_player(parent, start: Path | None = None):
    """GIF・動画を選んで、アプリの中で見る"""
    src, _ = QFileDialog.getOpenFileName(parent, "GIF・動画を開く", str(start or Path.home()), "GIF・動画 (*.gif *.mp4)")
    if src:
        PlayerDialog(src, parent).show()


def _qpix(im: Image.Image) -> QPixmap:
    data = im.convert("RGBA").tobytes("raw", "RGBA")
    q = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


class TimelapseDialog(QDialog):
    """記録したタイムラプスを再生する。帯で好きな所へ動かせ、GIF に書き出せる"""

    def __init__(self, recorder: Recorder, parent=None, out_dir: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("タイムラプス")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.rec, self.out_dir = recorder, out_dir
        lay = QVBoxLayout(self)
        self.view = QLabel(alignment=Qt.AlignCenter)
        self.view.setMinimumSize(320, 320)
        lay.addWidget(self.view, 1)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(0, len(recorder.frames) - 1))
        self.slider.valueChanged.connect(self.show_frame)
        lay.addWidget(self.slider)
        row = QHBoxLayout()
        self.play = QPushButton("再生")
        self.play.setToolTip("最初から再生する（もう一度押すと止める）")
        self.play.clicked.connect(self.toggle)
        save = QPushButton("GIF に書き出す")
        save.setToolTip("描いた過程を GIF に書き出す（約 15 秒）")
        save.clicked.connect(self.save)
        self.video = QPushButton("動画に書き出す")
        self.video.clicked.connect(self.save_video)
        if video_available():
            self.video.setToolTip("描いた過程を動画（MP4、約 15 秒）に書き出す")
        else:   # 前は押せなかった。MP4 を書く部品が無くても、動く WebP で書き出す
            self.video.setToolTip("この環境には MP4 を書く部品（ffmpeg）が無いので、動く WebP（.webp）で書き出します")
        see = QPushButton("開く")
        see.setToolTip("書き出した GIF・動画をアプリの中で見る")
        see.clicked.connect(lambda: open_player(self, self.out_dir))
        self.count = QLabel(f"{len(recorder.frames)} 枚")
        if not recorder.frames:   # 記録が無いと、押しても何も起きなかった。押せない形にして、記録の仕方をツールチップに出す
            why = "まだ記録がありません。「表示」→「タイムラプスを記録する」を入れて、線を引くか AI で描くと記録されます"
            for b in (self.play, save, self.video):
                b.setEnabled(False)
                b.setToolTip(why)
        row.addWidget(self.play)
        row.addWidget(save)
        row.addWidget(self.video)
        row.addWidget(see)
        row.addStretch()
        row.addWidget(self.count)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(max(30, 15000 // max(1, len(recorder.frames))))
        self.timer.timeout.connect(self._next)
        self.resize(560, 640)
        self.show_frame(0)

    def show_frame(self, i: int):
        if not self.rec.frames:
            self.view.setText("まだ記録がありません。線を引くか AI で描くと記録されます")
            return
        pix = _qpix(self.rec.frames[min(i, len(self.rec.frames) - 1)])
        self.view.setPixmap(pix.scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def toggle(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText("再生")
        elif self.rec.frames:
            if self.slider.value() >= self.slider.maximum():
                self.slider.setValue(0)
            self.timer.start()
            self.play.setText("止める")

    def _next(self):
        if self.slider.value() >= self.slider.maximum():
            self.toggle()
            return
        self.slider.setValue(self.slider.value() + 1)

    def save(self):
        if not self.rec.frames:
            return
        start = str((self.out_dir or Path.home()) / "timelapse.gif")
        dst, _ = QFileDialog.getSaveFileName(self, "タイムラプスを書き出す", start, "GIF (*.gif)")
        if dst:
            n = self.rec.export(dst)
            self.count.setText(f"{n} 枚を書き出しました")

    def save_video(self):
        if not self.rec.frames:
            return
        start = str((self.out_dir or Path.home()) / "timelapse.mp4")
        dst, _ = QFileDialog.getSaveFileName(self, "タイムラプスを動画に書き出す", start, "MP4 (*.mp4)")
        if dst:
            n, out = self.rec.export_video(dst)
            self.count.setText(f"{n} 枚を {out.name} に書き出しました")
