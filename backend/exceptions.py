"""智能旅游助手领域异常。"""


class TripGenerationCancelled(Exception):
    """用户取消进行中的行程生成任务时抛出。"""
