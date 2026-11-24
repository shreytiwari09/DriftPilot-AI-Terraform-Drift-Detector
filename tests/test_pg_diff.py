from pg_shop import by_attr, edit, findings, shop

from driftpilot.collector import finding_id
from driftpilot.database.catalog import Column, Constraint, Grant, Index, Policy, Table

USERS, ORDERS = "postgres.public.users", "postgres.public.orders"


def test_the_same_schema_has_no_findings() -> None:
    assert findings(shop(), shop()) == []


def test_rls_switched_off_is_one_table_level_finding() -> None:
    live = edit(shop(), "orders", lambda t: setattr(t, "rls_enabled", False))
    [f] = findings(shop(), live)
    assert (f.resource_type, f.address, f.attribute_path) == (
        "pg_table_rls", ORDERS, "row_level_security",
    )  # fmt: skip
    assert (f.provider, f.change_kind, f.before, f.after) == ("postgres", "modified", True, False)
    assert f.id == finding_id(ORDERS, "row_level_security")


def test_not_null_dropped_is_a_column_change() -> None:
    def drop_not_null(t: Table) -> None:
        next(c for c in t.columns if c.name == "email").nullable = True

    [f] = findings(shop(), edit(shop(), "users", drop_not_null))
    assert (f.resource_type, f.address, f.attribute_path) == (
        "pg_column", f"{USERS}.email", "nullable",
    )  # fmt: skip
    assert (f.before, f.after) == (False, True)


def test_a_new_column_is_added_with_its_definition() -> None:
    live = edit(
        shop(), "users", lambda t: t.columns.append(Column(name="ssn", type="text", nullable=True))
    )
    [f] = findings(shop(), live)
    assert (f.resource_type, f.address, f.attribute_path) == ("pg_column", f"{USERS}.ssn", None)
    assert f.change_kind == "added" and f.before is None
    assert f.after == {"type": "text", "nullable": True}


def test_a_missing_column_is_deleted() -> None:
    live = edit(shop(), "users", lambda t: t.columns.pop())
    [f] = findings(shop(), live)
    assert f.change_kind == "deleted" and f.after is None and f.address == f"{USERS}.created_at"


def test_a_grant_to_public_is_added() -> None:
    live = edit(
        shop(), "orders", lambda t: t.grants.append(Grant(grantee="PUBLIC", privilege="select"))
    )
    [f] = findings(shop(), live)
    assert (f.resource_type, f.attribute_path, f.change_kind) == (
        "pg_grant", "grant:PUBLIC:SELECT", "added",
    )  # fmt: skip
    assert f.after == {"grantee": "PUBLIC", "privilege": "SELECT"}


def test_a_revoked_grant_is_deleted() -> None:
    live = edit(shop(), "orders", lambda t: t.grants.pop(0))
    [f] = findings(shop(), live)
    assert f.attribute_path == "grant:app_readonly:SELECT" and f.change_kind == "deleted"


def test_a_dropped_policy_is_deleted_and_a_changed_one_is_modified() -> None:
    [dropped] = findings(shop(), edit(shop(), "orders", lambda t: t.policies.clear()))
    assert (dropped.resource_type, dropped.attribute_path, dropped.change_kind) == (
        "pg_policy", "policy:orders_owner_only", "deleted",
    )  # fmt: skip
    assert dropped.before["roles"] == ["app_writer"]

    def loosen(t: Table) -> None:
        t.policies[0].using = "true"

    [changed] = findings(shop(), edit(shop(), "orders", loosen))
    assert changed.change_kind == "modified" and changed.after["using"] == "true"


def test_constraints_are_matched_by_definition_not_by_name() -> None:
    def rename(t: Table) -> None:
        for c in t.constraints:
            c.name = f"renamed_{c.name}"
        for i in t.indexes:
            i.name = f"renamed_{i.name}"

    assert findings(shop(), edit(shop(), "orders", rename)) == []


def test_a_dropped_constraint_and_a_dropped_index() -> None:
    live = edit(
        shop(),
        "orders",
        lambda t: (
            t.constraints.__delitem__(slice(1, 2)),  # the foreign key
            t.indexes.clear(),
        ),
    )
    found = by_attr(findings(shop(), live))
    fk = found[(ORDERS, "constraint:FOREIGN KEY (user_id) REFERENCES users(id)")]
    assert fk.resource_type == "pg_constraint" and fk.change_kind == "deleted"
    assert fk.before["name"] == "orders_user_id_fkey"
    index = next(f for f in found.values() if f.resource_type == "pg_index")
    assert index.change_kind == "deleted" and index.before["name"] == "orders_user_id_idx"


def test_an_extra_constraint_and_index_are_added() -> None:
    live = edit(
        shop(),
        "users",
        lambda t: (
            t.constraints.append(
                Constraint(name="c", kind="check", definition="CHECK ((length(email) > 3))")
            ),
            t.indexes.append(
                Index(name="i", definition="CREATE INDEX i ON public.users USING btree (full_name)")
            ),
        ),
    )
    kinds = {(f.resource_type, f.change_kind) for f in findings(shop(), live)}
    assert kinds == {("pg_constraint", "added"), ("pg_index", "added")}


def test_a_type_change_is_modified() -> None:
    def widen(t: Table) -> None:
        next(c for c in t.columns if c.name == "total_cents").type = "bigint"

    [f] = findings(shop(), edit(shop(), "orders", widen))
    assert (f.attribute_path, f.before, f.after) == ("type", "integer", "bigint")


def test_serial_and_identity_by_default_are_the_same() -> None:
    def to_serial(t: Table) -> None:
        col = next(c for c in t.columns if c.name == "id")
        col.identity, col.serial = None, True

    assert findings(shop(), edit(shop(), "orders", to_serial)) == []


def test_identity_always_versus_by_default_is_a_change() -> None:
    def always(t: Table) -> None:
        next(c for c in t.columns if c.name == "id").identity = "always"

    [f] = findings(shop(), edit(shop(), "orders", always))
    assert (f.attribute_path, f.before, f.after) == ("auto", "sequence", "identity always")


def test_owner_and_comment_differences_are_reported_as_table_settings() -> None:
    def change(t: Table) -> None:
        t.owner, t.comment = "someone_else", "new comment"

    found = by_attr(findings(shop(), edit(shop(), "users", change)))
    assert set(found) == {(USERS, "owner"), (USERS, "comment")}
    assert all(f.resource_type == "pg_table" for f in found.values())


def test_an_empty_comment_equals_no_comment() -> None:
    assert findings(shop(), edit(shop(), "orders", lambda t: setattr(t, "comment", ""))) == []


def test_extra_and_missing_tables() -> None:
    extra = shop().model_copy(deep=True)
    extra.tables.append(Table(name="scratch_notes", columns=[Column(name="id", type="int4")]))
    [added] = findings(shop(), extra)
    assert (added.resource_type, added.address, added.change_kind) == (
        "pg_table", "postgres.public.scratch_notes", "added",
    )  # fmt: skip
    assert added.attribute_path is None and "id" in added.after["columns"]

    fewer = shop().model_copy(deep=True)
    fewer.tables = [t for t in fewer.tables if t.name != "orders"]
    [gone] = findings(shop(), fewer)
    assert gone.change_kind == "deleted" and gone.address == ORDERS and gone.after is None


def test_a_new_table_with_a_public_grant_still_shows_the_grant() -> None:
    extra = shop().model_copy(deep=True)
    extra.tables.append(Table(name="notes", grants=[Grant(grantee="PUBLIC", privilege="SELECT")]))
    types = sorted(f.resource_type for f in findings(shop(), extra))
    assert types == ["pg_grant", "pg_table"]


def test_finding_ids_are_stable_and_unique() -> None:
    live = edit(
        edit(shop(), "orders", lambda t: setattr(t, "rls_enabled", False)),
        "users",
        lambda t: t.columns.append(Column(name="ssn", type="text")),
    )
    ids = [f.id for f in findings(shop(), live)]
    assert ids == [f.id for f in findings(shop(), live)]
    assert len(set(ids)) == len(ids) == 2


def test_policy_summary_is_compact() -> None:
    p = Policy(name="p", command="SELECT", roles=["public"], using="true")
    assert p.summary() == {
        "command": "SELECT",
        "permissive": True,
        "roles": ["public"],
        "using": "true",
    }
