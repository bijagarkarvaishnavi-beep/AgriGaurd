import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


def test_public_root_and_docs():
    root = requests.get(f"{BASE_URL}/api/", timeout=15)
    assert root.status_code == 200
    assert root.json()["status"] == "operational"
    assert "DEMO" in root.json()["data_mode"]
    assert requests.get(f"{BASE_URL}/docs", timeout=15).status_code == 200


def test_auth_and_dashboard_flow():
    missing = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert missing.status_code == 401
    login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@example.com", "password": "admin123"}, timeout=15)
    assert login.status_code == 200
    body = login.json()
    assert body["user"]["email"] == "admin@example.com"
    token = body["token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=15)
    assert me.status_code == 200
    dashboard = requests.get(f"{BASE_URL}/api/dashboard", headers=headers, timeout=15)
    assert dashboard.status_code == 200
    data = dashboard.json()
    assert data["field"]["name"] == "North Meadow · DEMO"
    assert data["flood"]["flood_percentage"] == 65.0
    assert data["flood"]["severity"] == "HIGH"
    assert data["alerts"] and data["soil"] and data["weather"] and data["crops"]


def test_flood_analysis_history_and_optional_routes():
    login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@example.com", "password": "admin123"}, timeout=15)
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    field = requests.get(f"{BASE_URL}/api/fields", headers=headers, timeout=15).json()[0]
    analysis = requests.post(f"{BASE_URL}/api/flood/analyze", headers=headers, json={"field_id": field["id"]}, timeout=15)
    assert analysis.status_code == 200
    assert analysis.json()["data_mode"] == "DEMO SAR"
    history = requests.get(f"{BASE_URL}/api/fields/{field['id']}/analyses", headers=headers, timeout=15)
    assert history.status_code == 200 and any(x["id"] == analysis.json()["id"] for x in history.json())
    assert requests.post(f"{BASE_URL}/api/devices/register", headers=headers, json={}, timeout=15).json()["mode"] == "OPTIONAL HARDWARE"
    assert requests.post(f"{BASE_URL}/api/seed/analyze", headers=headers, json={}, timeout=15).json()["disclaimer"].startswith("DEMO")