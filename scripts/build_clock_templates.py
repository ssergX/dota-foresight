"""Собрать шаблоны цифр HUD-часов Dota из записи с известным offset.

Часы центрированы и меняют ширину с числом цифр -> читаем сегментацией по колонкам
(двоеточие отсеивается, т.к. его столбцы имеют <=1 белого пикселя) + классификацией
глифа по доле совпавших пикселей с канон-шаблоном. Ассеты привязаны к 1920x1080.

Запуск:  python scripts/build_clock_templates.py <video.mp4> <offset>
"""
import json
import os
import sys

import cv2

sys.path.insert(0, "src")
from dota_coach.video.align import (  # noqa: E402
    _clock_binary, _segment_glyphs, opencv_frame_at, video_time_for,
)

VIDEO, OFFSET = sys.argv[1], float(sys.argv[2])
BOX = (0.47, 0.028, 0.53, 0.060)   # центрированная область часов (доли w/h, 1080p)
THRESH = 170                        # светлые глифы на тёмной плите
CANON = (14, 20)                    # канонический размер глифа для классификации
# (game_time, ожидаемые цифры) — дневные кадры, покрывают 0..9
SAMPLES = [(600, "1000"), (754, "1234"), (956, "1556"), (478, "758"), (539, "859")]

frame_at = opencv_frame_at(VIDEO)
os.makedirs("assets/clock_digits", exist_ok=True)
templates = {}
for gt, expected in SAMPLES:
    b = _clock_binary(frame_at(video_time_for(gt, OFFSET)), BOX, THRESH)
    glyphs = _segment_glyphs(b, CANON)
    if len(glyphs) != len(expected):
        print(f"gt={gt}: ожидал {len(expected)} глифов, получил {len(glyphs)} — пропуск")
        continue
    for d, g in zip(expected, glyphs):
        if d not in templates:
            templates[d] = g
            cv2.imwrite(f"assets/clock_digits/{d}.png", g)

json.dump({"box": list(BOX), "thresh": THRESH, "canon": list(CANON)},
          open("assets/clock_box.json", "w"))
print("собраны цифры:", sorted(templates))
