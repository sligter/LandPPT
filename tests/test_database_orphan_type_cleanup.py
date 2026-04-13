from landppt.database.database import (
    _drop_postgres_orphan_composite_type,
    _extract_duplicate_pg_type_name,
)


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConnection:
    def __init__(self, orphan_type_oid=None):
        self.dialect = type("Dialect", (), {"name": "postgresql"})()
        self.orphan_type_oid = orphan_type_oid
        self.executed = []

    def execute(self, stmt, params=None):
        sql_text = str(stmt)
        self.executed.append((sql_text, params))
        if "SELECT t.oid" in sql_text:
            return _FakeScalarResult(self.orphan_type_oid)
        return _FakeScalarResult(None)


def test_extract_duplicate_pg_type_name_from_postgres_error():
    error = Exception(
        'duplicate key value violates unique constraint "pg_type_typname_nsp_index"\n'
        "DETAIL:  Key (typname, typnamespace)=(invite_codes, 2200) already exists."
    )

    assert _extract_duplicate_pg_type_name(error) == "invite_codes"


def test_extract_duplicate_pg_type_name_returns_none_for_other_errors():
    error = Exception("some unrelated database error")

    assert _extract_duplicate_pg_type_name(error) is None


def test_drop_postgres_orphan_composite_type_drops_when_orphan_exists():
    connection = _FakeConnection(orphan_type_oid=12345)

    dropped = _drop_postgres_orphan_composite_type(
        connection,
        table_name="invite_codes",
        schema="public",
    )

    assert dropped is True
    assert len(connection.executed) == 2
    assert "SELECT t.oid" in connection.executed[0][0]
    assert "DROP TYPE IF EXISTS" in connection.executed[1][0]
    assert '"public"."invite_codes"' in connection.executed[1][0]


def test_drop_postgres_orphan_composite_type_skips_when_no_orphan_exists():
    connection = _FakeConnection(orphan_type_oid=None)

    dropped = _drop_postgres_orphan_composite_type(
        connection,
        table_name="invite_codes",
        schema="public",
    )

    assert dropped is False
    assert len(connection.executed) == 1
    assert "SELECT t.oid" in connection.executed[0][0]
