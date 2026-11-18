"""M2 感知层冒烟 CLI：合成帧全管线一命令跑通（A6）."""

from __future__ import annotations

import argparse

from tft_copilot.perception.numbers import read_number
from tft_copilot.perception.scene import GameScene, SceneScheduler
from tft_copilot.perception.synth import load_anchors, synth_scene_frame
from tft_copilot.perception.templates import TemplateBank
from tft_copilot.perception.units_spotter import UnitSpotter


def run(args: argparse.Namespace) -> int:
    print("=== tft-copilot perception-test（合成帧全管线冒烟）===")
    bank = TemplateBank()
    scheduler = SceneScheduler()
    spotter = UnitSpotter(bank)
    anchors = load_anchors()

    total, passed = 0, 0
    for scene in ("shop", "battle", "pre_game", "unknown"):
        frame = synth_scene_frame(scene)
        got = scheduler.detect(frame)
        ok = got == GameScene(scene)
        total, passed = total + 1, passed + int(ok)
        print(f"  scene {scene:9s} -> {got.value:9s} {'OK' if ok else 'FAIL'}")

    frame = synth_scene_frame("shop", layer=12, gold=34, hp=87, level=7)
    num_rois = {
        "layer": (1710, 120, 120, 50),
        "gold": (1710, 180, 120, 50),
        "hp": (200, 990, 120, 50),
        "level": (1710, 240, 120, 50),
    }
    wants = {"layer": 12, "gold": 34, "hp": 87, "level": 7}
    for name, roi in num_rois.items():
        got = read_number(frame, roi, bank)
        ok = got == wants[name]
        total, passed = total + 1, passed + int(ok)
        print(f"  {name:6s} want={wants[name]:3d} got={got} {'OK' if ok else 'FAIL'}")

    for i, roi in enumerate(anchors["units"]["shop5"]["rois"]):
        boxes = spotter.spot(frame, tuple(roi))
        ok = bool(boxes) and boxes[0].score >= 0.9
        total, passed = total + 1, passed + int(ok)
        top = f"{boxes[0].unit_id}({boxes[0].score:.2f})" if boxes else "-"
        print(f"  card{i + 1} {top} {'OK' if ok else 'FAIL'}")

    print(f"== 冒烟结果 {passed}/{total} ==")
    return 0 if passed == total else 1


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("perception-test", help="感知层合成帧全管线冒烟")
    p.set_defaults(func=run)
