"""落ちた記録: 捕まえられなかった例外が crash.log に残り、次の起動で前の回の分だけを見つける"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


class CrashLogTest(unittest.TestCase):
    def test_thread_exception_is_written_and_found(self):
        from chatdraw import crashlog
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "crash.log"
            with mock.patch.object(crashlog, "path", return_value=log):
                old_hook, old_thread = sys.excepthook, threading.excepthook
                try:
                    crashlog.install()
                    start = log.stat().st_size
                    self.assertEqual(crashlog.last_crash(start), "")
                    t = threading.Thread(target=lambda: 1 / 0, name="描く糸")
                    t.start()
                    t.join()
                    got = crashlog.last_crash(start)
                    self.assertIn("ZeroDivisionError", got)
                    self.assertIn("描く糸", got)
                    self.assertEqual(crashlog.last_crash(log.stat().st_size), "")   # 見たあとの分は空
                finally:
                    import faulthandler
                    faulthandler.disable()
                    sys.excepthook, threading.excepthook = old_hook, old_thread
                    if crashlog._FILE:
                        crashlog._FILE.close()


if __name__ == "__main__":
    unittest.main()
