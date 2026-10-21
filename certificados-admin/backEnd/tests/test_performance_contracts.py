"""Query-count contracts that prevent remote PostgreSQL latency regressions."""

from __future__ import annotations

from sqlalchemy import event


def _count_selects(engine, call) -> int:
    statements: list[str] = []

    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_execute)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
    return len(statements)


def test_dashboard_uses_one_auth_query_and_one_aggregate_query(client, auth_headers):
    from database import db
    from database.engine import get_engine

    engine = get_engine(db._current_database_url())
    selects = _count_selects(
        engine,
        lambda: _assert_ok(client.get("/admin/stats")),
    )
    assert selects == 2


def test_recent_list_does_not_query_responsible_per_certificate(client, auth_headers):
    from database import db
    from database.engine import get_engine

    current = db.get_admin_user_by_username("secretaria")
    assert current is not None
    db.insert_certificates(
        [
            {
                "unique_code": "CERT-2026-PERF01",
                "participant_name": "Pessoa Sintética",
                "event_name": "Evento Sintético",
                "issue_date": "2026-08-15",
                "issued_by": current["id"],
            }
        ]
    )
    engine = get_engine(db._current_database_url())
    selects = _count_selects(
        engine,
        lambda: _assert_ok(client.get("/admin/recent-certificates")),
    )
    assert selects == 2


def _assert_ok(response) -> None:
    assert response.status_code == 200, response.text


def test_pool_pre_ping_is_explicitly_configurable(monkeypatch):
    from database import config

    monkeypatch.setenv("DB_POOL_PRE_PING", "false")
    assert config.pool_settings()["pool_pre_ping"] is False
    monkeypatch.setenv("DB_POOL_PRE_PING", "true")
    assert config.pool_settings()["pool_pre_ping"] is True
