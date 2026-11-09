Third-party runtime dependencies
These packages are not bundled in this repository. The plugin downloads them on demand via paper_translate_env (install action), which fetches wheels from PyPI into a local folder.

Package	License	Role
PyMuPDF	AGPL-3.0 (or commercial licence from Artifex)	PDF parsing and page rasterisation
SciPy	BSD-3-Clause	connected-component analysis for figure/table detection
PyYAML	MIT	configuration parsing used by PyMuPDF's table finder
AGPL note
PyMuPDF is AGPL-3.0. This repository only references it as a runtime dependency and does not redistribute it, so the AGPL obligations do not extend to this source tree.

If you build a distributable bundle that contains PyMuPDF (for example a standalone executable or a packaged wheel set), that bundle falls under AGPL-3.0 and you must comply with its terms — or obtain a commercial licence from Artifex.

Fonts
Figure and table text is rendered with fonts installed on the user's own system (Microsoft YaHei / SimHei on Windows). They are referenced by path and not redistributed here.
