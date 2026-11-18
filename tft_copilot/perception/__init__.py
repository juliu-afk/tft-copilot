"""感知层：截屏 -> 结构化棋局状态（M2）。

模块导出：
- ScreenGrabber: mss 截屏取帧（L1 PIL 兜底）
- TemplateBank: 模板库（头像/数字/角标，版本目录隔离）
- GameScene / SceneScheduler: 场景判定与降频调度
- read_number: 数字 ROI 识别
- UnitBox / UnitSpotter: 弈子识别（两级金字塔）

红线自查：全模块零网络、零输入模拟、零进程读取。
"""

from tft_copilot.perception.grabber import GrabStats, ScreenGrabber
from tft_copilot.perception.numbers import read_number
from tft_copilot.perception.scene import GameScene, SceneScheduler
from tft_copilot.perception.templates import TemplateBank
from tft_copilot.perception.units_spotter import UnitBox, UnitSpotter

__all__ = [
    "GameScene",
    "GrabStats",
    "SceneScheduler",
    "ScreenGrabber",
    "TemplateBank",
    "UnitBox",
    "UnitSpotter",
    "read_number",
]
