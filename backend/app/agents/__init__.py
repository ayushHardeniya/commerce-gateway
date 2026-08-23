"""AI buyer agent layer.

`app.agents` may depend on `app.catalog` (and future domain modules). No
domain module may depend on `app.agents` — the dependency only ever points
one way, so the commerce domain stays usable and testable with no notion of
an LLM. See `app.agents.tools.base` for the tool contract this layer is
built around: the LLM proposes actions only through explicit, typed tools,
never through direct database, HTTP, or code-execution access.
"""
