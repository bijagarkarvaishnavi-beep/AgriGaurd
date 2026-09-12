"""Iteration 4 regression: signup, /fields/overview, reports persistence & durability."""
import os, uuid, requests, pytest

BASE = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/') + '/api'
ARTIFACT_DIR = '/app/backend/sentinel_results'


def _hdr(t): return {'Authorization': f'Bearer {t}'}


@pytest.fixture(scope='module')
def admin_token():
    r = requests.post(f'{BASE}/auth/login', json={'email': 'admin@example.com', 'password': 'admin123'})
    assert r.status_code == 200, r.text
    return r.json()['token']


@pytest.fixture(scope='module')
def farmer():
    email = f'test_iter4_{uuid.uuid4().hex[:8]}@example.com'
    r = requests.post(f'{BASE}/auth/register', json={'email': email, 'password': 'secret123', 'name': 'Iter4 Farmer'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['user']['role'] == 'farmer'
    assert body['user']['email'] == email.lower()
    assert body['token']
    return {'email': email, 'token': body['token'], 'id': body['user']['id']}


# ---- signup ----
class TestSignup:
    def test_register_admin_role(self):
        email = f'TEST_iter4_{uuid.uuid4().hex[:8]}@example.com'
        r = requests.post(f'{BASE}/auth/register', json={'email': email, 'password': 'secret123', 'name': 'A Admin', 'role': 'admin'})
        assert r.status_code == 200
        assert r.json()['user']['role'] == 'admin'
        assert r.json()['token']

    def test_register_invalid_role_coerced(self):
        email = f'TEST_iter4_{uuid.uuid4().hex[:8]}@example.com'
        r = requests.post(f'{BASE}/auth/register', json={'email': email, 'password': 'secret123', 'name': 'Coerce', 'role': 'wizard'})
        assert r.status_code == 200
        assert r.json()['user']['role'] == 'farmer'

    def test_register_duplicate(self, farmer):
        r = requests.post(f'{BASE}/auth/register', json={'email': farmer['email'], 'password': 'secret123', 'name': 'Dup'})
        assert r.status_code == 409

    def test_short_password_422(self):
        email = f'TEST_iter4_{uuid.uuid4().hex[:8]}@example.com'
        r = requests.post(f'{BASE}/auth/register', json={'email': email, 'password': '12', 'name': 'Sh'})
        assert r.status_code == 422

    def test_short_name_422(self):
        email = f'TEST_iter4_{uuid.uuid4().hex[:8]}@example.com'
        r = requests.post(f'{BASE}/auth/register', json={'email': email, 'password': 'secret123', 'name': 'A'})
        assert r.status_code == 422

    def test_invalid_email_422(self):
        r = requests.post(f'{BASE}/auth/register', json={'email': 'notanemail', 'password': 'secret123', 'name': 'Bad'})
        assert r.status_code == 422

    def test_new_user_empty_state(self, farmer):
        h = _hdr(farmer['token'])
        assert requests.get(f'{BASE}/fields', headers=h).json() == []
        assert requests.get(f'{BASE}/fields/overview', headers=h).json() == []
        d = requests.get(f'{BASE}/dashboard', headers=h).json()
        assert d == {'field': None, 'alerts': []}

    def test_isolation_new_user_cannot_see_admin_fields(self, admin_token, farmer):
        af = requests.get(f'{BASE}/fields', headers=_hdr(admin_token)).json()
        assert af, 'admin should have seed field'
        fid = af[0]['id']
        r = requests.get(f'{BASE}/fields/{fid}/analyses', headers=_hdr(farmer['token']))
        assert r.status_code == 404
        r = requests.get(f'{BASE}/fields/{fid}/reports', headers=_hdr(farmer['token']))
        assert r.status_code == 404


# ---- overview ----
class TestOverview:
    def test_admin_overview_and_new_field_lifecycle(self, admin_token):
        h = _hdr(admin_token)
        overview = requests.get(f'{BASE}/fields/overview', headers=h).json()
        assert isinstance(overview, list) and len(overview) >= 1
        first = overview[0]
        for k in ('id', 'polygon', 'hectares', 'latest_analysis', 'latest_sentinel'):
            assert k in first
        # create new field (no analysis)
        poly = [[51.60, -0.20], [51.605, -0.20], [51.605, -0.19], [51.60, -0.19]]
        cr = requests.post(f'{BASE}/fields', headers=h, json={'name': 'TEST_iter4_ov', 'crop': 'Rice', 'polygon': poly})
        assert cr.status_code == 200
        fid = cr.json()['id']
        try:
            ov = requests.get(f'{BASE}/fields/overview', headers=h).json()
            row = next(x for x in ov if x['id'] == fid)
            assert row['latest_analysis'] is None
            # analyze
            an = requests.post(f'{BASE}/flood/analyze', headers=h, json={'field_id': fid}).json()
            assert an['severity'] == 'HIGH'
            assert abs(an['flood_percentage'] - 55.2) < 5
            ov = requests.get(f'{BASE}/fields/overview', headers=h).json()
            row = next(x for x in ov if x['id'] == fid)
            assert row['latest_analysis']['severity'] == 'HIGH'
            assert row['latest_analysis']['flood_percentage'] == an['flood_percentage']
        finally:
            requests.delete(f'{BASE}/fields/{fid}', headers=h)


# ---- reports persistence ----
class TestReportsPersistence:
    def test_generate_list_download_and_isolation(self, admin_token, farmer):
        h = _hdr(admin_token)
        fid = requests.get(f'{BASE}/fields', headers=h).json()[0]['id']
        r = requests.get(f'{BASE}/fields/{fid}/report', headers=h)
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('application/pdf')
        rep_id = r.headers.get('X-Report-Id')
        assert rep_id
        cd = r.headers.get('content-disposition', '')
        assert 'filename=' in cd
        # ASCII-safe
        assert cd.encode('ascii', errors='ignore').decode() == cd
        size = len(r.content)
        # on-disk
        disk = os.path.join(ARTIFACT_DIR, 'reports', rep_id + '.pdf')
        assert os.path.isfile(disk)
        assert os.path.getsize(disk) == size

        listed = requests.get(f'{BASE}/fields/{fid}/reports', headers=h).json()
        assert any(x['id'] == rep_id for x in listed)
        row = next(x for x in listed if x['id'] == rep_id)
        for k in ('id', 'filename', 'size_bytes', 'flood_percentage', 'severity', 'created_at'):
            assert k in row
        # newest-first
        times = [x['created_at'] for x in listed]
        assert times == sorted(times, reverse=True)

        d = requests.get(f'{BASE}/reports/{rep_id}', headers=h)
        assert d.status_code == 200
        assert d.headers['content-type'].startswith('application/pdf')
        assert len(d.content) == row['size_bytes']

        # farmer cannot download admin's report
        r2 = requests.get(f'{BASE}/reports/{rep_id}', headers=_hdr(farmer['token']))
        assert r2.status_code == 404
        # unknown id
        r3 = requests.get(f'{BASE}/reports/{uuid.uuid4()}', headers=h)
        assert r3.status_code == 404


class TestHealth:
    def test_health_ok(self):
        r = requests.get(f'{BASE}/health')
        assert r.status_code == 200
        b = r.json()
        assert b['status'] == 'ok'
        assert b['storage'] == 'PostGIS (canonical)'
