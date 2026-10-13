import sys
from pathlib import Path

# The repository still contains a legacy copy of the worker at its root.
# Exercise the source actually included in the desktop installer.
sys.path.insert(0, str(Path(__file__).parents[1]))
