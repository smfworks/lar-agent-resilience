# Contributing to LAR — Local Agent Resilience

Thank you for your interest in contributing! This project provides a production-grade reference implementation for resilient agent design on Linux.

## Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/smfworks/lar-agent-resilience.git
cd lar-agent-resilience
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=agent_resilience --cov-report=term-missing

# Run a specific test file
python -m pytest tests/test_circuit_breaker.py -v
```

## Code Style

- Use type hints on all public functions
- Follow PEP 8 (enforced by ruff)
- Keep functions focused and well-documented
- Add tests for all new functionality

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests for your changes
3. Ensure all tests pass: `python -m pytest tests/ -v`
4. Ensure linting passes: `ruff check src/ tests/`
5. Write clear commit messages following conventional commits
6. Open a PR with a description of what changed and why

## Architecture

The codebase follows a modular design:

- `src/agent_resilience/` — Core library
  - `agent.py` — Agent loop with checkpoint/resume
  - `config.py` — Configuration management with env var expansion
  - `circuit_breaker.py` — Misfire detection and circuit breaking
  - `health.py` — Health check system
  - `tools/` — Built-in tools (web search, exec, file I/O)
  - `observatory.py` — Observability dashboard
- `tests/` — Comprehensive test suite (232 tests)
- `skills/` — Hermes resilience skill
- `config.example.yaml` — Example configuration

## License

MIT — see [LICENSE](./LICENSE)