"""Error types. CLI maps ConfigError to exit code 2 and ModelCallError (and other AgentError) to 3."""


class AgentError(Exception):
    """Runtime failure in the answer stage (exit code 3)."""


class ConfigError(AgentError):
    """Bad configuration: missing API key environment variable, bad base URL (exit code 2)."""


class ModelCallError(AgentError):
    """Chat completion request failed (HTTP error after retries, connection error, unreadable response)."""
