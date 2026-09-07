from dotenv import load_dotenv
load_dotenv()
import os, uuid, math, logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import bcrypt, jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(os.environ['MONGO_URL']); db = client[os.environ['DB_NAME']]
app = FastAPI(title='SAR Satellite Crop Flood Engine', version='1.0.0')
api = APIRouter(prefix='/api')
SECRET = os.environ.get('JWT_SECRET', 'local-demo-secret-change-me')

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
class FieldIn(BaseModel): name: str = Field(min_length=2); crop: str = 'Wheat'; polygon: list[list[float]] = Field(min_length=3)
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
    # Demo planar calculation suitable for small farm polygons; replace with ST_Area geography in PostGIS deployment.
    area=abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2)
    return max(0.25, round(area*111000*111000/10000,2))
@api.get('/fields')
async def fields(user=Depends(current)):
    return [public(x) async for x in db.fields.find({'owner_id':user['id']},{'_id':0})]
@api.post('/fields')
async def create_field(body: FieldIn,user=Depends(current)):
    area=hectares(body.polygon); doc={'id':str(uuid.uuid4()),'owner_id':user['id'],'name':body.name,'crop':body.crop,'polygon':body.polygon,'hectares':area,'acres':round(area*2.47105,2),'created_at':now()}
    await db.fields.insert_one(doc); return public(doc)
@api.put('/fields/{field_id}')
async def update_field(field_id:str,body:FieldIn,user=Depends(current)):
    if not await db.fields.find_one({'id':field_id,'owner_id':user['id']}): raise HTTPException(404,'Field not found')
    doc=body.model_dump(); doc.update({'hectares':hectares(body.polygon),'acres':round(hectares(body.polygon)*2.47105,2)})
    await db.fields.update_one({'id':field_id},{'$set':doc}); return public(await db.fields.find_one({'id':field_id},{'_id':0}))
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
    return [public(x) async for x in db.analyses.find({'field_id':field_id},{'_id':0}).sort('created_at',-1).limit(20)]
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
app.add_middleware(CORSMiddleware,allow_credentials=True,allow_origins=os.environ.get('CORS_ORIGINS','*').split(','),allow_methods=['*'],allow_headers=['*'])
@app.on_event('startup')
async def startup():
    await db.users.create_index('email',unique=True)
    if not await db.users.find_one({'email':'admin@example.com'}):
        user={'id':str(uuid.uuid4()),'email':'admin@example.com','name':'Demo Admin','role':'admin','password_hash':bcrypt.hashpw(b'admin123',bcrypt.gensalt()).decode(),'created_at':now()}; await db.users.insert_one(user)
    admin=await db.users.find_one({'email':'admin@example.com'},{'_id':0})
    if admin and not await db.fields.find_one({'owner_id':admin['id']}):
        poly=[[51.505,-0.09],[51.51,-0.08],[51.508,-0.06],[51.502,-0.065]]
        area=hectares(poly)
        await db.fields.insert_one({'id':str(uuid.uuid4()),'owner_id':admin['id'],'name':'North Meadow · DEMO','crop':'Wheat','polygon':poly,'hectares':area,'acres':round(area*2.47105,2),'created_at':now()})
logging.basicConfig(level=logging.INFO)