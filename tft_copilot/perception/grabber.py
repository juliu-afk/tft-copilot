"""ScreenGrabber：mss 截屏封装（感知层取帧器）。

budget: 30ms/frame
红线自查：mss 只读屏幕像素，无输入模拟/进程读取/网络。
L1 降级：mss 不可用时切 PIL.ImageGrab。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class GrabStats:
    """截屏统计（黑屏率监测，三级降级判据）。"""
    total: int = 0
    black: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def black_rate(self) -> float:
        return self.black / self.total if self.total else 0.0


def is_black_frame(frame: np.ndarray, thresh: float = 0.97) -> bool:
    """黑屏判定：>=thresh 像素亮度 <8。"""
    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    return float((gray < 8).mean()) >= thresh


class ScreenGrabber:
    """mss 取帧器；grab() 返回 BGR ndarray(H,W,3)。"""

    def __init__(self, monitor_index: int = 0) -> None:
        self.monitor_index = monitor_index
        self._mss = None
        self._pil_mode = False
        self.stats = GrabStats()

    def _ensure_mss(self):
        if self._mss is None:
            import mss  # 延迟导入：测试环境可能无显示器
            self._mss = mss.mss()
        return self._mss

    def grab(self) -> np.ndarray:
        """截一帧 → BGR ndarray。失败/黑屏计入统计；连续失败抛 RuntimeError。"""
        try:
            if self._pil_mode:
                from PIL import ImageGrab
                img = np.asarray(ImageGrab.grab())
                frame = img[:, :, ::-1].copy()  # RGB → BGR
            else:
                m = self._ensure_mss()
                mon = m.monitors[min(self.monitor_index + 1, len(m.monitors) - 1)] if len(m.monitors) > 1 else m.monitors[0]
                shot = m.grab(mon)
                frame = np.asarray(shot)[:, :, :3][..., ::-1].copy()  # BGRA→BGR（mss 为 BGRA）
        except Exception as exc:  # noqa: BLE001 - 截屏异常统一走降级链
            self.stats.errors.append(str(exc))
            if not self._pil_mode:
                self._pil_mode = True  # L1：切 PIL 兜底
                return self.grab()
            raise RuntimeError(f"截屏彻底失败: {exc}") from exc
        self.stats.total += 1
        if is_black_frame(frame):
            self.stats.black += 1
        return frame

    def monitors(self) -> list[dict]:
        """显示器列表（主显示器在前）。"""
        m = self._ensure_mss()
        return list(m.monitors[1:]) or [m.monitors[0]]
