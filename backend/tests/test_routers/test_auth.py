def test_register_user(unauthenticated_client):
    response = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "securepass"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert "id" in data
    assert "password_hash" not in data
    assert "password" not in data


def test_register_duplicate_email_fails(unauthenticated_client):
    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "securepass"},
    )
    response = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "differentpass"},
    )
    assert response.status_code == 409


def test_login_returns_token(unauthenticated_client):
    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "securepass"},
    )
    response = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "securepass"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


def test_login_wrong_password_fails(unauthenticated_client):
    unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "wrongpw@example.com", "password": "securepass"},
    )
    response = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpw@example.com", "password": "badpass"},
    )
    assert response.status_code == 401


def test_login_unknown_user_fails(unauthenticated_client):
    response = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert response.status_code == 401


def test_me_returns_current_user(client, test_user):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["id"] == test_user.id


def test_me_without_token_fails(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_jobs_require_auth(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/jobs")
    assert response.status_code == 401


def test_jobs_create_requires_auth(unauthenticated_client):
    response = unauthenticated_client.post(
        "/api/v1/jobs",
        json={"job_type": "topic", "topic": "test"},
    )
    assert response.status_code == 401


def test_jobs_with_invalid_token_fails(unauthenticated_client):
    response = unauthenticated_client.get(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


# E-5.2.X — self-service tier flip with mock payment (D-050)


def test_me_includes_tier(client, test_user):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    # Default tier for new users is 'free'.
    assert data["tier"] == "free"


def test_change_tier_free_to_studio(client, test_user, db):
    response = client.put("/api/v1/auth/me/tier", json={"tier": "studio"})
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "studio"
    assert data["mock_payment_mode"] is True

    # Verify the DB row was updated.
    db.refresh(test_user)
    assert test_user.tier == "studio"

    # Verify subsequent /auth/me reflects the new tier.
    me_response = client.get("/api/v1/auth/me")
    assert me_response.json()["tier"] == "studio"


def test_change_tier_to_pro(client, test_user, db):
    response = client.put("/api/v1/auth/me/tier", json={"tier": "pro"})
    assert response.status_code == 200
    assert response.json()["tier"] == "pro"
    db.refresh(test_user)
    assert test_user.tier == "pro"


def test_change_tier_downgrade(client, test_user, db):
    # Upgrade first
    client.put("/api/v1/auth/me/tier", json={"tier": "studio"})
    # Then downgrade
    response = client.put("/api/v1/auth/me/tier", json={"tier": "free"})
    assert response.status_code == 200
    assert response.json()["tier"] == "free"


def test_change_tier_idempotent(client, test_user):
    response = client.put("/api/v1/auth/me/tier", json={"tier": "free"})
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "free"
    assert "No change" in data["message"]


def test_change_tier_unknown_value_rejected(client, test_user):
    response = client.put("/api/v1/auth/me/tier", json={"tier": "enterprise"})
    assert response.status_code == 422  # pydantic regex rejection


def test_change_tier_unauthenticated(unauthenticated_client):
    response = unauthenticated_client.put(
        "/api/v1/auth/me/tier", json={"tier": "studio"}
    )
    assert response.status_code == 401


def test_change_tier_accepts_mock_payment_field(client, test_user, db):
    # mock_payment is accepted (forward-compat shape) but ignored.
    response = client.put(
        "/api/v1/auth/me/tier",
        json={
            "tier": "pro",
            "mock_payment": {
                "card_number": "4242424242424242",
                "expiry": "12/30",
                "cvc": "123",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["tier"] == "pro"


def test_change_tier_writes_audit_log(client, test_user, db):
    client.put("/api/v1/auth/me/tier", json={"tier": "studio"})
    response = client.get("/api/v1/auth/audit-log")
    assert response.status_code == 200
    events = [e["event"] for e in response.json()]
    assert "tier_changed" in events


def test_change_tier_unlocks_feature_gate(client, test_user, db):
    # Echo is gated on the studio tier per TIER_CAPABILITIES.
    # On free, /echo/* returns 403.
    r_free = client.post("/api/v1/echo/context", json={
        "kind": "interest", "key": "test", "value": "anything", "source": "manual"
    })
    assert r_free.status_code == 403

    # Upgrade to studio.
    client.put("/api/v1/auth/me/tier", json={"tier": "studio"})

    # Now the same call succeeds.
    r_studio = client.post("/api/v1/echo/context", json={
        "kind": "interest", "key": "test", "value": "anything", "source": "manual"
    })
    assert r_studio.status_code in (200, 201)
