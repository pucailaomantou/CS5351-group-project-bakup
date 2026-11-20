import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult


def _agent_from_metadata(metadata: dict[str, Any] | None) -> str:
    """The agent (graph node) responsible for a model call.

    LangGraph stamps every callback with ``langgraph_node`` and
    ``langgraph_checkpoint_ns``. The analysts each run inside their own subgraph,
    so their inner node is always ``"agent"``; the checkpoint namespace's first
    segment is the analyst's own node name (``"Market Analyst:...|agent:..."``),
    which is what tells the four analysts apart. Outer agents (researchers,
    debaters, managers, trader) expose their name directly through
    ``langgraph_node``.
    """
    metadata = metadata or {}
    namespace = metadata.get("langgraph_checkpoint_ns") or ""
    if namespace:
        outer = namespace.split("|", 1)[0].split(":", 1)[0]
        if outer:
            return outer
    node = metadata.get("langgraph_node")
    if node:
        return str(node)
    return "unknown"


def _usage_from_response(response: LLMResult) -> tuple[int, int, int] | None:
    """``(input, output, total)`` tokens from a response, or ``None`` if absent.

    Providers that report no usage (some local/compatible endpoints) return
    ``None`` so the call is recorded as unavailable rather than as zero.
    """
    try:
        generation = response.generations[0][0]
    except (IndexError, TypeError):
        return None

    message = getattr(generation, "message", None)
    if not isinstance(message, AIMessage):
        return None
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, int(total_tokens)


class StatsCallbackHandler(BaseCallbackHandler):
    """Callback handler tracking LLM calls, tool calls, and token usage.

    Tokens are tracked globally (the original behavior) and per agent, so a
    run can report where its token budget went. Every model call is also
    recorded individually; a call whose provider reported no usage is kept
    with ``None`` token counts and marked unavailable, never silently as zero.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.total_tokens = 0
        # How many finished calls reported usage vs. none at all. Together with
        # llm_calls this gives the global usage_state below, so a real 0 is
        # never confused with "the provider told us nothing".
        self.usage_calls = 0
        self.unavailable_calls = 0
        # run_id -> agent name, so on_llm_end can attribute the usage it reads.
        self._run_agents: dict[str, str] = {}
        # run_ids already counted at start, so a provider that fires both
        # on_llm_start and on_chat_model_start for one call is not double-counted.
        self._started: set[str] = set()
        # One record per model call: {"agent", "input_tokens", "output_tokens",
        # "total_tokens"}; the token entries are None when usage was unavailable.
        self.calls: list[dict[str, Any]] = []
        # agent name -> aggregate. Tokens sum the calls that reported usage;
        # ``calls``/``unavailable_calls`` show how many did not.
        self.per_agent: dict[str, dict[str, Any]] = {}

    def _begin(self, agent: str, run_id: Any) -> None:
        if run_id is not None:
            self._run_agents[str(run_id)] = agent
        bucket = self.per_agent.setdefault(
            agent,
            {
                "calls": 0,
                "unavailable_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        )
        bucket["calls"] += 1

    def _register_start(self, agent: str, run_id: Any) -> None:
        """Count a call once per run_id; ignore a duplicate start event.

        Chat models fire ``on_chat_model_start``; some providers fire both that
        and ``on_llm_start`` for one call. Keying on run_id makes the count
        exactly one per call regardless. When ``run_id`` is None (no id
        available) the event is still counted, since there is no key to dedupe.
        """
        if run_id is not None:
            key = str(run_id)
            if key in self._started:
                return
            self._started.add(key)
        self.llm_calls += 1
        self._begin(agent, run_id)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when an LLM starts."""
        agent = _agent_from_metadata(metadata)
        with self._lock:
            self._register_start(agent, run_id)

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when a chat model starts."""
        agent = _agent_from_metadata(metadata)
        with self._lock:
            self._register_start(agent, run_id)

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Record token usage for this call, globally and for its agent."""
        usage = _usage_from_response(response)
        with self._lock:
            agent = self._run_agents.pop(str(run_id), None) if run_id is not None else None
            if run_id is not None:
                self._started.discard(str(run_id))
            if agent is None:
                agent = _agent_from_metadata(metadata)
            bucket = self.per_agent.setdefault(
                agent,
                {
                    "calls": 0,
                    "unavailable_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            )

            if usage is None:
                self.calls.append(
                    {
                        "agent": agent,
                        "input_tokens": None,
                        "output_tokens": None,
                        "total_tokens": None,
                    }
                )
                bucket["unavailable_calls"] += 1
                self.unavailable_calls += 1
                return

            input_tokens, output_tokens, total_tokens = usage
            self.tokens_in += input_tokens
            self.tokens_out += output_tokens
            self.total_tokens += total_tokens
            self.usage_calls += 1
            bucket["input_tokens"] += input_tokens
            bucket["output_tokens"] += output_tokens
            bucket["total_tokens"] += total_tokens
            self.calls.append(
                {
                    "agent": agent,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                }
            )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Increment tool call counter when a tool starts."""
        with self._lock:
            self.tool_calls += 1

    def _usage_state_locked(self) -> str:
        """``usage_state`` assuming the caller already holds ``self._lock``."""
        if self.llm_calls == 0:
            return "no_calls"
        if self.unavailable_calls == 0 and self.usage_calls == self.llm_calls:
            return "complete"
        if self.usage_calls == 0:
            return "unavailable"
        return "partial"

    def usage_state(self) -> str:
        """How complete the global token totals are across finished calls.

        Thread-safe: acquires the same lock as the counters, so a direct call
        under concurrency sees a consistent snapshot. ``get_stats`` calls the
        lock-held helper directly to avoid re-entering the (non-reentrant) lock.

        ``"complete"``: every call reported usage, so the totals are exact.
        ``"partial"``:  some calls did, and the totals cover only those.
        ``"unavailable"``: no call reported usage; the totals mean nothing.
        ``"no_calls"``: nothing finished yet, so there is nothing to judge.
        """
        with self._lock:
            return self._usage_state_locked()

    def get_stats(self) -> dict[str, Any]:
        """Return current statistics, globally and per agent.

        The original keys (``llm_calls``, ``tool_calls``, ``tokens_in``,
        ``tokens_out``) are unchanged so existing callers keep working.
        ``usage_state``/``usage_complete`` say how far the global totals can be
        trusted: a real 0 (complete) is never confused with "no data"
        (unavailable) or a mix (partial). ``per_agent`` carries each agent's
        totals along with how many of its calls reported usage; a call without
        usage never adds zero silently.
        """
        with self._lock:
            state = self._usage_state_locked()
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "total_tokens": self.total_tokens,
                "usage_calls": self.usage_calls,
                "unavailable_calls": self.unavailable_calls,
                "usage_state": state,
                "usage_complete": state == "complete",
                "per_agent": {
                    name: dict(agg) for name, agg in sorted(self.per_agent.items())
                },
                "calls": [dict(record) for record in self.calls],
            }
