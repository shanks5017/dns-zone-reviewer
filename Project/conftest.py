# conftest.py – pytest root configuration for dns-zone-reviewer
#
# Placing conftest.py at the project root makes pytest treat this directory
# as the rootdir. It also adds src/ to sys.path so that `import validator`,
# `import differ`, and `import main` work in every test file without any
# manual sys.path manipulation.

import sys
from pathlib import Path

# Insert src/ at the front of sys.path so project modules take precedence
# over any same-named packages that might be installed system-wide.
_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
