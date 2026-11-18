"""交互层：HUD 双实现（工程方案 8.1-8.3）。

- ConsoleHUD：终端版，PyQt6 缺失/CI 环境降级（PRD D4/A7）
- OverlayHUD：PyQt6 无边框置顶窗，Qt 导入失败自动回落
红线自查：零输入模拟（F9 只控制 HUD 自身显隐，非游戏输入）、零网络。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ANSI 颜色（ConsoleHUD Toast 用）
_ANSI = {"info": "\033[94m", "warn": "\033[93m", "critical": "\033[91m", "silent": "\033[90m"}
_RESET = "\033[0m"


@dataclass
class HUDState:
    """HUD 每帧状态（engine 填充）。"""

    layers: int | None = None
    next_milestone: int | None = None      # 下一里程碑层数
    dist_to_milestone: int | None = None   # 距下一里程碑层数
    players: list[tuple[str, float | None]] = field(default_factory=list)  # (名字, 战力分)
    match_id: int | None = None
    round_no: int | None = None


class HUDBase(ABC):
    """HUD 接口契约：update/toast/toggle/close。"""

    @abstractmethod
    def update(self, state: HUDState) -> None:
        """刷新常驻面板。"""

    @abstractmethod
    def toast(self, level: str, text: str) -> None:
        """弹出提醒：info 蓝 / warn 黄 / critical 红。"""

    def toggle(self) -> None:  # noqa: B027 - Console 实现刻意为空，Overlay 覆写
        """F9 开关钩子（Console 无视窗，默认无操作）。"""

    @abstractmethod
    def close(self) -> None:
        """关闭 HUD。"""


class ConsoleHUD(HUDBase):
    """终端版 HUD：每帧打印状态行 + Toast 彩色输出。"""

    def __init__(self, quiet: bool = False) -> None:
        self._quiet = quiet  # 测试模式：不真实打印
        self._visible = True

    def update(self, state: HUDState) -> None:
        if not self._visible or self._quiet:
            return
        bar = self._power_bars(state.players)
        print(
            f"[R{state.round_no or '-'}] 层数 {state.layers if state.layers is not None else '?'}"
            f" | 下一里程碑 {state.next_milestone or '-'}"
            f"（差 {state.dist_to_milestone if state.dist_to_milestone is not None else '?'}）"
            f" | {bar}"
        )

    @staticmethod
    def _power_bars(players: list[tuple[str, float | None]]) -> str:
        parts = []
        for name, score in players:
            if score is None:
                parts.append(f"{name}:?")
            else:
                n = int(score // 10)
                parts.append(f"{name} {'█' * n}{score:.0f}")
        return " ".join(parts)

    def toast(self, level: str, text: str) -> None:
        if self._quiet:
            return
        color = _ANSI.get(level, "")
        print(f"{color}[{level.upper()}] {text}{_RESET}")

    def close(self) -> None:
        if not self._quiet:
            print("[HUD] closed")


class OverlayHUD(HUDBase):
    """PyQt6 无边框置顶窗（1920x1080 基准，右下角 260x360）。

    依赖缺失/无显示环境时由 create_hud 回落到 ConsoleHUD。
    """

    def __init__(self) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

        self._Qt = Qt
        self._app_ref = None  # QApplication 由调用方持有
        self._win = QWidget()
        self._win.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self._win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._win.setStyleSheet("background-color: rgba(20, 20, 20, 200); color: white;")
        self._win.resize(260, 360)
        lay = QVBoxLayout(self._win)
        self._top = QLabel("层数 -")
        self._mid = QLabel("")
        self._bot = QLabel("")
        for w in (self._top, self._mid, self._bot):
            w.setWordWrap(True)
            lay.addWidget(w)
        # 屏幕右下角定位（1920x1080 基准；多分辨率 M6 校准）
        screen = self._win.screen() or QWidget().screen()
        geo = screen.availableGeometry()
        self._win.move(geo.right() - 270, geo.bottom() - 400)
        self._visible = True

    def update(self, state: HUDState) -> None:
        self._top.setText(
            f"层数 {state.layers if state.layers is not None else '?'}"
            f" | 里程碑 {state.next_milestone or '-'}"
            f" 差 {state.dist_to_milestone if state.dist_to_milestone is not None else '?'}"
        )
        lines = []
        for name, score in state.players:
            s = "?" if score is None else f"{score:.0f}"
            lines.append(f"{name}: {s}")
        self._mid.setText("\n".join(lines))
        self._bot.setText(f"R{state.round_no or '-'} M{state.match_id or '-'}")

    def toast(self, level: str, text: str) -> None:
        colors = {"info": "#5b9bd5", "warn": "#e6c045", "critical": "#e05252"}
        c = colors.get(level, "#aaaaaa")
        self._bot.setText(f'<span style="color:{c}">[{level.upper()}] {text}</span>')

    def toggle(self) -> None:
        self._visible = not self._visible
        self._win.setVisible(self._visible)

    def close(self) -> None:
        self._win.close()


def create_hud(prefer: str = "auto") -> HUDBase:
    """HUD 工厂：auto -> PyQt6 可用则 Overlay，否则 Console（D4/A7）。"""
    if prefer in ("auto", "overlay"):
        try:
            return OverlayHUD()
        except Exception:
            pass  # ImportError / 无显示环境 / Qt 初始化失败 -> 回落
    return ConsoleHUD()
