"""Adapter registry — imports every adapter so core.register() populates."""
from __future__ import annotations

from .. import core as _core
from . import deepswe, foodtruck, livecodebench, mmlu, swebench_pro, taubench, terminalbench

# Register each adapter with the core registry.
_core.register(mmlu.MMLUAdapter)
_core.register(livecodebench.LiveCodeBenchAdapter)
_core.register(deepswe.DeepSWEAdapter)
_core.register(terminalbench.TerminalBenchAdapter)
_core.register(swebench_pro.SWEBenchProAdapter)
_core.register(taubench.TauBenchAdapter)
_core.register(foodtruck.FoodTruckAdapter)

__all__ = [
    "deepswe", "foodtruck", "livecodebench", "mmlu",
    "swebench_pro", "taubench", "terminalbench",
]
