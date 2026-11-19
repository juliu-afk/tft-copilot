"""WindowGrabber：游戏窗口定位抓帧器（M6 真机层）。

解决三问题：
1. 全屏截图坐标错位 → FindWindow 定位游戏窗口，只抓客户区
2. 遮挡干扰 → PrintWindow(PW_RENDERFULLCONTENT) 穿透遮挡抓 DX 画面
3. 分辨率不一 → 统一 resize 到 1920x1080 标准帧，锚点坐标零改动

红线自查：只读窗口像素，无输入模拟、无进程内存读取。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import cv2
import numpy as np

GAME_WINDOW_TITLES = ["金铲铲之战"]
STD_W, STD_H = 1920, 1080


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def find_game_window() -> int | None:
    """按标题枚举顶层窗口，返回游戏窗口句柄（找不到返回 None）。"""
    user32 = ctypes.windll.user32
    hits: list[int] = []

    def cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value in GAME_WINDOW_TITLES:
                hits.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return hits[0] if hits else None


class WindowGrabber:
    """游戏窗口抓帧器：PrintWindow 穿透遮挡，输出 1920x1080 标准帧 BGR。"""

    def __init__(self, hwnd: int | None = None) -> None:
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self.hwnd = hwnd
        self.last_error: str | None = None

    def _ensure_hwnd(self) -> int:
        if self.hwnd is None or not self._user32.IsWindow(self.hwnd):
            self.hwnd = find_game_window()
        if not self.hwnd:
            raise RuntimeError("找不到游戏窗口（标题：金铲铲之战）")
        return self.hwnd

    def grab(self) -> np.ndarray:
        """抓游戏客户区一帧，resize 到 1920x1080 BGR ndarray。"""
        hwnd = self._ensure_hwnd()
        rect = wintypes.RECT()
        self._user32.GetClientRect(hwnd, ctypes.byref(rect))
        cw, ch = rect.right - rect.left, rect.bottom - rect.top
        if cw <= 0 or ch <= 0:
            raise RuntimeError(f"游戏客户区异常: {cw}x{ch}（窗口最小化？）")

        hwnd_dc = self._user32.GetDC(hwnd)
        mem_dc = self._gdi32.CreateCompatibleDC(hwnd_dc)
        bitmap = self._gdi32.CreateCompatibleBitmap(hwnd_dc, cw, ch)
        self._gdi32.SelectObject(mem_dc, bitmap)
        try:
            # PW_RENDERFULLCONTENT=2：支持 DirectComposition/DX 渲染窗口
            ok = self._user32.PrintWindow(hwnd, mem_dc, 2)
            if not ok:
                raise OSError("PrintWindow 失败")
            bih = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), cw, -ch, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(cw * ch * 4)
            got = self._gdi32.GetDIBits(mem_dc, bitmap, 0, ch, buf, ctypes.byref(bih), 0)
            if not got:
                raise OSError("GetDIBits 失败")
        finally:
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(mem_dc)
            self._user32.ReleaseDC(hwnd, hwnd_dc)

        frame = np.frombuffer(buf.raw, dtype=np.uint8).reshape(ch, cw, 4)
        bgr = frame[:, :, :3].copy()
        if bgr.shape[1] != STD_W or bgr.shape[0] != STD_H:
            bgr = cv2.resize(bgr, (STD_W, STD_H), interpolation=cv2.INTER_AREA)
        return bgr
