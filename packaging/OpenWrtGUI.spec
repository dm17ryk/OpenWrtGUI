# PyInstaller spec: onedir build of OpenWrtGUI with the built UI bundled.
# Run from the repo root (tools/build_windows.ps1 does):
#   uv run --extra build pyinstaller packaging/OpenWrtGUI.spec --noconfirm --distpath dist --workpath build/pyi
# Relative paths below are relative to this file's folder (packaging/).

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32 import versioninfo as vi

# Version info from src/openwrtgui/version.py (tools/stamp_version.py writes it before a build).
_text = (Path(SPECPATH).parent / "src" / "openwrtgui" / "version.py").read_text(encoding="utf-8")
APP_VERSION = re.search(r'^APP_VERSION = "([^"]+)"$', _text, re.MULTILINE).group(1)
_m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-ci\.(\d+))?", APP_VERSION)
NUMERIC = tuple(int(p or 0) for p in _m.groups())
VERSION_INFO = vi.VSVersionInfo(
    ffi=vi.FixedFileInfo(filevers=NUMERIC, prodvers=NUMERIC),
    kids=[
        vi.StringFileInfo(
            [
                vi.StringTable(
                    "040904B0",
                    [
                        vi.StringStruct("CompanyName", "OpenWrtGUI contributors"),
                        vi.StringStruct("FileDescription", "OpenWrtGUI"),
                        vi.StringStruct("FileVersion", APP_VERSION),
                        vi.StringStruct("InternalName", "OpenWrtGUI"),
                        vi.StringStruct("LegalCopyright", "GPL-3.0-only"),
                        vi.StringStruct("OriginalFilename", "OpenWrtGUI.exe"),
                        vi.StringStruct("ProductName", "OpenWrtGUI"),
                        vi.StringStruct("ProductVersion", APP_VERSION),
                    ],
                )
            ]
        ),
        vi.VarFileInfo([vi.VarStruct("Translation", [1033, 1200])]),
    ],
)

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # asyncssh imports its key and cipher modules by name at run time.
    *collect_submodules("asyncssh"),
]

a = Analysis(
    ["../src/openwrtgui/__main__.py"],
    pathex=["../src"],
    datas=[("../frontend/dist", "openwrtgui/web")],
    hiddenimports=hiddenimports,
    # pydantic's hook collects pydantic.mypy (which imports mypy); pygments' image formatter imports
    # PIL. The app needs neither, and together they are ~16 MB. build_windows.ps1 checks they stay out.
    excludes=["tkinter", "mypy", "pydantic.mypy", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenWrtGUI",
    icon="openwrtgui.ico",
    console=False,
    version=VERSION_INFO,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="OpenWrtGUI",
    upx=False,
)
