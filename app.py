#!/usr/bin/env python3
"""Khet AI local MVP API. Uses only Python's standard library and SQLite."""
import json, os, sqlite3, threading, urllib.parse, urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "khet_ai.db"
STATIC = ROOT / "outputs"
LOCK = threading.Lock()

def now(): return datetime.now(timezone.utc).isoformat()
def conn():
    global DB_PATH
    try:
        c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c
    except sqlite3.OperationalError:
        DB_PATH = Path("/tmp") / "khet_ai.db"
        c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c
def rows(c): return [dict(x) for x in c.fetchall()]

def init_db():
    with conn() as c:
        c.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS farms(id INTEGER PRIMARY KEY, name TEXT NOT NULL, farmer_name TEXT, latitude REAL, longitude REAL, acres REAL, location TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fields(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id), name TEXT NOT NULL, acres REAL, crop TEXT, variety TEXT, stage TEXT, geometry_json TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id), field_id INTEGER REFERENCES fields(id), source TEXT NOT NULL, kind TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL, provenance_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recommendations(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id), field_id INTEGER REFERENCES fields(id), title TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, evidence_json TEXT NOT NULL, confidence REAL NOT NULL, urgency TEXT NOT NULL, expected_impact TEXT, status TEXT NOT NULL DEFAULT 'pending', requires_approval INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, approved_at TEXT, outcome_json TEXT);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id), recommendation_id INTEGER REFERENCES recommendations(id), channel TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, farm_id INTEGER, event TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER, actor TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        if c.execute("SELECT count(*) FROM farms").fetchone()[0] == 0: seed(c)

def audit(c, farm_id, event, entity_type, entity_id, actor, payload):
    c.execute("INSERT INTO audit_log(farm_id,event,entity_type,entity_id,actor,payload_json,created_at) VALUES(?,?,?,?,?,?,?)", (farm_id,event,entity_type,entity_id,actor,json.dumps(payload),now()))

def seed(c):
    t=now(); farm=c.execute("INSERT INTO farms(name,farmer_name,latitude,longitude,acres,location,created_at) VALUES(?,?,?,?,?,?,?)", ("Gautam Farm","Ravi Gautam",19.9975,73.7898,8.4,"Nashik, Maharashtra",t)).lastrowid
    fields=[]
    for n,a,crop,stage in [("Wheat Field A",3.2,"Wheat","Tillering"),("Tomato Field B",2.1,"Tomato","Flowering"),("Onion Field C",3.1,"Onion","Bulbing")]:
        fields.append(c.execute("INSERT INTO fields(farm_id,name,acres,crop,stage,created_at) VALUES(?,?,?,?,?,?)",(farm,n,a,crop,stage,t)).lastrowid)
    add_observation(c,farm,fields[0],"sensor","soil_moisture",{"percent":21,"depth_cm":20},"seed")
    add_observation(c,farm,fields[0],"satellite","vegetation",{"ndvi":0.58,"baseline_ndvi":0.67,"anomaly":"western zone decline"},"seed")
    add_observation(c,farm,None,"weather","forecast",{"rain_mm_7d":8,"temperature_c":29,"humidity_pct":72,"wind_kph":7},"seed")
    evaluate_rules(c,farm,actor="system")
    audit(c,farm,"seeded","farm",farm,"system",{"note":"Demo farm created. Replace with farmer onboarding data."})

def add_observation(c,farm_id,field_id,source,kind,payload,provider):
    provenance={"provider":provider,"ingested_at":now(),"schema_version":"1.0"}
    return c.execute("INSERT INTO observations(farm_id,field_id,source,kind,observed_at,payload_json,provenance_json) VALUES(?,?,?,?,?,?,?)",(farm_id,field_id,source,kind,now(),json.dumps(payload),json.dumps(provenance))).lastrowid

def latest(c,farm_id,field_id,kind):
    q="SELECT * FROM observations WHERE farm_id=? AND kind=?"; args=[farm_id,kind]
    if field_id is None: q+=" AND field_id IS NULL"
    else: q+=" AND field_id=?"; args.append(field_id)
    q+=" ORDER BY observed_at DESC LIMIT 1"; r=c.execute(q,args).fetchone(); return json.loads(r['payload_json']) if r else None

def recommendation(c,farm,field,title,action,reason,evidence,confidence,urgency,impact):
    existing=c.execute("SELECT id FROM recommendations WHERE farm_id=? AND field_id IS ? AND title=? AND status='pending'",(farm,field,title)).fetchone()
    if existing:return existing[0]
    rid=c.execute("INSERT INTO recommendations(farm_id,field_id,title,action,reason,evidence_json,confidence,urgency,expected_impact,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(farm,field,title,action,reason,json.dumps(evidence),confidence,urgency,impact,now())).lastrowid
    c.execute("INSERT INTO alerts(farm_id,recommendation_id,channel,status,payload_json,created_at) VALUES(?,?,?,?,?,?)",(farm,rid,"in_app","queued",json.dumps({"title":title,"urgency":urgency}),now()))
    audit(c,farm,"created","recommendation",rid,"rule_engine",{"confidence":confidence,"evidence":evidence}); return rid

def evaluate_rules(c,farm_id,actor="rule_engine"):
    weather=latest(c,farm_id,None,"forecast") or {}; created=[]
    for f in rows(c.execute("SELECT * FROM fields WHERE farm_id=?",(farm_id,))):
        soil=latest(c,farm_id,f['id'],"soil_moisture") or {}; veg=latest(c,farm_id,f['id'],"vegetation") or {}
        if soil.get('percent',100)<25 and f['crop'].lower() in ('wheat','tomato','onion'):
            created.append(recommendation(c,farm_id,f['id'],f"Irrigate {f['name']} in the next safe window", "Review and approve a morning irrigation plan.", "Available soil moisture is below the farm threshold for this crop stage.", {"soil_moisture_percent":soil['percent'],"rain_mm_7d":weather.get('rain_mm_7d'),"field":f['name']}, .82,"today","Reduce water-stress risk and avoid unnecessary irrigation."))
        if f['crop'].lower()=="tomato" and weather.get('humidity_pct',0)>=70:
            created.append(recommendation(c,farm_id,f['id'],"Inspect tomato leaves for early blight", "Inspect 12 plants and upload clear leaf photos before applying treatment.", "High humidity raises disease risk; visual confirmation is required.", {"humidity_pct":weather['humidity_pct'],"crop_stage":f['stage']}, .64,"today","Detect a possible outbreak early; no chemical recommendation is made."))
        if veg.get('ndvi') and veg.get('baseline_ndvi') and veg['ndvi'] < veg['baseline_ndvi']*.92:
            created.append(recommendation(c,farm_id,f['id'],f"Inspect low-vigour zone in {f['name']}", "Walk the identified zone and record water, pest and nutrient observations.", "Vegetation index is below the field's historical baseline; satellite data alone cannot diagnose the cause.", veg, .61,"this_week","Narrow the cause before spending on an intervention."))
    audit(c,farm_id,"evaluated","farm",farm_id,actor,{"recommendations_created":created}); return created

def weather_refresh(c,farm_id):
    farm=c.execute("SELECT * FROM farms WHERE id=?",(farm_id,)).fetchone()
    if not farm or farm['latitude'] is None: raise ValueError("Farm requires latitude and longitude for weather refresh")
    params=urllib.parse.urlencode({"latitude":farm['latitude'],"longitude":farm['longitude'],"current":"temperature_2m,relative_humidity_2m,wind_speed_10m","daily":"precipitation_sum","forecast_days":7,"timezone":"auto"})
    url="https://api.open-meteo.com/v1/forecast?"+params
    with urllib.request.urlopen(url,timeout=12) as r: data=json.loads(r.read())
    daily=data.get('daily',{}); payload={"temperature_c":data.get('current',{}).get('temperature_2m'),"humidity_pct":data.get('current',{}).get('relative_humidity_2m'),"wind_kph":data.get('current',{}).get('wind_speed_10m'),"rain_mm_7d":round(sum(daily.get('precipitation_sum',[])),1),"provider_url":url}
    add_observation(c,farm_id,None,"weather","forecast",payload,"Open-Meteo"); evaluate_rules(c,farm_id,"weather_adapter"); return payload

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(STATIC),**kwargs)
    def send_json(self,status,data):
        raw=json.dumps(data,default=str).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers(); self.wfile.write(raw)
    def body(self):
        n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(n) or b'{}')
    def do_OPTIONS(self): self.send_response(204); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','Content-Type, Authorization'); self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS'); self.end_headers()
    def do_GET(self):
        path=self.path.split('?')[0]; parts=path.strip('/').split('/')
        try:
            with LOCK,conn() as c:
                if path=='/api/health': return self.send_json(200,{"status":"ok","service":"khet-ai","database":str(DB_PATH)})
                if path=='/api/farms': return self.send_json(200,{"farms":rows(c.execute("SELECT * FROM farms ORDER BY id"))})
                if len(parts)==4 and parts[:2]==['api','farms'] and parts[3]=='twin':
                    farm=int(parts[2]); f=dict(c.execute("SELECT * FROM farms WHERE id=?",(farm,)).fetchone() or {}); f['fields']=rows(c.execute("SELECT * FROM fields WHERE farm_id=?",(farm,))); f['observations']=rows(c.execute("SELECT * FROM observations WHERE farm_id=? ORDER BY observed_at DESC LIMIT 100",(farm,))); return self.send_json(200,{"digital_twin":f})
                if len(parts)==4 and parts[:2]==['api','farms'] and parts[3]=='recommendations':
                    return self.send_json(200,{"recommendations":rows(c.execute("SELECT r.*,f.name AS field_name FROM recommendations r LEFT JOIN fields f ON f.id=r.field_id WHERE r.farm_id=? ORDER BY CASE urgency WHEN 'today' THEN 0 ELSE 1 END, created_at DESC",(int(parts[2]),)))})
        except Exception as e:return self.send_json(400,{"error":str(e)})
        return super().do_GET()
    def do_POST(self):
        path=self.path.split('?')[0]; parts=path.strip('/').split('/')
        try:
            data=self.body()
            with LOCK,conn() as c:
                if path=='/api/farms':
                    required=['name','farmer_name','latitude','longitude']; missing=[x for x in required if x not in data]
                    if missing: return self.send_json(422,{"error":"Missing fields","fields":missing})
                    farm=c.execute("INSERT INTO farms(name,farmer_name,latitude,longitude,acres,location,created_at) VALUES(?,?,?,?,?,?,?)",(data['name'],data['farmer_name'],data['latitude'],data['longitude'],data.get('acres'),data.get('location',''),now())).lastrowid
                    for f in data.get('fields',[]): c.execute("INSERT INTO fields(farm_id,name,acres,crop,variety,stage,geometry_json,created_at) VALUES(?,?,?,?,?,?,?,?)",(farm,f['name'],f.get('acres'),f.get('crop'),f.get('variety'),f.get('stage'),json.dumps(f.get('geometry')),now()))
                    audit(c,farm,"created","farm",farm,"farmer_onboarding",data); return self.send_json(201,{"farm_id":farm,"message":"Farm digital twin created"})
                if len(parts)==4 and parts[:2]==['api','farms'] and parts[3]=='refresh-weather': return self.send_json(200,{"weather":weather_refresh(c,int(parts[2]))})
                if len(parts)==4 and parts[:2]==['api','farms'] and parts[3]=='evaluate': return self.send_json(200,{"created":evaluate_rules(c,int(parts[2]))})
                if len(parts)==3 and parts[:2]==['api','recommendations'] and parts[2].isdigit():
                    rid=int(parts[2]); r=c.execute("SELECT * FROM recommendations WHERE id=?",(rid,)).fetchone()
                    if not r:return self.send_json(404,{"error":"Recommendation not found"})
                    c.execute("UPDATE recommendations SET status='approved',approved_at=? WHERE id=?",(now(),rid)); audit(c,r['farm_id'],"approved","recommendation",rid,data.get('actor','farmer'),data); return self.send_json(200,{"recommendation_id":rid,"status":"approved","next_step":"Action is ready for a configured irrigation/task connector."})
                if path=='/api/ingest/observation':
                    req=['farm_id','source','kind','payload']; missing=[x for x in req if x not in data]
                    if missing:return self.send_json(422,{"error":"Missing fields","fields":missing})
                    oid=add_observation(c,data['farm_id'],data.get('field_id'),data['source'],data['kind'],data['payload'],data.get('provider','external_webhook')); evaluate_rules(c,data['farm_id'],'integration_webhook'); return self.send_json(201,{"observation_id":oid})
        except Exception as e:return self.send_json(400,{"error":str(e)})
        return self.send_json(404,{"error":"Unknown API route"})

if __name__=='__main__':
    init_db(); port=int(os.getenv('PORT','8000')); print(f'Khet AI running at http://localhost:{port}'); ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
