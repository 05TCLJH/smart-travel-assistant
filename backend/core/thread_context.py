"""在工作线程间保留请求级上下文的辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, Future
from contextvars import copy_context
from typing import ParamSpec, TypeVar


P = ParamSpec("P")
T = TypeVar("T")


def submit_with_context(executor: Executor, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> Future[T]:
    context = copy_context()
    return executor.submit(context.run, func, *args, **kwargs)
