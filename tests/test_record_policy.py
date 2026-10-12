"""記録の基準（docs/record-policy.md）のうち、言い回しで見分けられる分を検査する。

git に入った文は消しても履歴に残るので、入る前に止める。見つけた書き方は PATTERNS に足していく。
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 基準そのものを説明する文書は、避ける言い回しを例として含むので除く
EXEMPT = {
    "docs/record-policy.md",
    "tests/test_record_policy.py",
    # 秘密情報を見つけるための型の一覧で、例としての接続文字列を含む
    ".claude/skills/secret-leak-check/references/patterns.md",
}

PATTERNS = {
    # 人の反応を主語にした書き方。「〜と言われたら」「〜と言われたとき」はスキルの起動条件なので通す
    "利用者の発言や反応の引用": re.compile(r"(?:と|って)言われ(?!たら|たとき|ても)|指摘され|叱|怒られ|気持ち悪"),
    "文章を書いた AI のモデル名": re.compile(r"Claude (?:Opus|Sonnet|Haiku|Fable)"),
    "鍵の形の文字列": re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"),
    "メールアドレス": re.compile(r"[\w.+-]+@(?!anthropic\.com)[\w-]+\.[a-z]{2,}"),
}


def tracked_texts():
    out = subprocess.run(["git", "ls-files", "*.md", "*.txt"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split() if p not in EXEMPT]


class RecordPolicyTest(unittest.TestCase):
    def test_no_forbidden_phrases(self):
        found = []
        for rel in tracked_texts():
            path = ROOT / rel
            if not path.exists():
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                for kind, pat in PATTERNS.items():
                    if pat.search(line):
                        found.append(f"{rel}:{n} {kind}")
        self.assertEqual(found, [], "記録の基準（docs/record-policy.md）に合わない書き方:\n" + "\n".join(found))

    def test_patterns_catch_examples(self):
        # 一覧が効いていることを、典型の文で確かめる（効かなくなったら気づけるように）
        hits = {
            "利用者の発言や反応の引用": "写実の顔は良くないと言われた",
            "文章を書いた AI のモデル名": "Co-Authored-By: Claude Opus 5.5",
            "鍵の形の文字列": "sk-ant-abcdefghijk",
            "メールアドレス": "someone@example.com",
        }
        for kind, text in hits.items():
            self.assertTrue(PATTERNS[kind].search(text), kind)
        self.assertIsNone(PATTERNS["利用者の発言や反応の引用"].search("「描いて」と言われたら、まず描く"))


if __name__ == "__main__":
    unittest.main()
