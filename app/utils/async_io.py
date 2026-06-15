"""Run blocking CPU/IO work off the asyncio event loop."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Callable, TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], /, *args, **kwargs) -> T:
    """Execute a sync callable in the default thread pool (keeps API responsive)."""
    if kwargs:
        func = partial(func, **kwargs)
    return await asyncio.to_thread(func, *args)
