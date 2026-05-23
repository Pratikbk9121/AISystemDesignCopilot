"""
Central tool registry for LLM function-calling.

To add a new tool:
    1. Write a pure function in this package (see :mod:`capacity` for example).
    2. Define an OpenAI tool spec (``{"type": "function", "function": {...}}``).
    3. Add an entry to ``_TOOLS`` below mapping the tool name to (spec, impl).

``dispatch_tool`` is the synchronous executor — it validates the name and
forwards the kwargs.  Tools should be pure / non-blocking so this can be
called from inside an async LLM loop without thread-pool gymnastics.
"""
from typing import Any, Callable, Dict, List, Tuple
import logging

from app.core.tools.capacity import CAPACITY_TOOL_SPEC, estimate_capacity

logger = logging.getLogger(__name__)


# name -> (openai-spec-dict, python-callable)
_TOOLS: Dict[str, Tuple[Dict[str, Any], Callable[..., Any]]] = {
    "estimate_capacity": (CAPACITY_TOOL_SPEC, estimate_capacity),
}


TOOL_SPECS: List[Dict[str, Any]] = [spec for spec, _ in _TOOLS.values()]


def tool_names() -> List[str]:
    """Public list of registered tool names."""
    return list(_TOOLS.keys())


def dispatch_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the named tool with the given kwargs.

    Args:
        name: Tool name (must match a key in ``_TOOLS``).
        args: Keyword arguments parsed from the LLM's tool_call.

    Returns:
        Tool result dict. On error, returns ``{"error": "..."}`` so the
        LLM gets a useful response instead of a raised exception.
    """
    entry = _TOOLS.get(name)
    if entry is None:
        logger.warning("LLM requested unknown tool: %r", name)
        return {"error": f"Unknown tool: {name!r}. Registered tools: {list(_TOOLS)}"}
    _, impl = entry
    try:
        return impl(**args)
    except TypeError as e:
        # Bad argument shape — return as soft error so the model can recover.
        logger.warning("Tool %r called with bad args %r: %s", name, args, e)
        return {"error": f"Invalid arguments for {name}: {e}"}
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("Tool %r raised: %s", name, e)
        return {"error": f"Tool {name} failed: {e}"}
