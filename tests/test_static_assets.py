def test_frontend_assets_bypass_stale_release_cache(client):
    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-store"
    assert "/styles.css?v=20260731-ledger-filter-1" in index.text
    assert "/app.js?v=20260731-ledger-filter-1" in index.text

    javascript = client.get("/app.js?v=20260730-institutional-2")
    assert javascript.status_code == 200
    assert javascript.headers["cache-control"] == "no-store"
    assert "/auth-utils.js?v=20260730-institutional-2" in javascript.text
    assert "/input-utils.js?v=20260730-institutional-2" in javascript.text
