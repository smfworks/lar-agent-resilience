"""
Built-in tools for the Local Agent Runtime.

Safety rules (enforced here, not by the model):
- exec: argv only, no shell, allowlisted binaries, no metacharacters
- web_fetch: https only, private/link-local/metadata/file blocked
- file_*: resolved path must stay inside the configured base directory
"""

from __future__ import annotations

import ipaddress
import re
import shlex
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx

from agent_resilience.tools import Tool, ToolResult

_SHELL_METACHARS = set(";|&`$<>(){}\n\r")


def path_is_inside(candidate: Path, base: Path) -> bool:
    """True if candidate resolves inside base (no prefix-string bypass)."""
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except (OSError, ValueError):
        return False


def is_blocked_fetch_url(url: str) -> tuple[bool, str]:
    """Return (blocked, reason) for SSRF-sensitive fetch targets."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"file", "ftp", "gopher", "data"}:
        return True, f"scheme '{scheme}' is not allowed"
    if scheme != "https":
        return True, "only https URLs are allowed"

    host = parsed.hostname
    if not host:
        return True, "URL is missing a host"

    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "metadata.google.internal", "metadata"}:
        return True, f"host '{host}' is blocked"

    if lowered.endswith(".internal") or lowered.endswith(".localhost"):
        return True, f"host '{host}' is blocked"

    try:
        ip = ipaddress.ip_address(host)
        if _ip_is_unsafe(ip):
            return True, f"address '{host}' is not a public internet host"
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return True, f"cannot resolve host '{host}'"
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if _ip_is_unsafe(ip):
                return True, f"host '{host}' resolves to a non-public address"

    return False, ""


def _ip_is_unsafe(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


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
    """Fetch and extract readable content from public HTTPS URLs."""

    def __init__(self, max_bytes: int = 1_000_000):
        self.max_bytes = max_bytes
        super().__init__(
            name="web_fetch",
            description="Fetch and extract readable content from a public HTTPS URL.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "HTTPS URL to fetch",
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
        blocked, reason = is_blocked_fetch_url(url)
        if blocked:
            return ToolResult(output=None, error=f"Fetch blocked: {reason}", success=False)

        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
                response = await client.get(url)
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location", "")
                    reblock, rereason = is_blocked_fetch_url(location) if location else (True, "missing redirect")
                    if reblock:
                        return ToolResult(
                            output=None,
                            error=f"Redirect blocked: {rereason}",
                            success=False,
                        )
                    response = await client.get(location)
                response.raise_for_status()

                content = response.text
                if len(content.encode("utf-8", errors="ignore")) > self.max_bytes:
                    content = content[: self.max_bytes]

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
    """Execute allowlisted programs as argv (never via a shell)."""

    # Read-only / informational binaries only. Interpreters and network
    # clients must be opted in explicitly via allowed_commands.
    ALLOWED_COMMANDS = {
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
    }

    def __init__(self, allowed_commands: list[str] | None = None):
        self.custom_allowed = set(allowed_commands) if allowed_commands else set()
        super().__init__(
            name="exec",
            description="Execute an allowlisted program. Shell syntax is rejected. Interpreters are not in the default allowlist.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Program and arguments (no shell operators)",
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

    def allowed_names(self) -> set[str]:
        return set(self.ALLOWED_COMMANDS) | self.custom_allowed

    def parse_command(self, command: str) -> tuple[bool, str, list[str]]:
        """Validate and split a command. Returns (ok, reason, argv)."""
        if not command or not command.strip():
            return False, "empty command", []

        if any(ch in command for ch in _SHELL_METACHARS):
            return False, "shell metacharacters are not allowed", []

        try:
            argv = shlex.split(command, posix=True)
        except ValueError as e:
            return False, f"could not parse command: {e}", []

        if not argv:
            return False, "empty command", []

        exe = Path(argv[0]).name
        if exe not in self.allowed_names():
            return False, f"Command '{exe}' is not in the allowed list", []

        if argv[0] not in {exe, f"/bin/{exe}", f"/usr/bin/{exe}", f"/usr/local/bin/{exe}"}:
            # Allow only bare names or well-known absolute prefixes.
            if not Path(argv[0]).is_absolute() or Path(argv[0]).name != exe:
                return False, f"Command path '{argv[0]}' is not allowed", []

        return True, "", argv

    async def execute(self, command: str, timeout: int = 30) -> ToolResult:
        safe, reason, argv = self.parse_command(command)
        if not safe:
            return ToolResult(output=None, error=f"Safety check failed: {reason}", success=False)

        try:
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
            return ToolResult(output=output, success=result.returncode == 0)
        except subprocess.TimeoutExpired:
            return ToolResult(output=None, error=f"Command timed out after {timeout}s", success=False)
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


class FileReadTool(Tool):
    """Read file contents inside a base-path jail."""

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
        try:
            base = Path(self.base_path).resolve()
            resolved = (Path(self.base_path) / path).resolve()
            if not path_is_inside(resolved, base):
                return ToolResult(
                    output=None,
                    error=f"Access denied: path '{path}' is outside base directory",
                    success=False,
                )

            if not resolved.exists():
                return ToolResult(output=None, error=f"File not found: {path}", success=False)

            if resolved.is_dir():
                return ToolResult(output=None, error=f"Path is a directory: {path}", success=False)

            lines = []
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= limit:
                        lines.append(f"\n... [truncated at {limit} lines]")
                        break
                    lines.append(line)

            return ToolResult(output="".join(lines))
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


class FileWriteTool(Tool):
    """Write content to files inside a base-path jail."""

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
        try:
            base = Path(self.base_path).resolve()
            resolved = (Path(self.base_path) / path).resolve()
            if not path_is_inside(resolved, base):
                return ToolResult(
                    output=None,
                    error=f"Access denied: path '{path}' is outside base directory",
                    success=False,
                )

            if resolved.exists() and not self.allow_overwrite:
                return ToolResult(
                    output=None,
                    error=f"File exists and overwrite is disabled: {path}",
                    success=False,
                )

            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(output=f"File written: {resolved}")
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)


def register_builtin_tools(registry, config: dict | None = None):
    """Register all built-in tools with the given registry."""
    config = config or {}

    exec_config = config.get("exec", {})
    file_config = config.get("file", {})

    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(ExecTool(allowed_commands=exec_config.get("allowed_commands")))
    registry.register(FileReadTool(base_path=file_config.get("base_path", ".")))
    registry.register(
        FileWriteTool(
            base_path=file_config.get("base_path", "."),
            allow_overwrite=file_config.get("allow_overwrite", False),
        )
    )
