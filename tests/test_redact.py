from driftpilot.redact import REDACTED, is_marked_sensitive, mask_sensitive, redact, scrub_patterns


def test_marker_true_redacts_whole_value() -> None:
    assert mask_sensitive({"a": 1}, True) == REDACTED


def test_marker_redacts_nested_fields_only() -> None:
    value = {"name": "db", "password": "hunter2", "tags": ["a", "b"]}
    marker = {"password": True, "tags": [False, True]}
    assert mask_sensitive(value, marker) == {
        "name": "db",
        "password": REDACTED,
        "tags": ["a", REDACTED],
    }


def test_patterns_catch_tokens_and_keys() -> None:
    token = "ghp_" + "a" * 36
    pat = "github_pat_" + "B" * 60
    aws = "AKIA" + "ABCDEFGHIJKLMNOP"
    text = f"t={token} p={pat} k={aws}"
    out = scrub_patterns(text)
    assert token not in out and pat not in out and aws not in out


def test_secret_assignments_keep_key_name() -> None:
    assert scrub_patterns("password=hunter2") == f"password={REDACTED}"
    assert scrub_patterns("DB_PASSWORD=hunter2") == f"DB_PASSWORD={REDACTED}"
    assert scrub_patterns("SECRET_KEY: abc") == f"SECRET_KEY: {REDACTED}"
    assert scrub_patterns(["API_KEY=x", "PORT=80"]) == [f"API_KEY={REDACTED}", "PORT=80"]


def test_private_key_block() -> None:
    key = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    assert scrub_patterns(f"x {key} y") == f"x {REDACTED} y"


def test_secret_key_names_in_dicts() -> None:
    assert scrub_patterns({"token": "abc", "name": "x"}) == {"token": REDACTED, "name": "x"}


def test_ordinary_values_untouched() -> None:
    value = {"memory": 256, "restart": "unless-stopped", "labels": ["managed-by=terraform"]}
    assert redact(value) == value


def test_is_marked_sensitive() -> None:
    assert is_marked_sensitive({"a": {"b": [False, True]}})
    assert not is_marked_sensitive({"a": False, "b": []})
    assert not is_marked_sensitive(None)
