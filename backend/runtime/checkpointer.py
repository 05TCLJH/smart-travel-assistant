"""工作流检查点辅助函数。"""

from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer() -> MemorySaver:
    # Keep checkpoints scoped to the current execution chain so different users
    # do not share a global in-process saver.
    return MemorySaver()
