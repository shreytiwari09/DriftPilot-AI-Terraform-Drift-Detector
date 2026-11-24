import pytest
from pg_shop import FIXTURES, shop

from driftpilot.database.catalog import (
    Catalog,
    Column,
    Index,
    Policy,
    load_catalog,
    named_index,
    normalize_default,
    normalize_index,
    normalize_type,
    save_catalog,
)
from driftpilot.database.connect import DatabaseError, redact_url, url_from_env


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("int4", "integer"),
        ("INT", "integer"),
        ("int8", "bigint"),
        ("varchar", "character varying"),
        ("varchar(20)", "character varying(20)"),
        ("character varying(255)", "character varying(255)"),
        ("timestamptz", "timestamp with time zone"),
        ("timestamp", "timestamp without time zone"),
        ("bool", "boolean"),
        ("float8", "double precision"),
        ("int4[]", "integer[]"),
        ("numeric(10, 2)", "numeric(10, 2)"),
        ("public.mood", "mood"),
        ("text", "text"),
    ],
)
def test_types_are_normalized(raw: str, expected: str) -> None:
    assert normalize_type(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("'new'::text", "'new'"),
        ("'a'::character varying", "'a'"),
        ("(now())", "now()"),
        ("CURRENT_TIMESTAMP", "now()"),
        ("NULL::text", None),
        ("0", "0"),
        ("false", "false"),
        ("(a + b)", "a + b"),
        ("(1) + (2)", "(1) + (2)"),
        (None, None),
    ],
)
def test_defaults_lose_casts_and_outer_parentheses(raw: str | None, expected: str | None) -> None:
    assert normalize_default(raw) == expected


def test_a_serial_default_becomes_a_flag() -> None:
    column = Column(name="id", type="int4", default="nextval('users_id_seq'::regclass)")
    assert column.serial and column.default is None and column.auto
    identity = Column(name="id", type="integer", identity="by default")
    assert identity.auto and not identity.serial


def test_an_index_is_compared_without_its_name() -> None:
    a = Index(name="a", definition="CREATE INDEX a ON public.t USING btree (x)")
    b = Index(name="b", definition="CREATE  INDEX b ON public.t USING btree (x)")
    assert a.key == b.key == "CREATE INDEX ON public.t USING btree (x)"
    assert named_index("n", normalize_index(a.definition)).startswith("CREATE INDEX n ON")
    unique = normalize_index("CREATE UNIQUE INDEX u ON public.t USING btree (x)")
    assert unique == "CREATE UNIQUE INDEX ON public.t USING btree (x)"
    assert named_index("u", unique).startswith("CREATE UNIQUE INDEX u ON")


def test_policy_roles_are_sorted_and_lowercase() -> None:
    assert Policy(name="p", roles=["B", "a"]).roles == ["a", "b"]


def test_catalog_round_trips_through_json(tmp_path) -> None:
    path = tmp_path / "c.json"
    save_catalog(shop(), path)
    assert load_catalog(path) == shop()


def test_the_fixture_is_the_demo_schema() -> None:
    orders = shop().table("public.orders")
    assert orders is not None and orders.rls_enabled
    assert {c.name for c in orders.columns} == {
        "id", "user_id", "total_cents", "status", "created_at",
    }  # fmt: skip
    id_column = next(c for c in orders.columns if c.name == "id")
    assert id_column.type == "bigint" and id_column.identity == "by default"
    assert [p.name for p in orders.policies] == ["orders_owner_only"]


def test_bookkeeping_and_ignored_tables_are_left_out() -> None:
    catalog = Catalog.model_validate(
        {
            "tables": [
                {"name": n}
                for n in (
                    "users",
                    "schema_migrations",
                    "alembic_version",
                    "driftpilot_runs",
                    "tmp_x",
                )
            ]
        }
    )
    assert [t.name for t in catalog.filtered([]).tables] == ["tmp_x", "users"]
    assert [t.name for t in catalog.filtered(["tmp_*"]).tables] == ["users"]
    assert [t.name for t in catalog.filtered(["public.users"]).tables] == ["tmp_x"]


def test_passwords_are_hidden_in_urls_and_messages() -> None:
    url = "postgresql://driftpilot_ro:s3cr3t!@localhost:5433/appdb"
    assert "s3cr3t" not in redact_url(f"could not connect to {url}")
    assert redact_url(url) == "postgresql://driftpilot_ro:***@localhost:5433/appdb"
    assert "hunter2" not in redact_url("host=db user=x password=hunter2 dbname=y")
    assert "hunter2" not in redact_url("password='hunter2' dbname=y")


def test_a_missing_url_names_the_variable_not_the_value() -> None:
    with pytest.raises(DatabaseError, match="DRIFTPILOT_DB_URL is not set"):
        url_from_env("DRIFTPILOT_DB_URL", {})
    assert url_from_env("X", {"X": " postgresql://u@h/d "}) == "postgresql://u@h/d"


def test_fixture_directory_exists() -> None:
    assert (FIXTURES / "shop_expected.json").exists()
