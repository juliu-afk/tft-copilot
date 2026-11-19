# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['tft_copilot\\launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('data/rules', 'data/rules'), ('data/units', 'data/units'), ('data/traits', 'data/traits'), ('data/equips', 'data/equips'), ('data/cards', 'data/cards'), ('data/templates', 'data/templates'), ('tools/ocr_probe.ps1', 'tools')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['paddle', 'paddleocr', 'pandas', 'matplotlib', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='tft-copilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
