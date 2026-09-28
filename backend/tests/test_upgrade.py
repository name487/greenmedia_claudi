from sqlalchemy import create_engine, inspect, text

from app.upgrade import add_missing_columns


def test_old_database_gets_new_columns_and_demo_prefix(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:  # gmb_accounts / gmb_reviews as created before the Google integration
        c.execute(text("CREATE TABLE gmb_accounts (id INTEGER PRIMARY KEY, tenant_id INTEGER, client_id INTEGER, location_id VARCHAR(100), "
                       "oauth_ref VARCHAR(200), status VARCHAR(20), last_sync DATETIME, rating FLOAT, review_count INTEGER)"))
        c.execute(text("INSERT INTO gmb_accounts (id, tenant_id, client_id, location_id, status, rating, review_count) VALUES (1, 1, 1, 'locations/1', 'connected', 4.2, 10)"))
        c.execute(text("CREATE TABLE gmb_reviews (id INTEGER PRIMARY KEY, tenant_id INTEGER, client_id INTEGER, external_review_id VARCHAR(100))"))
        c.execute(text("INSERT INTO gmb_reviews VALUES (1, 1, 1, 'g_1_0'), (2, 1, 1, 'g_ab12cd34ef')"))

    added = add_missing_columns(engine)

    assert {"gmb_accounts.connection_id", "gmb_accounts.google_account", "gmb_accounts.title", "gmb_accounts.last_error"} <= set(added)
    assert "connection_id" in {c["name"] for c in inspect(engine).get_columns("gmb_accounts")}
    with engine.connect() as c:
        assert c.execute(text("SELECT google_account, title, last_error, connection_id FROM gmb_accounts")).one() == ("", "", "", None)
        assert [r[0] for r in c.execute(text("SELECT external_review_id FROM gmb_reviews ORDER BY id"))] == ["demo_1_0", "demo_ab12cd34ef"]
    assert add_missing_columns(engine) == []  # idempotent
