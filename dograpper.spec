# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_all, copy_metadata

# Bundle dograpper's dist-info so importlib.metadata.version("dograpper") works at runtime
dograpper_metadata = copy_metadata("dograpper")

# Namespace-package-friendly aggregation for tiktoken (known PyInstaller pain point)
tiktoken_datas, tiktoken_binaries, tiktoken_hiddenimports = collect_all("tiktoken")

# Collect playwright data files and submodules but NOT __main__.py (it conflicts with app entry point).
# collect_all("playwright") would bundle playwright/__main__.py which PyInstaller then runs instead
# of the app's entry script (playwright.__main__ calls the playwright CLI driver and exits 0 silently).
from PyInstaller.utils.hooks import collect_data_files
playwright_datas = collect_data_files("playwright")
playwright_binaries = []
playwright_hiddenimports = collect_submodules("playwright")

import os as _os
_here = _os.path.dirname(_os.path.abspath(SPEC))

a = Analysis(
    [_os.path.join(_here, "dograpper_entry.py")],
    pathex=[_os.path.join(_here, "src")],
    binaries=tiktoken_binaries + playwright_binaries,
    datas=tiktoken_datas + playwright_datas + dograpper_metadata,
    hiddenimports=(
        collect_submodules("dograpper")
        + tiktoken_hiddenimports
        + [m for m in playwright_hiddenimports if m != "playwright.__main__"]
        + ["tiktoken_ext", "tiktoken_ext.openai_public"]
        # httrack extra: policy.py imports these lazily, so PyInstaller cannot see them
        + collect_submodules("brotli")
        + collect_submodules("zstandard")
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["playwright.__main__"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="dograpper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
