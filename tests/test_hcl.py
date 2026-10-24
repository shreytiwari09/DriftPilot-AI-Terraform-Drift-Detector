from pathlib import Path

from driftpilot.hcl import add_ignore_changes, find_block, replace_block

DEMO = Path(__file__).parents[1] / "demo"


def test_finds_github_block_in_demo() -> None:
    block = find_block(DEMO / "github", "github_branch_protection.api_main")
    assert block is not None
    assert block.text.startswith('resource "github_branch_protection" "api_main" {')
    assert block.text.rstrip().endswith("}")
    assert "required_approving_review_count = 2" in block.text
    assert "github_team" not in block.text  # stopped at the right brace


def test_nested_dynamic_blocks_in_docker_demo() -> None:
    block = find_block(DEMO / "docker", "docker_container.web")
    assert block is not None
    assert 'dynamic "labels"' in block.text and "networks_advanced" in block.text
    assert 'resource "docker_container" "cache"' not in block.text


def test_index_and_unknown_and_module_addresses() -> None:
    assert find_block(DEMO / "docker", "docker_container.web[0]") is not None
    assert find_block(DEMO / "docker", "docker_container.nope") is None
    assert find_block(DEMO / "docker", "module.app.docker_container.web") is None


def test_braces_in_strings_comments_and_heredocs(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "x" "a" {\n'
        '  s = "not a } brace"\n'
        "  # } comment\n"
        "  /* { block } */\n"
        "  doc = <<-EOT\n"
        "    } heredoc {\n"
        "  EOT\n"
        "}\n"
        'resource "x" "b" {}\n'
    )
    block = find_block(tmp_path, "x.a")
    assert block.text.endswith("EOT\n}")


def test_replace_block_keeps_rest_of_file(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('# top\nresource "x" "a" {\n  v = 1\n}\n\nresource "x" "b" {}\n')
    block = find_block(tmp_path, "x.a")
    new = replace_block(block, 'resource "x" "a" {\n  v = 2\n}')
    assert new == '# top\nresource "x" "a" {\n  v = 2\n}\n\nresource "x" "b" {}\n'


def test_add_ignore_changes_creates_lifecycle() -> None:
    out = add_ignore_changes('resource "x" "a" {\n  v = 1\n}', "restart")
    assert (
        out
        == 'resource "x" "a" {\n  v = 1\n\n  lifecycle {\n    ignore_changes = [restart]\n  }\n}'
    )


def test_add_ignore_changes_extends_existing_list_once() -> None:
    block = 'resource "x" "a" {\n  lifecycle {\n    ignore_changes = [tags]\n  }\n}'
    out = add_ignore_changes(block, "restart")
    assert "ignore_changes = [tags, restart]" in out
    assert add_ignore_changes(out, "restart") == out


def test_add_ignore_changes_to_lifecycle_without_list() -> None:
    block = 'resource "x" "a" {\n  lifecycle {\n    prevent_destroy = true\n  }\n}'
    out = add_ignore_changes(block, "restart")
    assert "ignore_changes = [restart]" in out and "prevent_destroy = true" in out
