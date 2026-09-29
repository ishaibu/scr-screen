"""Allow ``python -m scr_screen``."""

import sys

from .cli import main

sys.exit(main())
