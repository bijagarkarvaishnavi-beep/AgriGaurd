from dotenv import load_dotenv
load_dotenv()
import os, uuid, math, logging, io
from datetime import datetime, timezone, timedelta
from typing import Optional
import bcrypt, jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr, field_validator
from motor.motor_asyncio import AsyncIOMotorClient
from pyproj import Geod
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

client = AsyncIOMotorClient(os.environ['MONGO_URL']); db = client[os.environ['DB_NAME']]
app = FastAPI(title='SAR Satellite Crop Flood Engine', version='1.0.0')
api = APIRouter(prefix='/api')
SECRET = os.environ.get('JWT_SECRET', 'local-demo-secret-change-me')
postgis_pool = None

def now(): return datetime.now(timezone.utc).isoformat()
def public(doc):
    if not doc: return None
    return {k: v for k, v in doc.items() if k not in {'_id','password_hash'}}
def token(user): return jwt.encode({'sub': user['id'], 'email': user['email'], 'role': user['role'], 'exp': datetime.now(timezone.utc)+timedelta(days=2)}, SECRET, algorithm='HS256')
async def current(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401, 'Login required')
    try: payload = jwt.decode(authorization[7:], SECRET, algorithms=['HS256'])
    except jwt.PyJWTError: raise HTTPException(401, 'Invalid or expired session')
    user = await db.users.find_one({'id': payload['sub']}, {'_id': 0, 'password_hash': 0})
    if not user: raise HTTPException(401, 'User not found')
    return user

class AuthIn(BaseModel): email: EmailStr; password: str = Field(min_length=6); name: str = Field(min_length=2); role: str = 'farmer'
class LoginIn(BaseModel): email: EmailStr; password: str
class FieldIn(BaseModel):
    name: str = Field(min_length=2)
    crop: str = Field(default='Wheat', min_length=2, max_length=40)
    polygon: list[list[float]] = Field(min_length=3, max_length=100)
    @field_validator('polygon')
    @classmethod
    def valid_polygon(cls, value):
        if len(value) < 3 or any(len(point) != 2 for point in value):
            raise ValueError('polygon must contain at least three latitude/longitude pairs')
        if any(abs(point[0]) > 90 or abs(point[1]) > 180 for point in value):
            raise ValueError('polygon coordinates must be valid WGS84 latitude/longitude values')
        return value
class AnalysisIn(BaseModel): field_id: str; before_date: str = '2024-06-01'; after_date: str = '2024-06-15'

@api.get('/')
async def root(): return {'service':'SAR Satellite Crop Flood Engine','status':'operational','data_mode':'DEMO/TEST'}
@api.post('/auth/register')
async def register(body: AuthIn):
    email=body.email.lower()
    if await db.users.find_one({'email':email}): raise HTTPException(409,'Email already registered')
    user={'id':str(uuid.uuid4()),'email':email,'name':body.name,'role':body.role if body.role in ('farmer','admin') else 'farmer','password_hash':bcrypt.hashpw(body.password.encode(),bcrypt.gensalt()).decode(),'created_at':now()}
    await db.users.insert_one(user); return {'user':public(user),'token':token(user)}
@api.post('/auth/login')
async def login(body: LoginIn):
    user=await db.users.find_one({'email':body.email.lower()})
    if not user or not bcrypt.checkpw(body.password.encode(),user['password_hash'].encode()): raise HTTPException(401,'Email or password is incorrect')
    return {'user':public(user),'token':token(user)}
@api.get('/auth/me')
async def me(user=Depends(current)): return user
@api.post('/auth/logout')
async def logout(): return {'ok':True}

def hectares(poly):
    # Exact WGS84 geodesic area now; PostGIS uses the same geography calculation when configured.
    lonlat=[(point[1],point[0]) for point in poly]
    area, _ = Geod(ellps='WGS84').polygon_area_perimeter(*zip(*lonlat))
    return max(0.01, round(abs(area)/10000,2))
async def postgis_field(doc):
    if not postgis_pool: return
    try:
        points=', '.join(f'{p[1]} {p[0]}' for p in doc['polygon'])
        await postgis_pool.execute('INSERT INTO fields (id, owner_id, name, crop, geom, hectares, acres) VALUES ($1,$2,$3,$4,ST_SetSRID(ST_GeomFromText($5),4326)::geography,$6,$7) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,crop=EXCLUDED.crop,geom=EXCLUDED.geom,hectares=EXCLUDED.hectares,acres=EXCLUDED.acres',doc['id'],doc['owner_id'],doc['name'],doc['crop'],f'POLYGON(({points}, {doc["polygon"][0][1]} {doc["polygon"][0][0]}))',doc['hectares'],doc['acres'])
    except Exception as exc: logging.warning('PostGIS sync skipped: %s', exc)
@api.get('/fields')
async def fields(user=Depends(current)):
    return [public(x) async for x in db.fields.find({'owner_id':user['id']},{'_id':0})]
@api.post('/fields')
async def create_field(body: FieldIn,user=Depends(current)):
    area=hectares(body.polygon); doc={'id':str(uuid.uuid4()),'owner_id':user['id'],'name':body.name,'crop':body.crop,'polygon':body.polygon,'hectares':area,'acres':round(area*2.47105,2),'geometry_source':'WGS84 geodesic / PostGIS-ready','created_at':now()}
    await db.fields.insert_one(doc); await postgis_field(doc); return public(dict(doc))
@api.put('/fields/{field_id}')
async def update_field(field_id:str,body:FieldIn,user=Depends(current)):
    if not await db.fields.find_one({'id':field_id,'owner_id':user['id']}): raise HTTPException(404,'Field not found')
    doc=body.model_dump(); doc.update({'hectares':hectares(body.polygon),'acres':round(hectares(body.polygon)*2.47105,2)})
    await db.fields.update_one({'id':field_id},{'$set':doc}); updated=await db.fields.find_one({'id':field_id},{'_id':0}); await postgis_field(updated); return public(updated)
@api.delete('/fields/{field_id}')
async def delete_field(field_id:str,user=Depends(current)):
    r=await db.fields.delete_one({'id':field_id,'owner_id':user['id']})
    if not r.deleted_count: raise HTTPException(404,'Field not found')
    return {'ok':True}

def flood_result(field, before='2024-06-01', after='2024-06-15'):
    hectares=field['hectares']; flooded=round(hectares*.65,2); pct=round(flooded/hectares*100,1)
    severity='HIGH' if pct>=50 else 'MEDIUM' if pct>=20 else 'LOW'
    return {'id':str(uuid.uuid4()),'field_id':field['id'],'field_name':field['name'],'field_hectares':hectares,'field_acres':field['acres'],'flooded_hectares':flooded,'flooded_acres':round(flooded*2.47105,2),'flood_percentage':pct,'severity':severity,'before_date':before,'after_date':after,'data_mode':'DEMO SAR','mask_pixels':14280,'created_at':now()}
@api.post('/flood/analyze')
async def analyze(body:AnalysisIn,user=Depends(current)):
    field=await db.fields.find_one({'id':body.field_id,'owner_id':user['id']},{'_id':0})
    if not field: raise HTTPException(404,'Field not found')
    result=flood_result(field,body.before_date,body.after_date)
    await db.analyses.insert_one(result)
    return public(dict(result))
@api.get('/fields/{field_id}/analyses')
async def history(field_id:str,user=Depends(current)):
    if not await db.fields.find_one({'id':field_id,'owner_id':user['id']},{'_id':0}): raise HTTPException(404,'Field not found')
    return [public(x) async for x in db.analyses.find({'field_id':field_id},{'_id':0}).sort('created_at',-1).limit(20)]
@api.get('/fields/{field_id}/report')
async def report(field_id:str,user=Depends(current)):
    field=await db.fields.find_one({'id':field_id,'owner_id':user['id']},{'_id':0})
    if not field: raise HTTPException(404,'Field not found')
    flood=await db.analyses.find_one({'field_id':field_id},{'_id':0},sort=[('created_at',-1)]) or flood_result(field)
    out=io.BytesIO(); pdf=canvas.Canvas(out,pagesize=A4); width,height=A4
    pdf.setTitle('Flood Evidence Report - '+field['name']); pdf.setFillColorRGB(.02,.12,.16); pdf.rect(0,height-95,width,95,fill=1,stroke=0)
    pdf.setFillColorRGB(0,.85,.9); pdf.setFont('Helvetica-Bold',18); pdf.drawString(42,height-55,'SENTINEL CROP AI')
    pdf.setFillColorRGB(.1,.1,.1); pdf.setFont('Helvetica-Bold',15); pdf.drawString(42,height-135,'Flood Evidence Report')
    pdf.setFont('Helvetica',10); y=height-165
    lines=[('Field',field['name']),('Crop',field['crop']),('Area',f"{field['hectares']} ha / {field['acres']} acres"),('Flooded area',f"{flood['flooded_hectares']} ha / {flood['flooded_acres']} acres"),('Flood percentage',f"{flood['flood_percentage']}%"),('Severity',flood['severity']),('SAR dates',f"{flood['before_date']} → {flood['after_date']}"),('Soil','Loam · Saturated · Waterlogging risk HIGH'),('Weather','27°C · 38 mm rainfall · 84% humidity'),('Recommendation','Rice · 91/100 · NOT RECOMMENDED to plant now')]
    for label,value in lines: pdf.setFillColorRGB(.25,.3,.33); pdf.drawString(42,y,label.upper()); pdf.setFillColorRGB(.05,.07,.09); pdf.drawString(180,y,value); y-=25
    pdf.setFillColorRGB(.75,.2,.18); pdf.setFont('Helvetica-Bold',10); pdf.drawString(42,y-15,'DISCLAIMER'); pdf.setFillColorRGB(.2,.2,.2); pdf.setFont('Helvetica',9); pdf.drawString(42,y-32,'This is an insurance-supporting evidence report, NOT an official insurance assessment.')
    pdf.drawString(42,y-47,'SAR, soil, weather, and recommendations may contain DEMO/ESTIMATED values. Verify with qualified assessors.')
    pdf.save(); out.seek(0)
    return StreamingResponse(out,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{field["name"].replace(" ","_")}_flood_report.pdf"'})
@api.get('/dashboard')
async def dashboard(user=Depends(current)):
    field=await db.fields.find_one({'owner_id':user['id']},{'_id':0})
    if not field: return {'field':None,'alerts':[]}
    latest=await db.analyses.find_one({'field_id':field['id']},{'_id':0},sort=[('created_at',-1)]) or flood_result(field)
    soil={'type':'Loam','moisture':78,'condition':'Saturated','waterlogging_risk':'HIGH','data_mode':'ESTIMATED / DEMO'}
    weather={'temperature':27,'rainfall':38,'humidity':84,'forecast':'Heavy rain likely','data_mode':'DEMO WEATHER'}
    crops=[{'name':'Rice','score':91,'reason':'Tolerates saturated soil','warning':'Delay transplanting until water recedes'},{'name':'Soybean','score':64,'reason':'Good seasonal fit','warning':'Needs drainage before sowing'},{'name':'Maize','score':42,'reason':'Available season window','warning':'Not suitable for current waterlogging'}]
    alerts=['Flood detected inside field','HIGH severity flood condition','Waterlogging risk is HIGH','Planting not recommended until drainage improves']
    return {'field':field,'flood':latest,'soil':soil,'weather':weather,'crops':crops,'readiness':{'percentage':18,'status':'NOT RECOMMENDED','reason':'Flooded soil and heavy rain window'},'alerts':alerts}
@api.post('/devices/register')
async def device_register(payload:dict,user=Depends(current)): return {'device_id':str(uuid.uuid4()),'status':'registered','mode':'OPTIONAL HARDWARE'}
@api.post('/seed/upload')
async def seed_upload(file:UploadFile=File(...),user=Depends(current)): return {'upload_id':str(uuid.uuid4()),'filename':file.filename,'status':'ready_for_analysis','mode':'DEMO'}
@api.post('/seed/analyze')
async def seed_analyze(payload:dict,user=Depends(current)): return {'quality_score':82,'classification':'HEALTHY-LOOKING','notes':['No obvious discoloration detected','Basic visual screening only'],'disclaimer':'DEMO analysis; not guaranteed real/fake seed detection'}
@api.get('/fields/{field_id}/seed-tests')
async def seed_history(field_id:str,user=Depends(current)): return []

app.include_router(api)
cors_origins=os.environ.get('CORS_ORIGINS','*').split(',')
app.add_middleware(CORSMiddleware,allow_credentials='*' not in cors_origins,allow_origins=cors_origins,allow_methods=['*'],allow_headers=['*'])
@app.on_event('startup')
async def startup():
    global postgis_pool
    if os.environ.get('POSTGIS_DATABASE_URL'):
        try:
            import asyncpg
            postgis_pool=await asyncpg.create_pool(os.environ['POSTGIS_DATABASE_URL'])
            async with postgis_pool.acquire() as conn:
                await conn.execute('CREATE EXTENSION IF NOT EXISTS postgis; CREATE TABLE IF NOT EXISTS fields (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL, crop TEXT NOT NULL, geom geography(POLYGON,4326), hectares DOUBLE PRECISION, acres DOUBLE PRECISION)')
        except Exception as exc: logging.warning('PostGIS unavailable; Mongo remains active: %s', exc)
    await db.users.create_index('email',unique=True)
    if not await db.users.find_one({'email':'admin@example.com'}):
        user={'id':str(uuid.uuid4()),'email':'admin@example.com','name':'Demo Admin','role':'admin','password_hash':bcrypt.hashpw(b'admin123',bcrypt.gensalt()).decode(),'created_at':now()}; await db.users.insert_one(user)
    admin=await db.users.find_one({'email':'admin@example.com'},{'_id':0})
    if admin and not await db.fields.find_one({'owner_id':admin['id']}):
        poly=[[51.505,-0.09],[51.51,-0.08],[51.508,-0.06],[51.502,-0.065]]
        area=hectares(poly)
        await db.fields.insert_one({'id':str(uuid.uuid4()),'owner_id':admin['id'],'name':'North Meadow · DEMO','crop':'Wheat','polygon':poly,'hectares':area,'acres':round(area*2.47105,2),'geometry_source':'WGS84 geodesic / PostGIS-ready','created_at':now()})
    await db.fields.update_many({'geometry_source':{'$exists':False}},{'$set':{'geometry_source':'WGS84 geodesic / PostGIS-ready'}})
logging.basicConfig(level=logging.INFO)