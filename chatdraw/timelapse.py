"""タイムラプス（描いた過程の記録）と、その再生・GIF への書き出し。

線を 1 本引くたび、AI の絵を置くたび、AI が描いている途中の工程ごとに、キャンバスの写しを撮る。
写しは縮めてメモリに持ち（1 枚 長い辺 640 画素、最大 1200 枚。超えたら半分に間引く）、同じ写しは足さない。
「タイムラプスを見る」で、アプリの中で再生でき、そのまま GIF か動画（MP4）に書き出せる。
書き出した GIF・動画は「開く」でアプリの中で見られる（外のプレーヤーを探させない）。
動画の書き出しは imageio-ffmpeg が要る。数十 MB あるのでアプリに同梱せず、入っているときだけ使う。
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

    def export_video(self, path: str | Path, seconds: float = 15.0) -> int:
        """MP4 に書き出す。書いた枚数を返す。imageio-ffmpeg が無ければ RuntimeError"""
        if not self.frames:
            return 0
        if not video_available():
            raise RuntimeError("動画の書き出しには imageio-ffmpeg が要ります（pip install imageio-ffmpeg）")
        import imageio_ffmpeg
        size = self.frames[-1].size
        w, h = size[0] // 2 * 2, size[1] // 2 * 2   # H.264 は偶数の大きさしか受けない
        fps = max(1, min(30, round(len(self.frames) / seconds)))
        tail = [self.frames[-1]] * (fps * 2)   # 最後の絵で 2 秒止める
        writer = imageio_ffmpeg.write_frames(str(path), (w, h), fps=fps, macro_block_size=1)
        writer.send(None)
        n = 0
        for f in self.frames + tail:
            writer.send((f if f.size == (w, h) else f.resize((w, h))).tobytes())
            n += 1
        writer.close()
        return n


def video_available() -> bool:
    try:
        import imageio_ffmpeg  # noqa: F401
        return True
    except ImportError:
        return False


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
        else:
            self.video.setEnabled(False)
            self.video.setToolTip("動画の書き出しには imageio-ffmpeg が要ります（同梱していません）")
        see = QPushButton("開く")
        see.setToolTip("書き出した GIF・動画をアプリの中で見る")
        see.clicked.connect(lambda: open_player(self, self.out_dir))
        self.count = QLabel(f"{len(recorder.frames)} 枚")
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
            n = self.rec.export_video(dst)
            self.count.setText(f"{n} 枚を書き出しました")
