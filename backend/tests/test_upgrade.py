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


def test_previous_release_gets_token_columns_and_stays_live(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'prev.db'}")
    with engine.begin() as c:  # as created by the release with agency-only Google connections
        c.execute(text("CREATE TABLE google_connections (id INTEGER PRIMARY KEY, tenant_id INTEGER, email VARCHAR(200), refresh_token_enc TEXT, "
                       "scopes TEXT, status VARCHAR(20), last_error TEXT, connected_by INTEGER, created_at DATETIME)"))
        c.execute(text("CREATE TABLE gmb_accounts (id INTEGER PRIMARY KEY, tenant_id INTEGER, client_id INTEGER, location_id VARCHAR(100), "
                       "oauth_ref VARCHAR(200), status VARCHAR(20), last_sync DATETIME, rating FLOAT, review_count INTEGER, connection_id INTEGER, "
                       "google_account VARCHAR(100), title VARCHAR(200), last_error TEXT)"))
        c.execute(text("INSERT INTO gmb_accounts VALUES (1, 1, 1, 'locations/2', '', 'connected', NULL, 4.5, 9, 1, 'accounts/1', 'Shop', '')"))

    added = set(add_missing_columns(engine))

    assert {"gmb_accounts.refresh_token_enc", "gmb_accounts.access_token_enc", "gmb_accounts.token_expires_at", "gmb_accounts.google_email",
            "gmb_accounts.address", "gmb_accounts.maps_uri", "google_connections.access_token_enc", "google_connections.token_expires_at"} <= added
    from app.models import GmbAccount
    from sqlalchemy.orm import Session
    with Session(engine) as db:
        g = db.get(GmbAccount, 1)
        assert g.refresh_token_enc == "" and g.token_expires_at is None and g.is_live  # agency link keeps working
