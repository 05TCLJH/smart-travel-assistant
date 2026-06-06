"""工作流检查点辅助函数。"""

from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer() -> MemorySaver:
    # 将检查点限定在当前执行链路内，避免不同用户共享同一个进程内 Saver。
    return MemorySaver()
