"""Guardrails for untrusted text: clean it before an LLM sees it, and spot injection attempts.

DriftPilot reads text anyone with write access can set (descriptions, tags, names, code). A prompt
injection hides instructions in it. These helpers are the first layers; the deterministic ones
(never-soften list, suspicious-input rule in `triage/policy.py`) do not rely on the model.
"""

import re
import unicodedata
from typing import Any

VALUE_LIMIT = 2000  # longest value shown to a model (policy documents are long)
CODE_LIMIT = 20000  # longest block of Terraform code shown to a model
TRUNCATED = "…[truncated]"

# Zero-width and bidirectional control characters: invisible to a reviewer, readable to a model.
_HIDDEN = re.compile("[​-‏‪-‮⁦-⁩﻿]")
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_SPACES = re.compile(r"\s+")

_SIGNALS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.I)
    for name, pattern in {
        "ignore-instructions": (
            r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}"
            r"\b(?:instructions?|prompts?|rules|guidelines|directions)\b"
        ),
        "role-override": r"\byou are now\b|\bnew instructions?\s*:|\bpretend (?:to be|you)\b",
        "system-prompt": r"\bsystem prompt\b|\bdeveloper message\b",
        "mark-as-safe": (
            r"\b(?:mark|classify|label|treat|report|rate|set) (?:this|it|these|them)\b[^.\n]{0,30}"
            r"\b(?:as|to) (?:safe|noise|low|benign|harmless|approved|expected|not real|none)\b"
        ),
        "as-an-ai": r"\bas an ai\b|\bas a language model\b",
        "role-tag": (
            r"</?\s*(?:system|assistant|user|instructions?|developer)\s*>"
            r"|\[/?(?:inst|sys)\]|<\|im_(?:start|end)\|>"
        ),
        "do-not-report": (
            r"\b(?:do not|don't|never|no need to)\s+(?:report|flag|alert|mention|escalate|revert)\b"
        ),
        "fake-verdict": r"is_real_drift|recommended_action|\"verdicts?\"\s*:",
        "approval-claim": (
            r"\b(?:pre-?approved|approved|authori[sz]ed) by (?:the )?"
            r"(?:security|ciso|cto|admin|management|compliance)\b"
        ),
    }.items()
}


def _strings(value: Any):
    """Every string in a nested value, including dict keys."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def sanitize_text(text: str, max_len: int = 500, keep_layout: bool = False) -> str:
    """Remove hidden characters and HTML comments, collapse whitespace, cap the length.

    `keep_layout` keeps line breaks and indentation, for code.
    """
    text = _HIDDEN.sub("", text)
    text = _HTML_COMMENT.sub("", text)
    if not keep_layout:
        text = _SPACES.sub(" ", text).strip()
    return text if len(text) <= max_len else text[:max_len] + TRUNCATED


def sanitize_value(value: Any, max_len: int = 500, keep_layout: bool = False) -> Any:
    """`sanitize_text` over every string in a dict/list/str; other types stay as they are."""
    if isinstance(value, str):
        return sanitize_text(value, max_len, keep_layout)
    if isinstance(value, dict):
        return {
            sanitize_value(k, max_len, keep_layout): sanitize_value(v, max_len, keep_layout)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(v, max_len, keep_layout) for v in value]
    return value


def injection_signals(value: Any) -> list[str]:
    """Names of injection-looking patterns found in `value`. A hint for humans, never a gate.

    The text is normalised first (hidden characters out, comment markers dropped, full-width
    letters folded), so the usual obfuscations do not hide a phrase.
    """
    found: list[str] = []

    def add(name: str) -> None:
        if name not in found:
            found.append(name)

    for raw in _strings(value):
        if _HIDDEN.search(raw):
            add("hidden-characters")
        if "<!--" in raw:
            add("html-comment")
        text = unicodedata.normalize("NFKC", _HIDDEN.sub("", raw))
        text = _SPACES.sub(" ", text.replace("<!--", " ").replace("-->", " "))
        for name, pattern in _SIGNALS.items():
            if pattern.search(text):
                add(name)
    return found
