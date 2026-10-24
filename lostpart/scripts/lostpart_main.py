"""Entry point used by the packaged builds.

PyInstaller and the Linux launcher both need a *top level* script, because
``lostpart.cli`` uses relative imports that only work inside the package.
"""

from __future__ import annotations

import sys

from lostpart.cli import main

if __name__ == "__main__":
    sys.exit(main())
