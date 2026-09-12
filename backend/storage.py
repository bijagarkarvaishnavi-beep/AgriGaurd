"""Persistence layer: PostGIS is canonical when configured; MongoDB is the fallback. Never both."""
import json, os, logging, subprocess
from datetime import datetime
import engine

SQL_INIT = open(os.path.join(os.path.dirname(__file__), 'sql', 'init.sql')).read()
FIELD_SQL = "SELECT id, owner_id, name, crop, ST_AsGeoJSON(geom)::text AS gj, ST_Area(geom::geography)/10000 AS ha, created_at FROM fields"


def _wkt(polygon):
    pts = [f'{p[1]} {p[0]}' for p in polygon] + [f'{polygon[0][1]} {polygon[0][0]}']
    return 'POLYGON((' + ', '.join(pts) + '))'


def _field_row(r):
    ha = max(0.01, round(r['ha'], 2))
    coords = json.loads(r['gj'])['coordinates'][0][:-1]
    return {'id': r['id'], 'owner_id': r['owner_id'], 'name': r['name'], 'crop': r['crop'], 'polygon': [[lat, lon] for lon, lat in coords],
            'hectares': ha, 'acres': engine.acres(ha), 'geometry_source': 'PostGIS geometry(Polygon,4326) · ST_Area(geography)', 'created_at': r['created_at'].isoformat()}


class PostgisStore:
    name = 'PostGIS (canonical)'
    fallback = False

    def __init__(self, url):
        self.url = url
        self.pool = None

    async def init(self):
        import asyncpg

        async def codecs(conn):
            await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
        self.pool = await asyncpg.create_pool(self.url, init=codecs, min_size=1, max_size=5, timeout=10)
        async with self.pool.acquire() as conn:
            await conn.execute(SQL_INIT)

    async def user_by_email(self, email):
        r = await self.pool.fetchrow('SELECT * FROM users WHERE email=$1', email)
        return dict(r) | {'created_at': r['created_at'].isoformat()} if r else None

    async def user_by_id(self, user_id):
        r = await self.pool.fetchrow('SELECT id, email, name, role, created_at FROM users WHERE id=$1', user_id)
        return dict(r) | {'created_at': r['created_at'].isoformat()} if r else None

    async def create_user(self, u):
        await self.pool.execute('INSERT INTO users (id,email,name,role,password_hash,created_at) VALUES ($1,$2,$3,$4,$5,$6)', u['id'], u['email'], u['name'], u['role'], u['password_hash'], datetime.fromisoformat(u['created_at']))

    async def list_fields(self, owner_id):
        return [_field_row(r) for r in await self.pool.fetch(FIELD_SQL + ' WHERE owner_id=$1 ORDER BY created_at', owner_id)]

    async def first_field(self, owner_id):
        r = await self.pool.fetchrow(FIELD_SQL + ' WHERE owner_id=$1 ORDER BY created_at LIMIT 1', owner_id)
        return _field_row(r) if r else None

    async def get_field(self, field_id, owner_id):
        r = await self.pool.fetchrow(FIELD_SQL + ' WHERE id=$1 AND owner_id=$2', field_id, owner_id)
        return _field_row(r) if r else None

    async def create_field(self, f):
        await self.pool.execute('INSERT INTO fields (id,owner_id,name,crop,geom,created_at) VALUES ($1,$2,$3,$4,ST_GeomFromText($5,4326),$6)', f['id'], f['owner_id'], f['name'], f['crop'], _wkt(f['polygon']), datetime.fromisoformat(f['created_at']))
        return await self.get_field(f['id'], f['owner_id'])

    async def update_field(self, field_id, owner_id, name, crop, polygon):
        await self.pool.execute('UPDATE fields SET name=$3, crop=$4, geom=ST_GeomFromText($5,4326) WHERE id=$1 AND owner_id=$2', field_id, owner_id, name, crop, _wkt(polygon))
        return await self.get_field(field_id, owner_id)

    async def delete_field(self, field_id, owner_id):
        return (await self.pool.execute('DELETE FROM fields WHERE id=$1 AND owner_id=$2', field_id, owner_id)).endswith('1')

    async def add_analysis(self, a):
        await self.pool.execute('INSERT INTO analyses (id,field_id,payload,created_at) VALUES ($1,$2,$3,$4)', a['id'], a['field_id'], a, datetime.fromisoformat(a['created_at']))

    async def analyses(self, field_id, limit=20):
        return [r['payload'] for r in await self.pool.fetch('SELECT payload FROM analyses WHERE field_id=$1 ORDER BY created_at DESC LIMIT $2', field_id, limit)]

    async def latest_analysis(self, field_id):
        r = await self.pool.fetchrow('SELECT payload FROM analyses WHERE field_id=$1 ORDER BY created_at DESC LIMIT 1', field_id)
        return r['payload'] if r else None

    async def add_run(self, run):
        await self.pool.execute('INSERT INTO sentinel_runs (id,field_id,payload,created_at) VALUES ($1,$2,$3,$4)', run['id'], run['field_id'], run, datetime.fromisoformat(run['created_at']))

    async def get_run(self, run_id):
        r = await self.pool.fetchrow('SELECT payload FROM sentinel_runs WHERE id=$1', run_id)
        return r['payload'] if r else None

    async def latest_run(self, field_id):
        r = await self.pool.fetchrow('SELECT payload FROM sentinel_runs WHERE field_id=$1 ORDER BY created_at DESC LIMIT 1', field_id)
        return r['payload'] if r else None

    async def add_report(self, rep):
        await self.pool.execute('INSERT INTO reports (id,field_id,owner_id,payload,created_at) VALUES ($1,$2,$3,$4,$5)', rep['id'], rep['field_id'], rep['owner_id'], rep, datetime.fromisoformat(rep['created_at']))

    async def reports(self, field_id, limit=20):
        return [r['payload'] for r in await self.pool.fetch('SELECT payload FROM reports WHERE field_id=$1 ORDER BY created_at DESC LIMIT $2', field_id, limit)]

    async def get_report(self, report_id, owner_id):
        r = await self.pool.fetchrow('SELECT payload FROM reports WHERE id=$1 AND owner_id=$2', report_id, owner_id)
        return r['payload'] if r else None


class MongoStore:
    name = 'MongoDB (fallback)'
    fallback = True

    def __init__(self, url, db_name):
        from motor.motor_asyncio import AsyncIOMotorClient
        self.db = AsyncIOMotorClient(url)[db_name]

    async def init(self):
        await self.db.users.create_index('email', unique=True)
        await self.db.fields.update_many({'geometry_source': {'$exists': False}}, {'$set': {'geometry_source': 'WGS84 geodesic (pyproj) · MongoDB fallback'}})

    async def user_by_email(self, email):
        return await self.db.users.find_one({'email': email}, {'_id': 0})

    async def user_by_id(self, user_id):
        return await self.db.users.find_one({'id': user_id}, {'_id': 0, 'password_hash': 0})

    async def create_user(self, u):
        await self.db.users.insert_one(dict(u))

    async def list_fields(self, owner_id):
        return [x async for x in self.db.fields.find({'owner_id': owner_id}, {'_id': 0}).sort('created_at', 1)]

    async def first_field(self, owner_id):
        return await self.db.fields.find_one({'owner_id': owner_id}, {'_id': 0}, sort=[('created_at', 1)])

    async def get_field(self, field_id, owner_id):
        return await self.db.fields.find_one({'id': field_id, 'owner_id': owner_id}, {'_id': 0})

    async def create_field(self, f):
        doc = dict(f, geometry_source='WGS84 geodesic (pyproj) · MongoDB fallback')
        await self.db.fields.insert_one(dict(doc))
        return doc

    async def update_field(self, field_id, owner_id, name, crop, polygon):
        ha = engine.hectares(polygon)
        await self.db.fields.update_one({'id': field_id, 'owner_id': owner_id}, {'$set': {'name': name, 'crop': crop, 'polygon': polygon, 'hectares': ha, 'acres': engine.acres(ha)}})
        return await self.get_field(field_id, owner_id)

    async def delete_field(self, field_id, owner_id):
        r = await self.db.fields.delete_one({'id': field_id, 'owner_id': owner_id})
        if r.deleted_count:
            await self.db.analyses.delete_many({'field_id': field_id})
            await self.db.reports.delete_many({'field_id': field_id})
            await self.db.sentinel_runs.update_many({'field_id': field_id}, {'$set': {'field_id': None}})
        return bool(r.deleted_count)

    async def add_analysis(self, a):
        await self.db.analyses.insert_one(dict(a))

    async def analyses(self, field_id, limit=20):
        return [x async for x in self.db.analyses.find({'field_id': field_id}, {'_id': 0}).sort('created_at', -1).limit(limit)]

    async def latest_analysis(self, field_id):
        return await self.db.analyses.find_one({'field_id': field_id}, {'_id': 0}, sort=[('created_at', -1)])

    async def add_run(self, run):
        await self.db.sentinel_runs.insert_one(dict(run))

    async def get_run(self, run_id):
        return await self.db.sentinel_runs.find_one({'id': run_id}, {'_id': 0})

    async def latest_run(self, field_id):
        return await self.db.sentinel_runs.find_one({'field_id': field_id}, {'_id': 0}, sort=[('created_at', -1)])

    async def add_report(self, rep):
        await self.db.reports.insert_one(dict(rep))

    async def reports(self, field_id, limit=20):
        return [x async for x in self.db.reports.find({'field_id': field_id}, {'_id': 0}).sort('created_at', -1).limit(limit)]

    async def get_report(self, report_id, owner_id):
        return await self.db.reports.find_one({'id': report_id, 'owner_id': owner_id}, {'_id': 0})


def _bootstrap_local_postgis(url):
    if '@localhost' not in url and '@127.0.0.1' not in url:
        return
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'ensure_local_postgis.sh')
    try:
        out = subprocess.run(['bash', script], capture_output=True, text=True, timeout=90)
        logging.info('Local PostGIS bootstrap: %s', (out.stdout or out.stderr).strip()[-300:])
    except Exception as exc:
        logging.warning('Local PostGIS bootstrap skipped: %s', exc)


async def build_store():
    url = os.environ.get('POSTGIS_DATABASE_URL')
    if url:
        _bootstrap_local_postgis(url)
        try:
            store = PostgisStore(url)
            await store.init()
            logging.info('Storage: PostGIS canonical')
            return store
        except Exception as exc:
            logging.warning('PostGIS unavailable, falling back to MongoDB: %s', exc)
    store = MongoStore(os.environ['MONGO_URL'], os.environ['DB_NAME'])
    await store.init()
    logging.info('Storage: MongoDB fallback')
    return store
