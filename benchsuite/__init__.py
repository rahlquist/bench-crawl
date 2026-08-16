"""benchsuite — orchestrator for multiple model benchmark harnesses."""
__version__ = "0.1.0"

# Importing adapters runs the register() side-effects that populate core.ADAPTERS.
from . import adapters as _adapters  # noqa: F401
from . import core  # noqa: F401
