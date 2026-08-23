# 0004. AI buyer acts only through a typed, provider-neutral tool contract

## Status

Accepted

## Context

Milestone 2 begins the AI buyer. The eventual shape is an LLM that
interprets a natural-language shopping request and decides what to do next.
`CLAUDE.md` and `ARCHITECTURE.md` already establish a hard determinism
boundary — financial calculations, authorization, policy enforcement,
transaction state, and payment execution must never depend on an LLM's
output — but that boundary only holds if it's structurally impossible for
the LLM to reach those things directly. An LLM with raw database access, raw
SQL, arbitrary HTTP access, or code execution could bypass any amount of
prompt-level instruction not to.

Separately, this milestone is explicitly scoped to *not* integrate a
specific LLM vendor (Gemini) yet. Whatever is built now has to be genuinely
useful once Gemini (or another provider) is wired in later, without needing
to be redesigned.

## Decision

The LLM's only channel to application state is a small, explicit set of
**tools**, defined in `app/agents/tools/`:

- Each tool (`Tool` in `agents/tools/base.py`) declares an explicit `name`,
  `description`, a typed Pydantic input schema, and a typed output schema.
- A tool's single entry point, `run(raw_input: dict)`, validates the input
  against its schema, executes deterministically against the existing
  domain layer (`app.catalog.repository` for the catalog tools), and always
  returns a `ToolResult` — either the typed `output` or a typed `ToolError`
  with a closed `ToolErrorCode` (`invalid_input`, `not_found`,
  `internal_error`). `run()` never raises and never leaks a stack trace or
  raw database error to the caller.
- Tools contain no LLM calls, no ranking/recommendation logic, and no
  randomness — same catalog state and input always produce the same result.
- `app.agents` may import from `app.catalog`; no domain module may import
  from `app.agents`. Checked statically in
  `backend/tests/agents/test_architecture.py`, not left to convention.
- Nothing in this layer references a specific LLM SDK or vendor. The
  contract (typed schema in, typed structured result out) is exactly what
  any function/tool-calling API — Gemini, OpenAI, Anthropic, etc. — needs to
  be handed; adapting a specific provider is future, separate work that sits
  on top of this contract rather than inside it.

The first two tools, `search_catalog` and `get_product`, are thin wrappers
over the catalog repository functions the HTTP API already uses, returning
the same `ProductCatalogView`/`ProductPage` shapes — so the agent and the
HTTP API can never drift into different availability or filtering
semantics.

## Consequences

- The LLM can be given exactly these tools' JSON schemas and never anything
  broader; there is no code path by which it could execute arbitrary SQL,
  arbitrary HTTP requests, or arbitrary Python, regardless of what a prompt
  injection or a model mistake asks for.
- Every future domain capability the agent needs (cart operations, checkout
  initiation, etc.) is added the same way: a new `Tool` subclass with a
  typed schema, not a new ad hoc integration point. This keeps the tool
  surface enumerable and auditable as it grows.
- Swapping or adding an LLM provider later touches only a new adapter layer
  that turns `Tool` definitions into that provider's function-calling
  format and turns its tool-call requests into `run()` calls — it does not
  touch `app.catalog` or the tool implementations themselves.
- This ADR does not decide anything about the agent loop itself (how tool
  calls get sequenced, conversation state, or how a specific provider's
  function-calling API is invoked) — only the contract tools must satisfy.
  Those are separate, later decisions.
