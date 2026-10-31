"""女性を描くときの基準の体（利用者が決めた体型。casts/body-types.json の anime.ideal）。

頼みの「女性」を adult woman, mature female と訳していたため、どの模型も脂肪の多い年配の体と顔で描いた
（mature female は年配の女性の札）。女性を描くときは、この基準の体の言葉を足し、描かない物にも基準の禁止を足す。
配る版（Setup.exe）には casts/ を入れないので、値はここに写して持ち、試験（test_body）で casts と食い違わないかを見る。
"""
from __future__ import annotations

TAGS = ("adult woman, slender body, soft body, toned, slim waist, wide hips, slender legs, medium breasts, cleavage, "
        "long legs, healthy")
NEGATIVE = ("logo, brand logo, emblem, text on clothes, see-through, abs, muscular, six pack, micro bikini, thick thighs, "
            "mature female, old woman, plump, fat, chubby, huge breasts, gigantic breasts")
WOMAN = "1girl, solo, " + TAGS
