import asyncio, os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
import pytest
import engine
from storage import PostgisStore

URL = os.environ.get('POSTGIS_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='POSTGIS_DATABASE_URL not configured')
SEED = [[51.505, -0.09], [51.51, -0.08], [51.508, -0.06], [51.502, -0.065]]


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def scenario():
    store = PostgisStore(URL)
    await store.init()
    uid = str(uuid.uuid4())
    await store.create_user({'id': uid, 'email': f'{uid}@test.local', 'name': 'PostGIS Tester', 'role': 'farmer', 'password_hash': 'x', 'created_at': '2026-06-01T00:00:00+00:00'})
    try:
        assert (await store.user_by_id(uid))['email'] == f'{uid}@test.local'
        fid = str(uuid.uuid4())
        field = await store.create_field({'id': fid, 'owner_id': uid, 'name': 'PG Plot', 'crop': 'Rice', 'polygon': SEED, 'created_at': '2026-06-01T00:00:00+00:00'})
        assert field['polygon'] == SEED
        assert 'PostGIS' in field['geometry_source']
        assert field['hectares'] == pytest.approx(engine.hectares(SEED), rel=0.002)  # ST_Area(geography) vs pyproj geodesic
        assert field['acres'] == engine.acres(field['hectares'])
        assert await store.get_field(fid, 'someone-else') is None
        assert [f['id'] for f in await store.list_fields(uid)] == [fid]
        bigger = [[51.50, -0.10], [51.52, -0.10], [51.52, -0.06], [51.50, -0.06]]
        updated = await store.update_field(fid, uid, 'PG Plot 2', 'Maize', bigger)
        assert updated['name'] == 'PG Plot 2' and updated['polygon'] == bigger and updated['hectares'] > field['hectares']
        a = {'id': str(uuid.uuid4()), 'field_id': fid, 'flood_percentage': 55.2, 'severity': 'HIGH', 'created_at': '2026-06-02T00:00:00+00:00'}
        b = dict(a, id=str(uuid.uuid4()), flood_percentage=12.0, severity='LOW', created_at='2026-06-03T00:00:00+00:00')
        await store.add_analysis(a); await store.add_analysis(b)
        assert [x['id'] for x in await store.analyses(fid)] == [b['id'], a['id']]
        assert (await store.latest_analysis(fid))['flood_percentage'] == 12.0
        r = {'id': str(uuid.uuid4()), 'field_id': fid, 'artifacts': {'before.png': '/x/before.png'}, 'flood_percentage': 50.0, 'created_at': '2026-06-03T00:00:00+00:00'}
        await store.add_run(r)
        assert (await store.get_run(r['id']))['artifacts'] == r['artifacts']
        assert (await store.latest_run(fid))['id'] == r['id']
        assert await store.delete_field(fid, 'someone-else') is False
        assert await store.delete_field(fid, uid) is True
        assert await store.analyses(fid) == []  # ON DELETE CASCADE
        assert (await store.get_run(r['id']))['id'] == r['id']  # runs survive with field_id SET NULL
        assert await store.pool.fetchval('SELECT field_id FROM sentinel_runs WHERE id=$1', r['id']) is None
    finally:
        await store.pool.execute('DELETE FROM users WHERE id=$1', uid)
        await store.pool.close()


def test_postgis_store_roundtrip():
    run(scenario())
