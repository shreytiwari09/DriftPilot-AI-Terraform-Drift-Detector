"""Find and edit resource blocks in `.tf` files as raw text.

Raw text (not a parsed tree) because both the LLM and the patch need the code exactly as written.
"""

import re
from dataclasses import dataclass
from pathlib import Path

_INDEX = re.compile(r"\[[^\]]*\]$")


@dataclass(frozen=True)
class Block:
    path: Path
    start: int  # offset of `resource`
    end: int  # offset just after the closing `}`
    text: str


def _split_address(address: str) -> tuple[str, str] | None:
    """`type.name` or `type.name[0]` → (type, name). Module addresses aren't supported yet."""
    parts = _INDEX.sub("", address).split(".")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _block_end(text: str, open_brace: int) -> int:
    """Offset just after the `}` matching `text[open_brace]`, skipping strings/comments/heredocs."""
    depth, i, n = 0, open_brace, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "#" or text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i == -1 else i
        elif text.startswith("/*", i):
            i = text.find("*/", i + 2)
            i = n if i == -1 else i + 1
        elif text.startswith("<<", i) and (m := re.match(r"<<-?([A-Za-z_]\w*)\n", text[i:])):
            end = re.compile(rf"^\s*{m.group(1)}\s*$", re.M).search(text, i + m.end())
            i = n if end is None else end.end() - 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced braces")


def module_name(address: str) -> str | None:
    """`module.billing.github_repository.default[0]` → "billing" (the call in this directory)."""
    match = re.match(r"module\.([A-Za-z0-9_-]+)(?:\[[^\]]*\])?\.", address)
    return match.group(1) if match else None


def find_block(directory: Path, address: str) -> Block | None:
    """The resource block for `address` in `directory/*.tf`, or None."""
    split = _split_address(address)
    if split is None:
        return None
    rtype, name = split
    header = re.compile(
        rf'^[ \t]*resource\s+"{re.escape(rtype)}"\s+"{re.escape(name)}"\s*\{{', re.M
    )
    return _find(directory, header)


def find_module_call(directory: Path, name: str) -> Block | None:
    """The `module "<name>" { ... }` block in `directory/*.tf`, or None."""
    return _find(directory, re.compile(rf'^[ \t]*module\s+"{re.escape(name)}"\s*\{{', re.M))


def find_owner_block(directory: Path, address: str) -> tuple[Block, bool] | None:
    """The code to edit for `address`: its resource block, or the module call that creates it.

    Returns (block, is_module_call).
    """
    if (name := module_name(address)) is not None:
        block = find_module_call(directory, name)
        return (block, True) if block else None
    block = find_block(directory, address)
    return (block, False) if block else None


def _find(directory: Path, header: re.Pattern[str]) -> Block | None:
    for path in sorted(directory.glob("*.tf")):
        text = path.read_text()
        if m := header.search(text):
            start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
            end = _block_end(text, m.end() - 1)
            return Block(path, start, end, text[start:end])
    return None


def replace_block(block: Block, new_text: str) -> str:
    """Full new content of `block.path` with the block replaced."""
    text = block.path.read_text()
    return text[: block.start] + new_text.strip() + text[block.end :]


def add_ignore_changes(block_text: str, attribute: str) -> str:
    """Add `attribute` to `lifecycle { ignore_changes = [...] }`, creating the block if missing."""
    ignore = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", block_text)
    if ignore:
        items = [i.strip() for i in ignore.group(1).split(",") if i.strip()]
        if attribute in items:
            return block_text
        new_list = ", ".join([*items, attribute])
        return block_text[: ignore.start(1)] + new_list + block_text[ignore.end(1) :]
    lifecycle = re.search(r"\blifecycle\s*\{", block_text)
    if lifecycle:
        insert_at = lifecycle.end()
        return (
            block_text[:insert_at]
            + f"\n    ignore_changes = [{attribute}]"
            + block_text[insert_at:]
        )
    body = block_text.rstrip()
    assert body.endswith("}")
    return body[:-1].rstrip() + (
        f"\n\n  lifecycle {{\n    ignore_changes = [{attribute}]\n  }}\n}}"
    )
