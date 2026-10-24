"""Strip sensitive values before they are shown or sent to an LLM.

Two layers:
1. Values Terraform marks sensitive (`before_sensitive` / `after_sensitive` in plan JSON).
2. A pattern safety net for secrets providers don't mark (tokens, keys, `password=...`).
"""

import re
from typing import Any

REDACTED = "<redacted>"

_SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub classic/OAuth/app tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),  # GitHub fine-grained tokens
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),  # AWS access key IDs
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    # KEY=value / key: value where the key mentions a secret, e.g. DB_PASSWORD=..., SECRET_KEY: ...
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY)[A-Z0-9_]*)(\s*[=:]\s*)\S+"
    ),
]
_SECRET_KEY_NAMES = re.compile(r"(?i)^(password|passwd|secret|token|api_key|apikey|private_key)$")


def mask_sensitive(value: Any, marker: Any) -> Any:
    """Replace parts of `value` that Terraform's sensitivity `marker` flags.

    The marker mirrors the value's shape: `True` means "this whole value is sensitive",
    a dict/list holds markers for the children, anything else means "not sensitive".
    """
    if marker is True:
        return REDACTED
    if isinstance(value, dict) and isinstance(marker, dict):
        return {k: mask_sensitive(v, marker.get(k)) for k, v in value.items()}
    if isinstance(value, list) and isinstance(marker, list):
        return [
            mask_sensitive(v, marker[i] if i < len(marker) else None) for i, v in enumerate(value)
        ]
    return value


def scrub_patterns(value: Any) -> Any:
    """Redact anything that looks like a secret, recursively."""
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.groups == 2:
                value = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
            else:
                value = pattern.sub(REDACTED, value)
        return value
    if isinstance(value, dict):
        return {
            k: REDACTED
            if _SECRET_KEY_NAMES.match(str(k)) and v not in (None, "")
            else scrub_patterns(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub_patterns(v) for v in value]
    return value


def redact(value: Any, marker: Any = None) -> Any:
    """Both layers: Terraform's sensitivity marks, then the pattern safety net."""
    return scrub_patterns(mask_sensitive(value, marker))


def is_marked_sensitive(marker: Any) -> bool:
    """True if any part of a sensitivity marker is set."""
    if marker is True:
        return True
    if isinstance(marker, dict):
        return any(is_marked_sensitive(m) for m in marker.values())
    if isinstance(marker, list):
        return any(is_marked_sensitive(m) for m in marker)
    return False
