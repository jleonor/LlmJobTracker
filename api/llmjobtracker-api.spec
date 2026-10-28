# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

# trafilatura (settings.cfg, data/tei_corpus.dtd) and justext (its stoplists/ folder, used as a
# fallback extractor) both ship non-Python resources that PyInstaller's import analysis won't
# pick up on its own, and neither has a bundled PyInstaller hook. Without this, the frozen
# backend hits a missing settings.cfg on every extraction, or a missing stoplist whenever
# trafilatura falls back to justext - both only on a URL/HTML job listing.
datas = collect_data_files('trafilatura') + collect_data_files('justext')

a = Analysis(
    ['src/llmjobtracker/__main__.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='llmjobtracker-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='llmjobtracker-api',
)
