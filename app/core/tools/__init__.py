"""
LLM-callable tools (OpenAI function-calling spec).

The registry exposes:
    - ``TOOL_SPECS``: list of OpenAI tool-definition dicts, ready to pass as
      the ``tools=`` argument to chat.completions.create.
    - ``dispatch_tool(name, args)``: synchronous executor that returns a
      JSON-serializable result for a single tool invocation.

A fresh tool can be added by writing a function in this package and
registering it in :mod:`app.core.tools.registry`.
"""
from app.core.tools.registry import TOOL_SPECS, dispatch_tool, tool_names

__all__ = ["TOOL_SPECS", "dispatch_tool", "tool_names"]
