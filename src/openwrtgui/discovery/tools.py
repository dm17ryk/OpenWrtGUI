"""Promoted tool cards (decision D9) and Run --help (D3): a program the image or the overlay brings, turned
into named commands with checked parameters. Cards are kept per board in <data>/tools/<board>.json."""

from __future__ import annotations

import posixpath
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from openwrtgui.store import write_atomic

PROGRAM = re.compile(r"/[A-Za-z0-9._/+-]{1,200}")
LITERAL = re.compile(r"[A-Za-z0-9._:=,/@+-]{1,64}")
PARAM = re.compile(r"\{([a-z][a-z0-9_]{0,15})\}")
DEFAULT_TEXT = r"[A-Za-z0-9._:-]{1,64}"
MAX_COMMANDS = 12
MAX_PARAMS = 4
_BOARD = re.compile(r"[^A-Za-z0-9._,-]")


class ToolParam(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: Literal["choice", "text", "number"]
    choices: tuple[str, ...] = ()
    pattern: str | None = None
    minimum: int | None = None
    maximum: int | None = None


class ToolCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    args: tuple[str, ...]
    params: tuple[ToolParam, ...] = ()
    write: bool


class ToolCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    board: str
    path: str
    name: str
    commands: tuple[ToolCommand, ...]


_CARDS = TypeAdapter(list[ToolCard])


def help_command(path: str) -> str:
    if not PROGRAM.fullmatch(path):
        raise ValueError(f"{path} is not a program path")
    return f"timeout 5 {path} --help 2>&1 | head -c 8192"


def _check_param(p: ToolParam) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,15}", p.name):
        raise ValueError(f"{p.name} is not a parameter name (a-z, digits and _, up to 16)")
    if p.kind == "choice" and (not p.choices or not all(LITERAL.fullmatch(c) for c in p.choices)):
        raise ValueError(f"{p.name} needs choices of letters, digits and . _ : = , / @ + -")
    if p.kind == "text" and p.pattern is not None:
        try:
            re.compile(p.pattern)
        except re.error as exc:
            raise ValueError(f"{p.pattern} is not a valid pattern") from exc
    if p.kind == "number" and p.minimum is not None and p.maximum is not None and p.minimum > p.maximum:
        raise ValueError(f"{p.name}: the minimum is above the maximum")


def check_card(card: ToolCard) -> None:
    if not 1 <= len(card.name) <= 40:
        raise ValueError("A card name is 1 to 40 characters")
    if not PROGRAM.fullmatch(card.path):
        raise ValueError(f"{card.path} is not a program path")
    if not 1 <= len(card.commands) <= MAX_COMMANDS:
        raise ValueError(f"A card has 1 to {MAX_COMMANDS} commands")
    for command in card.commands:
        if not 1 <= len(command.label) <= 40:
            raise ValueError("A command label is 1 to 40 characters")
        if len(command.params) > MAX_PARAMS:
            raise ValueError(f"A command has at most {MAX_PARAMS} parameters")
        for p in command.params:
            _check_param(p)
        names = {p.name for p in command.params}
        for arg in command.args:
            if m := PARAM.fullmatch(arg):
                if m.group(1) not in names:
                    raise ValueError(f"{arg} is not a parameter of {command.label}")
            elif not LITERAL.fullmatch(arg):
                raise ValueError(
                    f"{arg} is not a literal (letters, digits and . _ : = , / @ + -) or a {{parameter}}"
                )


def prefill_card(board: str, path: str, usage: str | None) -> ToolCard:
    """Filled from the first Usage: line: the first {a|b|c} group gives one command per alternative, each
    later {…} group a choice parameter; […] parts are left out. Every command is a write until marked."""
    line = next((ln for ln in (usage or "").splitlines() if "usage:" in ln.lower()), "")
    line = re.sub(r"\[[^\]]*\]", " ", line)
    groups = [[c.strip() for c in g.split("|") if c.strip()] for g in re.findall(r"\{([^}]*)\}", line)]
    groups = [g for g in groups if g and all(LITERAL.fullmatch(c) for c in g)]
    name = posixpath.basename(path)[:40] or "tool"
    if not groups:
        return ToolCard(
            board=board, path=path, name=name, commands=(ToolCommand(label="run", args=(), write=True),)
        )
    params = tuple(
        ToolParam(name=f"arg{i}", kind="choice", choices=tuple(g))
        for i, g in enumerate(groups[1 : 1 + MAX_PARAMS], 1)
    )
    commands = tuple(
        ToolCommand(label=sub[:40], args=(sub, *(f"{{{p.name}}}" for p in params)), params=params, write=True)
        for sub in groups[0][:MAX_COMMANDS]
    )
    return ToolCard(board=board, path=path, name=name, commands=commands)


def _value(p: ToolParam, raw: str | None) -> str:
    if raw is None or raw == "":
        raise ValueError(f"{p.name} needs a value")
    if p.kind == "choice":
        if raw not in p.choices:
            raise ValueError(f"{p.name} must be one of {', '.join(p.choices)}")
    elif p.kind == "text":
        pattern = p.pattern or DEFAULT_TEXT
        if not re.fullmatch(pattern, raw):
            raise ValueError(f"{p.name} must match {pattern}")
    else:
        low = p.minimum if p.minimum is not None else -(2**31)
        high = p.maximum if p.maximum is not None else 2**31
        if not re.fullmatch(r"-?\d{1,10}", raw) or not low <= int(raw) <= high:
            raise ValueError(f"{p.name} is a number from {low} to {high}")
    return raw


def tool_command(card: ToolCard, label: str, values: Mapping[str, str]) -> str:
    command = next((c for c in card.commands if c.label == label), None)
    if command is None:
        raise ValueError(f"{card.name} has no command {label}")
    params = {p.name: p for p in command.params}
    words = [card.path]
    for arg in command.args:
        m = PARAM.fullmatch(arg)
        words.append(_value(params[m.group(1)], values.get(m.group(1))) if m else arg)
    return " ".join(shlex.quote(w) for w in words)


class ToolStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _file(self, board: str) -> Path:
        return self._root / f"{_BOARD.sub('_', board)}.json"

    def cards(self, board: str) -> list[ToolCard]:
        path = self._file(board)
        if not path.is_file():
            return []
        try:
            return [c for c in _CARDS.validate_json(path.read_text(encoding="utf-8")) if c.board == board]
        except (OSError, ValueError, ValidationError):
            return []

    def _write(self, board: str, cards: list[ToolCard]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        write_atomic(self._file(board), _CARDS.dump_json(cards, indent=1).decode())

    def save(self, card: ToolCard) -> None:
        check_card(card)
        self._write(card.board, [*(c for c in self.cards(card.board) if c.path != card.path), card])

    def delete(self, board: str, path: str) -> None:
        self._write(board, [c for c in self.cards(board) if c.path != path])
