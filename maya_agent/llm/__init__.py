"""LLM providers package."""

from maya_agent.llm.base import (
    ChatMessage,
    ChatResponse,
    StreamChunk,
    ToolCall,
    ToolSpec,
)


def __getattr__(name):
    # Tool schemas and image attachments use llm.base without making API calls.
    # Keep HTTP providers optional until the chat UI actually requests one.
    if name in {"create_provider", "list_providers"}:
        from maya_agent.llm import registry

        value = getattr(registry, name)
        globals()[name] = value
        return value
    raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))

__all__ = [
    "ChatMessage",
    "ChatResponse",
    "StreamChunk",
    "ToolCall",
    "ToolSpec",
    "create_provider",
    "list_providers",
]
