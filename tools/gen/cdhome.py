"""部品・模型・利用者のデータを置く場所（既定はリポジトリの .cache）。

環境変数 CD_HOME で替えられる。入れた場所と置き場所を分けると、入れ直しや版の更新で模型（約 9GB）と
学んだ基準を消さずに済む。置き場所を組み立てるのはここだけにする（ほかで ROOT / ".cache" を組むと、替えたときに片方だけ残る）。
"""
import os
from pathlib import Path

HOME = Path(os.environ.get("CD_HOME") or Path(__file__).resolve().parents[2] / ".cache")
