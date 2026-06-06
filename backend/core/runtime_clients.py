"""运行时客户端辅助函数。

旅行规划服务现在按任务/请求按需创建，因此不再需要进程级的高德客户端缓存重置。
"""

from __future__ import annotations


def reset_cached_amap_clients() -> None:
    """兼容旧调用方，保留该入口。"""
    return None
