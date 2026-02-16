"""Event system for notifications.

Provides an EventEmitter base class that CLI uses for terminal output.
Future messenger handlers (Telegram, Discord, Slack) will extend this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EventEmitter(ABC):
    """Base event emitter for AAT notifications.

    Subclass this to create CLI, Telegram, Discord, Slack handlers.
    """

    @abstractmethod
    def info(self, message: str) -> None:
        """Informational message."""
        ...

    @abstractmethod
    def success(self, message: str) -> None:
        """Success message."""
        ...

    @abstractmethod
    def warning(self, message: str) -> None:
        """Warning message."""
        ...

    @abstractmethod
    def error(self, message: str) -> None:
        """Error message."""
        ...

    @abstractmethod
    def step_start(self, step_num: int, total: int, description: str) -> None:
        """A test step is starting."""
        ...

    @abstractmethod
    def step_result(
        self, step_num: int, passed: bool, description: str, error: str | None = None
    ) -> None:
        """A test step completed."""
        ...

    @abstractmethod
    def progress(self, label: str, current: int, total: int) -> None:
        """Progress update (e.g. analyzing documents 2/5)."""
        ...

    @abstractmethod
    def prompt(self, question: str, options: list[str] | None = None) -> str:
        """Ask user for input. Returns user's response."""
        ...

    @abstractmethod
    def section(self, title: str) -> None:
        """Start a new section (visual separator)."""
        ...


class CLIEventHandler(EventEmitter):
    """Terminal output handler using typer/rich."""

    def info(self, message: str) -> None:
        import typer

        typer.echo(message)

    def success(self, message: str) -> None:
        import typer

        typer.echo(typer.style(f"  [OK] {message}", fg=typer.colors.GREEN))

    def warning(self, message: str) -> None:
        import typer

        typer.echo(typer.style(f"  [WARN] {message}", fg=typer.colors.YELLOW))

    def error(self, message: str) -> None:
        import typer

        typer.echo(typer.style(f"  [ERROR] {message}", fg=typer.colors.RED), err=True)

    def step_start(self, step_num: int, total: int, description: str) -> None:
        import typer

        typer.echo(f"  Step {step_num}/{total}: {description}...", nl=False)

    def step_result(
        self, step_num: int, passed: bool, description: str, error: str | None = None
    ) -> None:
        import typer

        if passed:
            typer.echo(typer.style(" OK", fg=typer.colors.GREEN))
        else:
            typer.echo(typer.style(" FAILED", fg=typer.colors.RED))
            if error:
                typer.echo(typer.style(f"         Reason: {error}", fg=typer.colors.RED))

    def progress(self, label: str, current: int, total: int) -> None:
        import typer

        typer.echo(f"  ({current}/{total}) {label}")

    def prompt(self, question: str, options: list[str] | None = None) -> str:
        import typer

        if options:
            for i, opt in enumerate(options, 1):
                typer.echo(f"  [{i}] {opt}")
        response: str = typer.prompt(question)
        return response

    def section(self, title: str) -> None:
        import typer

        typer.echo(f"\n{'=' * 50}")
        typer.echo(f"  {title}")
        typer.echo(f"{'=' * 50}")


class MessageBuffer(EventEmitter):
    """Collects messages for batch sending (messenger integration).

    Future use: collect all messages, then send as one formatted message
    to Telegram/Discord/Slack.
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def info(self, message: str) -> None:
        self.messages.append({"type": "info", "text": message})

    def success(self, message: str) -> None:
        self.messages.append({"type": "success", "text": message})

    def warning(self, message: str) -> None:
        self.messages.append({"type": "warning", "text": message})

    def error(self, message: str) -> None:
        self.messages.append({"type": "error", "text": message})

    def step_start(self, step_num: int, total: int, description: str) -> None:
        self.messages.append(
            {
                "type": "step_start",
                "step": step_num,
                "total": total,
                "text": description,
            }
        )

    def step_result(
        self, step_num: int, passed: bool, description: str, error: str | None = None
    ) -> None:
        self.messages.append(
            {
                "type": "step_result",
                "step": step_num,
                "passed": passed,
                "text": description,
                "error": error,
            }
        )

    def progress(self, label: str, current: int, total: int) -> None:
        self.messages.append(
            {
                "type": "progress",
                "text": label,
                "current": current,
                "total": total,
            }
        )

    def prompt(self, question: str, options: list[str] | None = None) -> str:
        self.messages.append({"type": "prompt", "text": question, "options": options})
        return ""  # messenger handlers will override with async input

    def section(self, title: str) -> None:
        self.messages.append({"type": "section", "text": title})

    def to_text(self) -> str:
        """Format all messages as plain text (for messenger send)."""
        lines: list[str] = []
        for msg in self.messages:
            mtype = msg["type"]
            if mtype == "section":
                lines.append(f"--- {msg['text']} ---")
            elif mtype == "success":
                lines.append(f"[OK] {msg['text']}")
            elif mtype == "error":
                lines.append(f"[ERROR] {msg['text']}")
            elif mtype == "step_result":
                status = "OK" if msg["passed"] else "FAILED"
                lines.append(f"  Step {msg['step']}: {status} — {msg['text']}")
            else:
                lines.append(msg.get("text", ""))
        return "\n".join(lines)
