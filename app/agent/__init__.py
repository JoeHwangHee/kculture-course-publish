"""RAG answer stage: retrieve top-k chunks, ask Nemotron (NIM, OpenAI-compatible) for a grounded JSON answer.

- nim_client: POST {base_url}/chat/completions via urllib, retries 5xx/429 only, injectable transport and sleep.
- prompt: system rules + evidence chunks wrapped in boundary markers, JSON answer schema.
- answer: retrieve -> prompt -> call -> parse/validate JSON (one re-request on parse failure).
"""

from agent.errors import AgentError, ConfigError, ModelCallError

__all__ = ["AgentError", "ConfigError", "ModelCallError"]
