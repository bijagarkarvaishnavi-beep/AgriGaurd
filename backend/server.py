from dotenv import load_dotenv
load_dotenv()
import os, uuid, logging, io, re
from datetime import datetime, timezone, timedelta
from typing import Optional
import bcrypt, jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr, field_validator
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import engine, raster
from storage import build_store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title='SAR Satellite Crop Flood Engine', version='1.1.0')
@app.get("/")
async def root():
    return {
        "message": "AgriGaurd Backend API is running",
        "docs": "/docs"
    }
api = APIRouter(prefix='/api')
SECRET = os.environ.get('JWT_SECRET', 'local-demo-secret-change-me')
store = None
DEMO_SOIL = {'type': 'Loam', 'moisture': 78}
DEMO_WEATHER = {'temperature': 27, 'rainfall': 38, 'humidity': 84, 'forecast': 'Heavy rain likely', 'data_mode': 'DEMO WEATHER'}
SEED_POLYGON = [[51.505, -0.09], [51.51, -0.08], [51.508, -0.06], [51.502, -0.065]]

def now(): return datetime.now(timezone.utc).isoformat()
def public(doc):
    if not doc: return None
    return {k: v for k, v in doc.items() if k not in {'_id', 'password_hash'}}
def token(user): return jwt.encode({'sub': user['id'], 'email': user['email'], 'role': user['role'], 'exp': datetime.now(timezone.utc) + timedelta(days=2)}, SECRET, algorithm='HS256')
async def current(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401, 'Login required')
    try: payload = jwt.decode(authorization[7:], SECRET, algorithms=['HS256'])
    except jwt.PyJWTError: raise HTTPException(401, 'Invalid or expired session')
    user = await store.user_by_id(payload['sub'])
    if not user: raise HTTPException(401, 'User not found')
    return public(user)
async def owned_field(field_id, user):
    field = await store.get_field(field_id, user['id'])
    if not field: raise HTTPException(404, 'Field not found')
    return field

class AuthIn(BaseModel): email: EmailStr; password: str = Field(min_length=6); name: str = Field(min_length=2); role: str = 'farmer'
class LoginIn(BaseModel): email: EmailStr; password: str
class FieldIn(BaseModel):
    name: str = Field(min_length=2)
    crop: str = Field(default='Wheat', min_length=2, max_length=40)
    polygon: list[list[float]] = Field(min_length=3, max_length=100)
    @field_validator('polygon')
    @classmethod
    def valid_polygon(cls, value):
        problem = engine.polygon_problem(value)
        if problem: raise ValueError(problem)
        return value
class AnalysisIn(BaseModel): field_id: str; before_date: str = '2024-06-01'; after_date: str = '2024-06-15'

@api.get('/')
async def root(): return {'service': 'SAR Satellite Crop Flood Engine', 'status': 'operational', 'data_mode': 'DEMO/TEST', 'storage': store.name if store else 'initialising'}
@api.get('/health')
async def health():
    degraded = bool(os.environ.get('POSTGIS_DATABASE_URL')) and (store is None or store.fallback)
    body = {'status': 'degraded' if degraded else 'ok', 'storage': store.name if store else 'initialising', 'configured_canonical': 'PostGIS' if os.environ.get('POSTGIS_DATABASE_URL') else 'MongoDB'}
    return JSONResponse(body, status_code=503 if degraded else 200)
@api.post('/auth/register')
async def register(body: AuthIn):
    email = body.email.lower()
    if await store.user_by_email(email): raise HTTPException(409, 'Email already registered')
    user = {'id': str(uuid.uuid4()), 'email': email, 'name': body.name, 'role': body.role if body.role in ('farmer', 'admin') else 'farmer', 'password_hash': bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode(), 'created_at': now()}
    await store.create_user(user); return {'user': public(user), 'token': token(user)}
@api.post('/auth/login')
async def login(body: LoginIn):
    user = await store.user_by_email(body.email.lower())
    if not user or not bcrypt.checkpw(body.password.encode(), user['password_hash'].encode()): raise HTTPException(401, 'Email or password is incorrect')
    return {'user': public(user), 'token': token(user)}
@api.get('/auth/me')
async def me(user=Depends(current)): return user
@api.post('/auth/logout')
async def logout(): return {'ok': True}

def field_doc(owner_id, body):
    ha = engine.hectares(body.polygon)
    return {'id': str(uuid.uuid4()), 'owner_id': owner_id, 'name': body.name, 'crop': body.crop, 'polygon': body.polygon, 'hectares': ha, 'acres': engine.acres(ha), 'created_at': now()}
@api.get('/fields')
async def fields(user=Depends(current)): return await store.list_fields(user['id'])
@api.post('/fields')
async def create_field(body: FieldIn, user=Depends(current)): return await store.create_field(field_doc(user['id'], body))
@api.put('/fields/{field_id}')
async def update_field(field_id: str, body: FieldIn, user=Depends(current)):
    await owned_field(field_id, user)
    return await store.update_field(field_id, user['id'], body.name, body.crop, body.polygon)
@api.delete('/fields/{field_id}')
async def delete_field(field_id: str, user=Depends(current)):
    if not await store.delete_field(field_id, user['id']): raise HTTPException(404, 'Field not found')
    return {'ok': True}

def flood_result(field, before='2024-06-01', after='2024-06-15'):
    flooded, pct = engine.demo_flood(field['polygon'])
    return {'id': str(uuid.uuid4()), 'field_id': field['id'], 'field_name': field['name'], 'field_hectares': field['hectares'], 'field_acres': field['acres'], 'flooded_hectares': flooded, 'flooded_acres': engine.acres(flooded),
            'flood_percentage': pct, 'severity': engine.severity(pct), 'before_date': before, 'after_date': after, 'data_mode': 'DEMO SAR', 'method': 'Deterministic DEMO waterbody ∩ field polygon (geodesic)', 'created_at': now()}
def context(field, flood):
    soil = engine.soil_assessment(DEMO_SOIL['type'], DEMO_SOIL['moisture'], DEMO_WEATHER['rainfall']) | {'data_mode': 'ESTIMATED / DEMO'}
    crops = engine.crop_recommendations(soil)
    readiness = engine.planting_readiness(flood['flood_percentage'], soil, DEMO_WEATHER['rainfall'])
    return {'field': field, 'flood': flood, 'soil': soil, 'weather': DEMO_WEATHER, 'crops': crops, 'readiness': readiness, 'alerts': engine.alerts(flood, soil, readiness)}

def raster_bytes(upload, field, after):
    if not upload or not upload.filename: return raster.demo_raster(field['polygon'] if field else None, after), True
    if not upload.filename.lower().endswith(('.tif', '.tiff')): raise HTTPException(415, 'Only GeoTIFF uploads are accepted')
    data = upload.file.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024: raise HTTPException(413, 'Raster exceeds 100 MB limit')
    if not data: raise HTTPException(422, 'Uploaded GeoTIFF is empty')
    return data, False
@api.post('/sentinel1/runs')
async def sentinel_run(before: UploadFile | None = File(None), after: UploadFile | None = File(None), field_id: str | None = Form(None), threshold_db: float = Form(-7.0), user=Depends(current)):
    if not -30 <= threshold_db <= 0: raise HTTPException(422, 'threshold_db must be between -30 and 0')
    field = await owned_field(field_id, user) if field_id else None
    before_data, b_demo = raster_bytes(before, field, False); after_data, a_demo = raster_bytes(after, field, True)
    result = raster.raster_run(before_data, after_data, field, threshold_db, 'DEMO SAR' if b_demo or a_demo else 'SENTINEL-1 UPLOAD')
    await store.add_run(result); return result
@api.get('/sentinel1/results/{run_id}/{filename}')
async def sentinel_artifact(run_id: str, filename: str, user=Depends(current)):
    run = await store.get_run(run_id)
    if not run or filename not in {os.path.basename(x) for x in run.get('artifacts', {}).values()}: raise HTTPException(404, 'Artifact not found')
    path = os.path.join(raster.RESULTS_DIR, run_id, filename)
    if not os.path.isfile(path): raise HTTPException(404, 'Artifact not found')
    return StreamingResponse(open(path, 'rb'), media_type='image/png')
@api.post('/flood/analyze')
async def analyze(body: AnalysisIn, user=Depends(current)):
    field = await owned_field(body.field_id, user)
    result = flood_result(field, body.before_date, body.after_date)
    await store.add_analysis(result); return result
@api.get('/fields/{field_id}/analyses')
async def history(field_id: str, user=Depends(current)):
    await owned_field(field_id, user); return await store.analyses(field_id)
@api.get('/fields/{field_id}/report')
async def report(field_id: str, user=Depends(current)):
    field = await owned_field(field_id, user)
    flood = await store.latest_analysis(field_id) or flood_result(field)
    ctx = context(field, flood); sentinel = await store.latest_run(field_id)
    out = io.BytesIO(); pdf = canvas.Canvas(out, pagesize=A4); width, height = A4
    pdf.setTitle('Flood Evidence Report - ' + field['name']); pdf.setFillColorRGB(.02, .12, .16); pdf.rect(0, height - 95, width, 95, fill=1, stroke=0)
    pdf.setFillColorRGB(0, .85, .9); pdf.setFont('Helvetica-Bold', 18); pdf.drawString(42, height - 55, 'SENTINEL CROP AI')
    pdf.setFillColorRGB(.1, .1, .1); pdf.setFont('Helvetica-Bold', 15); pdf.drawString(42, height - 135, 'Flood Evidence Report')
    y = height - 165
    if sentinel:
        pdf.setFont('Helvetica-Bold', 9); pdf.setFillColorRGB(.25, .3, .33); pdf.drawString(42, height - 155, f"SAR EVIDENCE SNAPSHOTS · {sentinel['source']} · {sentinel['flood_percentage']}% flooded")
        x = 42
        for key in ('before.png', 'after.png', 'flood-mask.png'):
            path = os.path.join(raster.RESULTS_DIR, sentinel['id'], key)
            if os.path.isfile(path): pdf.drawImage(ImageReader(path), x, height - 270, width=155, height=95, preserveAspectRatio=True, anchor='c'); x += 170
        y = height - 295
    soil, weather, crop, ready = ctx['soil'], ctx['weather'], ctx['crops'][0], ctx['readiness']
    lines = [('Field', field['name']), ('Crop', field['crop']), ('Area', f"{field['hectares']} ha / {field['acres']} acres"), ('Geometry', field['geometry_source']), ('Flooded area', f"{flood['flooded_hectares']} ha / {flood['flooded_acres']} acres"), ('Flood percentage', f"{flood['flood_percentage']}%"), ('Severity', flood['severity']), ('SAR dates', f"{flood['before_date']} → {flood['after_date']}"),
             ('Soil', f"{soil['type']} · {soil['condition']} · Waterlogging risk {soil['waterlogging_risk']}"), ('Weather', f"{weather['temperature']}°C · {weather['rainfall']} mm rainfall · {weather['humidity']}% humidity"), ('Recommendation', f"{crop['name']} · {crop['score']}/100 · {ready['status']} to plant now")]
    pdf.setFont('Helvetica', 10)
    for label, value in lines: pdf.setFillColorRGB(.25, .3, .33); pdf.drawString(42, y, label.upper()); pdf.setFillColorRGB(.05, .07, .09); pdf.drawString(180, y, value); y -= 25
    pdf.setFillColorRGB(.75, .2, .18); pdf.setFont('Helvetica-Bold', 10); pdf.drawString(42, y - 15, 'DISCLAIMER'); pdf.setFillColorRGB(.2, .2, .2); pdf.setFont('Helvetica', 9); pdf.drawString(42, y - 32, 'This is an insurance-supporting evidence report, NOT an official insurance assessment.')
    pdf.drawString(42, y - 47, 'SAR, soil, weather, and recommendations may contain DEMO/ESTIMATED values. Verify with qualified assessors.')
    pdf.save(); out.seek(0)
    rep = {'id': str(uuid.uuid4()), 'field_id': field_id, 'owner_id': user['id'], 'field_name': field['name'], 'flood_percentage': flood['flood_percentage'], 'severity': flood['severity'], 'sentinel_run_id': sentinel['id'] if sentinel else None, 'size_bytes': out.getbuffer().nbytes, 'created_at': now()}
    rep['filename'] = f"{re.sub(r'[^A-Za-z0-9_-]+', '_', field['name']).strip('_')}_flood_report_{rep['created_at'][:10]}.pdf"
    with open(os.path.join(raster.RESULTS_DIR, 'reports', rep['id'] + '.pdf'), 'wb') as fh: fh.write(out.getvalue())
    await store.add_report(rep)
    return StreamingResponse(out, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{rep["filename"]}"', 'X-Report-Id': rep['id']})
@api.get('/fields/{field_id}/reports')
async def field_reports(field_id: str, user=Depends(current)):
    await owned_field(field_id, user); return await store.reports(field_id)
@api.get('/reports/{report_id}')
async def download_report(report_id: str, user=Depends(current)):
    rep = await store.get_report(report_id, user['id'])
    path = os.path.join(raster.RESULTS_DIR, 'reports', report_id + '.pdf')
    if not rep or not os.path.isfile(path): raise HTTPException(404, 'Report not found')
    return StreamingResponse(open(path, 'rb'), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{rep["filename"]}"'})
@api.get('/fields/overview')
async def fields_overview(user=Depends(current)):
    out = []
    for field in await store.list_fields(user['id']):
        latest = await store.latest_analysis(field['id']); run = await store.latest_run(field['id'])
        out.append({**field, 'latest_analysis': {'flood_percentage': latest['flood_percentage'], 'severity': latest['severity'], 'after_date': latest['after_date'], 'created_at': latest['created_at']} if latest else None,
                    'latest_sentinel': {'flood_percentage': run['flood_percentage'], 'severity': run['severity'], 'source': run['source']} if run else None})
    return out
@api.get('/dashboard')
async def dashboard(user=Depends(current)):
    field = await store.first_field(user['id'])
    if not field: return {'field': None, 'alerts': []}
    latest = await store.latest_analysis(field['id']) or flood_result(field)
    return context(field, latest)
@api.post('/devices/register')
async def device_register(payload: dict, user=Depends(current)): return {'device_id': str(uuid.uuid4()), 'status': 'registered', 'mode': 'OPTIONAL HARDWARE'}
@api.post('/seed/upload')
async def seed_upload(file: UploadFile = File(...), user=Depends(current)): return {'upload_id': str(uuid.uuid4()), 'filename': file.filename, 'status': 'ready_for_analysis', 'mode': 'DEMO'}
@api.post('/seed/analyze')
async def seed_analyze(payload: dict, user=Depends(current)): return {'quality_score': 82, 'classification': 'HEALTHY-LOOKING', 'notes': ['No obvious discoloration detected', 'Basic visual screening only'], 'disclaimer': 'DEMO analysis; not guaranteed real/fake seed detection'}
@api.get('/fields/{field_id}/seed-tests')
async def seed_history(field_id: str, user=Depends(current)): return []

app.include_router(api)
cors_origins = os.environ.get('CORS_ORIGINS', '*').split(',')
app.add_middleware(CORSMiddleware, allow_credentials='*' not in cors_origins, allow_origins=cors_origins, allow_methods=['*'], allow_headers=['*'])

@app.on_event('startup')
async def startup():
    global store
    store = await build_store()
    admin = await store.user_by_email('admin@example.com')
    if not admin:
        admin = {'id': str(uuid.uuid4()), 'email': 'admin@example.com', 'name': 'Demo Admin', 'role': 'admin', 'password_hash': bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode(), 'created_at': now()}
        await store.create_user(admin)
    if not await store.first_field(admin['id']):
        await store.create_field(field_doc(admin['id'], FieldIn(name='North Meadow · DEMO', crop='Wheat', polygon=SEED_POLYGON)))
