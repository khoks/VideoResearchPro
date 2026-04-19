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
