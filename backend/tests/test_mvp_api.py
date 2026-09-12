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
    assert 40 <= data["flood"]["flood_percentage"] <= 70
    assert data["flood"]["severity"] == "HIGH"
    assert data["readiness"]["status"] == "NOT RECOMMENDED"
    assert data["alerts"] and data["soil"] and data["weather"] and data["crops"]
    assert "PostGIS" in requests.get(f"{BASE_URL}/api/", timeout=15).json()["storage"]


def test_field_crud_and_validation():
    login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@example.com", "password": "admin123"}, timeout=15)
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    square = [[51.52, -0.10], [51.525, -0.10], [51.525, -0.09], [51.52, -0.09]]
    created = requests.post(f"{BASE_URL}/api/fields", headers=headers, json={"name": "API Plot", "crop": "Rice", "polygon": square}, timeout=15)
    assert created.status_code == 200 and created.json()["hectares"] == 38.61 and "PostGIS" in created.json()["geometry_source"]
    fid = created.json()["id"]
    bowtie = [[51.52, -0.10], [51.53, -0.09], [51.53, -0.10], [51.52, -0.09]]
    assert requests.post(f"{BASE_URL}/api/fields", headers=headers, json={"name": "Bad", "crop": "Rice", "polygon": bowtie}, timeout=15).status_code == 422
    updated = requests.put(f"{BASE_URL}/api/fields/{fid}", headers=headers, json={"name": "API Plot 2", "crop": "Maize", "polygon": [[51.52, -0.10], [51.53, -0.10], [51.53, -0.09], [51.52, -0.09]]}, timeout=15)
    assert updated.status_code == 200 and updated.json()["name"] == "API Plot 2" and updated.json()["hectares"] > 38.61
    assert requests.delete(f"{BASE_URL}/api/fields/{fid}", headers=headers, timeout=15).json()["ok"] is True
    assert requests.delete(f"{BASE_URL}/api/fields/{fid}", headers=headers, timeout=15).status_code == 404


def test_sentinel_demo_run_and_artifacts():
    login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@example.com", "password": "admin123"}, timeout=15)
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    field = requests.get(f"{BASE_URL}/api/fields", headers=headers, timeout=15).json()[0]
    run = requests.post(f"{BASE_URL}/api/sentinel1/runs", headers=headers, data={"field_id": field["id"], "threshold_db": "-7"}, timeout=60)
    assert run.status_code == 200
    body = run.json()
    assert body["source"] == "DEMO SAR" and 40 <= body["flood_percentage"] <= 70 and body["flood_pixels"] > 0
    art = requests.get(f"{BASE_URL}{body['artifacts']['flood-mask.png']}", headers=headers, timeout=15)
    assert art.status_code == 200 and art.headers["content-type"] == "image/png"
    assert requests.get(f"{BASE_URL}{body['artifacts']['flood-mask.png']}", timeout=15).status_code == 401
    bad = requests.post(f"{BASE_URL}/api/sentinel1/runs", headers=headers, data={"field_id": field["id"]}, files={"before": ("x.txt", b"nope")}, timeout=15)
    assert bad.status_code == 415
    report = requests.get(f"{BASE_URL}/api/fields/{field['id']}/report", headers=headers, timeout=30)
    assert report.status_code == 200 and report.headers["content-type"] == "application/pdf" and len(report.content) > 5000


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