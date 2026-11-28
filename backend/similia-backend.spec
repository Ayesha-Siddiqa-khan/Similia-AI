# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the Similia AI desktop backend.

Build with:
    cd backend
    uv sync --group speech --group packaging
    uv run --no-sync pyinstaller --noconfirm --clean similia-backend.spec
"""

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = []

# Runtime data and native libraries that PyInstaller's static analysis cannot see.
for package in (
    "faster_whisper",
    "ctranslate2",
    "av",
    "onnxruntime",
    "tokenizers",
    "huggingface_hub",
    "pymupdf",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# Packages that read their own version from distribution metadata at runtime.
for distribution in (
    "faster-whisper",
    "ctranslate2",
    "av",
    "onnxruntime",
    "tokenizers",
    "huggingface-hub",
    "pymupdf",
    "langchain",
    "langchain-core",
    "langchain-community",
    "langchain-anthropic",
    "langchain-voyageai",
    "langgraph",
    "langsmith",
    "strawberry-graphql",
    "uvicorn",
    "fastapi",
    "pydantic",
    "pydantic-settings",
    "supabase",
    "voyageai",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "app.main",
    "app.services.speech.worker",
]

a = Analysis(
    ["desktop_entry.py"],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
        "PyQt5",
        "PySide6",
        "torch",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="similia-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="similia-backend",
)
