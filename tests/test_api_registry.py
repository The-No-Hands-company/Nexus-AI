import pytest
from fastapi.testclient import TestClient
from api_registry import app

client = TestClient(app)


def test_register_api():
    response = client.post(
        "/register",
        json={
            "api_name": "test_api",
            "api_url": "http://test.com/api",
            "metadata": {"description": "Test API"}
        }
    )
    assert response.status_code == 200
    assert response.json()["message"] == "API 'test_api' registered successfully"
    assert "test_api" in response.json()["api"]


def test_register_duplicate_api():
    # First registration
    client.post(
        "/register",
        json={
            "api_name": "duplicate_api",
            "api_url": "http://test.com/api"
        }
    )
    
    # Second registration attempt
    response = client.post(
        "/register",
        json={
            "api_name": "duplicate_api",
            "api_url": "http://test.com/api2"
        }
    )
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


def test_get_registry():
    # Register a test API first
    client.post(
        "/register",
        json={
            "api_name": "registry_test_api",
            "api_url": "http://test.com/api"
        }
    )
    
    response = client.get("/registry")
    assert response.status_code == 200
    assert "registry_test_api" in response.json()


def test_get_specific_api():
    # Register a test API first
    client.post(
        "/register",
        json={
            "api_name": "specific_test_api",
            "api_url": "http://test.com/api"
        }
    )
    
    response = client.get("/registry/specific_test_api")
    assert response.status_code == 200
    assert "specific_test_api" in response.json()


def test_get_nonexistent_api():
    response = client.get("/registry/nonexistent_api")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_update_api_status():
    # Register a test API first
    client.post(
        "/register",
        json={
            "api_name": "status_test_api",
            "api_url": "http://test.com/api"
        }
    )
    
    response = client.put(
        "/registry/status_test_api/status",
        json={"status": "inactive"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "API 'status_test_api' status updated to 'inactive'"
    assert response.json()["api"]["status"] == "inactive"


def test_deregister_api():
    # Register a test API first
    client.post(
        "/register",
        json={
            "api_name": "deregister_test_api",
            "api_url": "http://test.com/api"
        }
    )
    
    response = client.delete("/registry/deregister_test_api")
    assert response.status_code == 200
    assert response.json()["message"] == "API 'deregister_test_api' deregistered successfully"


def test_deregister_nonexistent_api():
    response = client.delete("/registry/nonexistent_api")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]