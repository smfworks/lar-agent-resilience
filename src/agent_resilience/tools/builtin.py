"""
Built-in tools for the Local Agent Runtime.

These are the default tools available to every LAR agent:
- web_search: Search the web for current information
- web_fetch: Fetch and extract content from URLs
- exec: Execute shell commands (with restrictions)
- file_read: Read file contents
- file_write: Write content to files
"""

import re
import shlex
import subprocess
from pathlib import Path

import httpx

from agent_resilience.tools import Tool, ToolResult

_UNSAFE_SHELL_CHARS = set(";|&`$()<>\n\r")


def resolve_within_base(base_path: str | Path, user_path: str) -> tuple[Path | None, str]:
    """Resolve user_path inside base_path. Rejects absolute, prefix, and symlink escapes."""
    base = Path(base_path).resolve()
    raw = Path(user_path)
    if raw.is_absolute():
        return None, f"Access denied: path '{user_path}' is outside base directory"
    candidate = base / raw
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        return None, str(exc)
    try:
        resolved.relative_to(base)
    except ValueError:
        return None, f"Access denied: path '{user_path}' is outside base directory"
    return resolved, ""


class WebSearchTool(Tool):
    """Search the web using the configured search provider."""

    def __init__(self):
        super().__init__(
            name="web_search",
            description="Search the web for current information. Use for finding news, documentation, references, and facts.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results to return (1-10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        )

    async def execute(self, query: str, count: int = 5) -> ToolResult:
        """Execute web search via DuckDuckGo or similar."""
        try:
            ddg_url = "https://duckduckgo.com/html/"
            params = {"q": query}

            async with httpx.AsyncClient() as client:
                await client.get(ddg_url, params=params, timeout=30.0)

            return ToolResult(
                output=f"Search initiated for: {query}. Use web_fetch to retrieve specific pages.",
            )
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


class WebFetchTool(Tool):
    """Fetch and extract readable content from URLs."""

    def __init__(self):
        super().__init__(
            name="web_fetch",
            description="Fetch and extract readable content from a URL. Use for reading articles, documentation, and web pages.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return",
                        "default": 5000,
                    },
                },
                "required": ["url"],
            },
        )

    async def execute(self, url: str, max_chars: int = 5000) -> ToolResult:
        """Fetch URL and extract readable content. HTTPS only."""
        if not url.lower().startswith("https://"):
            return ToolResult(
                output=None,
                error="Only https URLs are allowed",
                success=False,
            )
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, timeout=30.0)
                response.raise_for_status()

                content = response.text

                text = re.sub(r"<script>.*?</script>", "", content, flags=re.DOTALL)
                text = re.sub(r"<style>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()

                if len(text) > max_chars:
                    text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

                return ToolResult(output=text)
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


class ExecTool(Tool):
    """Execute shell commands with safety restrictions.

    Security: uses shlex.split() and subprocess without shell=True to prevent
    shell injection via command chaining. Interpreters and VCS are opt-in.
    """

    ALLOWED_COMMANDS = frozenset({
        "ls",
        "cat",
        "grep",
        "find",
        "head",
        "tail",
        "wc",
        "date",
        "whoami",
        "pwd",
        "echo",
        "which",
    })

    BLOCKED_PATTERNS = [
        "rm -rf",
        "rm -r /",
        "> /dev",
        "dd if=",
        "mkfs.",
        r"curl .*\|",
        r"wget .*\|",
        "eval",
        "exec",
    ]

    def __init__(self, allowed_commands: list[str] | None = None):
        self.custom_allowed = frozenset(allowed_commands) if allowed_commands else frozenset()
        super().__init__(
            name="exec",
            description="Execute a shell command. Only safe, read-only commands are allowed. Use for checking files, running scripts, and gathering system information.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        )

    def _is_safe(self, command: str) -> tuple[bool, str]:
        """Check if command is safe to execute without a shell."""
        if not command or not command.strip():
            return False, "empty command"

        if any(ch in command for ch in _UNSAFE_SHELL_CHARS):
            return False, "command contains unsafe shell metacharacters"

        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Command matches blocked pattern: {pattern}"

        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return False, f"could not parse command: {exc}"

        if not argv:
            return False, "empty command"

        base_cmd = Path(argv[0]).name
        allowed = self.ALLOWED_COMMANDS | self.custom_allowed
        if base_cmd not in allowed:
            return False, f"Command '{base_cmd}' is not in the allowed list"

        return True, ""

    async def execute(self, command: str, timeout: int = 30) -> ToolResult:
        """Execute command with safety checks and no shell."""
        safe, reason = self._is_safe(command)
        if not safe:
            return ToolResult(output=None, error=f"Safety check failed: {reason}", success=False)

        try:
            argv = shlex.split(command)
            result = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            return ToolResult(
                output=output,
                success=result.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(output=None, error=f"Command timed out after {timeout}s", success=False)
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


class FileReadTool(Tool):
    """Read file contents."""

    def __init__(self, base_path: str = "."):
        self.base_path = base_path
        super().__init__(
            name="file_read",
            description="Read the contents of a file. Use for reading configuration, logs, code, and documentation.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read (relative to base path)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum lines to read",
                        "default": 1000,
                    },
                },
                "required": ["path"],
            },
        )

    async def execute(self, path: str, limit: int = 1000) -> ToolResult:
        """Read file contents."""
        try:
            resolved, err = resolve_within_base(self.base_path, path)
            if err or resolved is None:
                return ToolResult(
                    output=None,
                    error=err or f"Access denied: path '{path}' is outside base directory",
                    success=False,
                )

            if not resolved.exists():
                return ToolResult(output=None, error=f"File not found: {path}", success=False)

            if resolved.is_dir():
                return ToolResult(output=None, error=f"Path is a directory: {path}", success=False)

            lines = []
            with open(resolved) as f:
                for i, line in enumerate(f):
                    if i >= limit:
                        lines.append(f"\n... [truncated at {limit} lines]")
                        break
                    lines.append(line)

            return ToolResult(output="".join(lines))
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


class FileWriteTool(Tool):
    """Write content to files."""

    def __init__(self, base_path: str = ".", allow_overwrite: bool = False):
        self.base_path = base_path
        self.allow_overwrite = allow_overwrite
        super().__init__(
            name="file_write",
            description="Write content to a file. Use for creating reports, saving data, and writing output files.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write (relative to base path)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                },
                "required": ["path", "content"],
            },
        )

    async def execute(self, path: str, content: str) -> ToolResult:
        """Write content to file."""
        try:
            resolved, err = resolve_within_base(self.base_path, path)
            if err or resolved is None:
                return ToolResult(
                    output=None,
                    error=err or f"Access denied: path '{path}' is outside base directory",
                    success=False,
                )

            if resolved.exists() and not self.allow_overwrite:
                return ToolResult(
                    output=None,
                    error=f"File exists and overwrite is disabled: {path}",
                    success=False,
                )

            resolved.parent.mkdir(parents=True, exist_ok=True)

            with open(resolved, "w") as f:
                f.write(content)

            return ToolResult(output=f"File written: {resolved}")
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


def register_builtin_tools(registry, config: dict = None):
    """Register all built-in tools with the given registry."""
    config = config or {}

    exec_config = config.get("exec", {})
    file_config = config.get("file", {})

    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(ExecTool(allowed_commands=exec_config.get("allowed_commands")))
    registry.register(FileReadTool(base_path=file_config.get("base_path", ".")))
    registry.register(FileWriteTool(
        base_path=file_config.get("base_path", "."),
        allow_overwrite=file_config.get("allow_overwrite", False),
    ))
