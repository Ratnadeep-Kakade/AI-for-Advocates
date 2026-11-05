from enum import Enum

class HookEvent(str, Enum):
    PRE_EXECUTION = "pre_execution"
    POST_EXECUTION = "post_execution"
    PRE_TASK = "pre_task"
    POST_TASK = "post_task"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_VALIDATE = "pre_validate"
    POST_VALIDATE = "post_validate"
    ON_FAILURE = "on_failure"
