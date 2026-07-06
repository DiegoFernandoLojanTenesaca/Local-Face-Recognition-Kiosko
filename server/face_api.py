#!/data/data/com.termux/files/usr/bin/python
# App (PWA) de asistencia facial: entrada/salida+horas, foto al enrolar, reporte, config.
import os, sys, csv, json, re, datetime, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from collections import defaultdict
from flask import Flask, request, jsonify, Response, send_file
from PIL import Image, ImageDraw
import face_core

app = Flask(__name__)
TMP   = os.path.expanduser("~/.face_uploads"); os.makedirs(TMP, exist_ok=True)
ICON  = os.path.expanduser("~/face_icons");    os.makedirs(ICON, exist_ok=True)
PHOTO = os.path.expanduser("~/face_photos");   os.makedirs(PHOTO, exist_ok=True)
ATT   = os.path.expanduser("~/attendance.csv")
CFG   = os.path.expanduser("~/face_config.json")
DEF   = {"business":"", "threshold":0.35, "dup_window":300, "liveness":True, "live_threshold":0.5}
_c = itertools.count()

def _cfg():
    c=dict(DEF)
    if os.path.exists(CFG):
        try: c.update(json.load(open(CFG)))
        except: pass
    return c
def _safe(n): return re.sub(r"[^\w]+","_", n)[:40] or "x"
def _read():
    if not os.path.exists(ATT): return []
    with open(ATT) as f: return [r for r in csv.reader(f) if r]
def _today(name):
    hoy=datetime.date.today().isoformat()
    return sorted(r[0] for r in _read() if len(r)>=2 and r[1]==name and r[0].startswith(hoy))

def _make_icon(size):
    p=os.path.join(ICON,f"icon-{size}.png")
    if os.path.exists(p): return
    img=Image.new("RGB",(size,size),(99,102,241)); d=ImageDraw.Draw(img)
    m=size*0.17; d.ellipse([m,m,size-m,size-m],fill=(255,255,255)); r=size*0.05; ey=size*0.42
    for ex in (size*0.39,size*0.61): d.ellipse([ex-r,ey-r,ex+r,ey+r],fill=(30,40,60))
    d.arc([size*0.35,size*0.40,size*0.65,size*0.68],20,160,fill=(30,40,60),width=max(3,int(size*0.035))); img.save(p)
_make_icon(192); _make_icon(512)

def _upload():
    f=request.files.get("file")
    if not f: return None
    p=os.path.join(TMP,f"u{os.getpid()}_{next(_c)}.jpg"); f.save(p); return p

# ---------- API ----------
@app.post("/enroll")
def enroll():
    name=request.form.get("name")
    if not name: return jsonify(error="falta 'name'"),400
    p=_upload()
    if not p: return jsonify(error="falta 'file'"),400
    ok,msg=face_core.enroll(name,p)
    if ok:
        try: Image.open(p).convert("RGB").resize((160,213)).save(os.path.join(PHOTO,_safe(name)+".jpg"),quality=80)
        except: pass
    os.remove(p)
    return jsonify(ok=ok,message=msg),(200 if ok else 422)

@app.post("/attendance")
def attendance():
    p=_upload()
    if not p: return jsonify(error="falta 'file'"),400
    cfg=_cfg(); r=face_core.identify_live(p, threshold=float(cfg["threshold"])); os.remove(p)
    n,s,live = r["name"], r["sim"], r["live"]
    liv = round(live,2) if live is not None else None
    if n in (None,"desconocido"):
        return jsonify(name="desconocido", similarity=round(s,3), marked=False, live=liv)
    if cfg.get("liveness") and live is not None and live < float(cfg["live_threshold"]):
        return jsonify(name=n, similarity=round(s,3), marked=False, spoof=True, live=liv)
    tm=_today(n); now=datetime.datetime.now()
    if tm:                                              # anti-duplicado
        try:
            if (now-datetime.datetime.fromisoformat(tm[-1])).total_seconds() < float(cfg["dup_window"]):
                return jsonify(name=n,similarity=round(s,3),marked=False,duplicate=True,last=tm[-1][11:16])
        except ValueError: pass
    tipo = "entrada" if len(tm)==0 else "salida"
    horas = None
    if tipo=="salida":
        try: horas=round((now-datetime.datetime.fromisoformat(tm[0])).total_seconds()/3600,1)
        except ValueError: pass
    ts=now.isoformat(timespec="seconds")
    with open(ATT,"a",newline="") as f: csv.writer(f).writerow([ts,n,round(s,3),tipo])
    return jsonify(name=n,similarity=round(s,3),marked=True,tipo=tipo,time=ts,horas=horas)

@app.post("/esp_mark")          # ESP32-CAM: envía el JPEG crudo en el cuerpo, respuesta simple
def esp_mark():
    data=request.get_data()
    if not data or len(data)<500: return jsonify(name="sin imagen",marked=False),400
    p=os.path.join(TMP,f"esp_{os.getpid()}_{next(_c)}.jpg")
    with open(p,"wb") as f: f.write(data)
    cfg=_cfg(); r=face_core.identify_live(p, threshold=float(cfg["threshold"])); os.remove(p)
    n,s,live=r["name"],r["sim"],r["live"]
    if n in (None,"desconocido"): return jsonify(name="desconocido",marked=False)
    if cfg.get("liveness") and live is not None and live<float(cfg["live_threshold"]):
        return jsonify(name=n,marked=False,spoof=True)
    tm=_today(n); now=datetime.datetime.now()
    if tm:
        try:
            if (now-datetime.datetime.fromisoformat(tm[-1])).total_seconds()<float(cfg["dup_window"]):
                return jsonify(name=n,marked=False,duplicate=True)
        except ValueError: pass
    tipo="entrada" if len(tm)==0 else "salida"
    ts=now.isoformat(timespec="seconds")
    with open(ATT,"a",newline="") as f: csv.writer(f).writerow([ts,n,round(s,3),tipo])
    return jsonify(name=n,marked=True,tipo=tipo,time=ts[11:16])

# ---------- Multi-kiosko: servidor central (varios kioscos comparten personas y registro) ----------
CENTRAL_P=os.path.expanduser("~/central_people.json")
CENTRAL_L=os.path.expanduser("~/central_log.json")
def _load_json(p,d):
    try: return json.load(open(p))
    except: return d
@app.post("/sync/enroll")
def sync_enroll():
    d=request.get_json(force=True,silent=True) or {}
    if not d.get("name") or not d.get("emb"): return jsonify(error="faltan datos"),400
    ppl=_load_json(CENTRAL_P,[])
    if not any(x["name"]==d["name"] for x in ppl):
        ppl.append({"name":d["name"],"emb":d["emb"]}); json.dump(ppl,open(CENTRAL_P,"w"))
    return jsonify(ok=True,count=len(ppl))
@app.get("/sync/people")
def sync_people(): return jsonify(people=_load_json(CENTRAL_P,[]))
@app.post("/sync/mark")
def sync_mark():
    d=request.get_json(force=True,silent=True) or {}
    log=_load_json(CENTRAL_L,[]); log.append([d.get("ts"),d.get("name"),d.get("tipo"),d.get("tarde","")])
    json.dump(log,open(CENTRAL_L,"w")); return jsonify(ok=True,count=len(log))
@app.get("/sync/log")
def sync_log(): return jsonify(rows=_load_json(CENTRAL_L,[])[::-1])

@app.post("/detect")
def detect_ep():
    p=_upload()
    if not p: return jsonify(faces=[])
    img=np.array(Image.open(p).convert("RGB")); os.remove(p)
    d=face_core.detect(img); h,w=img.shape[:2]; faces=[]
    if d is not None:
        for r in d:
            faces.append({"box":[float(r[0]/w),float(r[1]/h),float(r[2]/w),float(r[3]/h)],
                "score":round(float(r[4]),2),
                "points":[[float(r[5+2*i]/w),float(r[6+2*i]/h)] for i in range(5)]})
    return jsonify(faces=faces)

@app.get("/people")
def people():
    names,_=face_core._load()
    return jsonify(people=[{"name":n,"photo":os.path.exists(os.path.join(PHOTO,_safe(n)+".jpg"))} for n in names], count=len(names))

@app.get("/photo/<name>")
def photo(name):
    p=os.path.join(PHOTO,_safe(name)+".jpg")
    return send_file(p) if os.path.exists(p) else ("",404)

@app.get("/log")
def log(): return jsonify(rows=_read()[::-1])

@app.get("/report")
def report():
    date=request.args.get("date") or datetime.date.today().isoformat()
    per=defaultdict(list)
    for r in _read():
        if r[0].startswith(date): per[r[1]].append(r[0])
    out=[]
    for name,ts in per.items():
        ts.sort(); ent=ts[0]; sal=ts[-1]; horas=0
        if len(ts)>1:
            try: horas=round((datetime.datetime.fromisoformat(sal)-datetime.datetime.fromisoformat(ent)).total_seconds()/3600,1)
            except ValueError: pass
        out.append({"name":name,"entrada":ent[11:16],"salida":sal[11:16] if len(ts)>1 else "—","horas":horas,"marcas":len(ts)})
    out.sort(key=lambda x:x["entrada"])
    return jsonify(date=date, rows=out)

@app.get("/export.csv")
def export():
    data="fecha,nombre,similitud,tipo\n"+(open(ATT).read() if os.path.exists(ATT) else "")
    return Response(data,mimetype="text/csv",headers={"Content-Disposition":"attachment;filename=asistencia.csv"})

@app.get("/config")
def get_config(): return jsonify(_cfg())
@app.post("/config")
def set_config():
    c=_cfg()
    if request.form.get("business") is not None: c["business"]=request.form.get("business").strip()
    if request.form.get("liveness") is not None: c["liveness"]=request.form.get("liveness")=="1"
    for k in ("threshold","dup_window","live_threshold"):
        if request.form.get(k):
            try: c[k]=float(request.form.get(k))
            except ValueError: pass
    json.dump(c,open(CFG,"w")); return jsonify(ok=True,**c)

@app.post("/delete_person")
def del_person():
    name=request.form.get("name") or ""
    face_core.delete_person(name)
    ph=os.path.join(PHOTO,_safe(name)+".jpg")
    if os.path.exists(ph): os.remove(ph)
    return jsonify(ok=True)

@app.post("/rename_person")
def ren_person():
    old=request.form.get("old"); new=(request.form.get("new") or "").strip()
    if not new: return jsonify(error="falta nuevo nombre"),400
    face_core.rename_person(old,new)
    po=os.path.join(PHOTO,_safe(old)+".jpg"); pn=os.path.join(PHOTO,_safe(new)+".jpg")
    if os.path.exists(po): os.replace(po,pn)
    return jsonify(ok=True)

@app.post("/delete_mark")
def del_mark():
    ts=request.form.get("ts")
    rows=[r for r in _read() if r[0]!=ts]
    with open(ATT,"w",newline="") as f: csv.writer(f).writerows(rows)
    return jsonify(ok=True)

@app.post("/analyze")            # datos internos del modelo, para demostrar
def analyze_ep():
    p=_upload()
    if not p: return jsonify(faces=0)
    r=face_core.analyze(p); os.remove(p); return jsonify(r)

# ---------- PWA ----------
@app.get("/manifest.json")
def manifest():
    return jsonify(name="Asistencia Facial",short_name="Asistencia",start_url="/kiosk",display="standalone",
        orientation="portrait",background_color="#0a0e17",theme_color="#0a0e17",
        icons=[{"src":"/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any maskable"},
               {"src":"/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}])
@app.get("/sw.js")
def sw(): return Response("self.addEventListener('fetch',e=>{});",mimetype="application/javascript")
@app.get("/icon-<int:sz>.png")
def icon_png(sz): return send_file(os.path.join(ICON,f"icon-{sz}.png")) if sz in (192,512) else ("",404)

# ---------- ICONOS (Lucide, inline via tokens {{name}} / {{name:lg}}) ----------
LU = {
 "camera":'<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
 "scan":'<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="10" r="2.5"/><path d="M8.5 16a3.5 3.5 0 0 1 7 0"/>',
 "user":'<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
 "users":'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
 "user-plus":'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/>',
 "info":'<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
 "cpu":'<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
 "shield":'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
 "home":'<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
 "max":'<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
 "edit":'<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"/>',
 "trash":'<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
 "download":'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
 "image":'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
 "sliders":'<line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="1" x2="7" y1="14" y2="14"/><line x1="9" x2="15" y1="8" y2="8"/><line x1="17" x2="23" y1="16" y2="16"/>',
 "check":'<path d="M20 6 9 17l-5-5"/>',
 "x":'<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
 "clock":'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
 "save":'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
 "chart":'<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
 "clock-in":'<path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="10"/>',
 "activity":'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
}
def icon(name, cls="ic"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{LU.get(name,"")}</svg>'
def render(t):
    return re.sub(r"\{\{([a-z-]+)(?::(lg|sm))?\}\}", lambda m: icon(m.group(1), "ic "+m.group(2) if m.group(2) else "ic"), t)

# ---------- UI ----------
HEAD="""<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content=#0a0e17><link rel=manifest href=/manifest.json>
<link rel=apple-touch-icon href=/icon-192.png><meta name=apple-mobile-web-app-capable content=yes>
<meta name=mobile-web-app-capable content=yes><title>Asistencia</title>
<script>if('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js')}</script>
<style>
:root{--bg:#0a0e17;--line:#1e2740;--txt:#e7ecf5;--mut:#8a99b5;--acc:#6366f1;--ok:#34d399;--no:#fb7185}
*{box-sizing:border-box;font-family:-apple-system,'Segoe UI',system-ui,Arial,sans-serif;margin:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--txt);min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;inset:0;z-index:-1;background:radial-gradient(900px 500px at 85% -10%,#4f46e522,transparent 60%),radial-gradient(700px 420px at -10% 5%,#0ea5e916,transparent 55%)}
.top{position:sticky;top:0;z-index:9;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 16px;background:#0a0e17d9;backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:8px;color:var(--txt);text-decoration:none;font-size:15px} .brand b{font-weight:800;letter-spacing:-.3px} .brand .ic{color:var(--acc);width:21px;height:21px}
nav{display:flex;gap:3px} nav a{color:var(--mut);text-decoration:none;font-size:13px;font-weight:600;padding:8px 12px;border-radius:10px} nav a:active{background:#ffffff12}
.wrap{max-width:760px;margin:0 auto;padding:18px 16px 46px}
h1{font-size:20px;font-weight:800;letter-spacing:-.3px;margin:2px 0 3px;display:flex;align-items:center;gap:9px}
.sub{color:var(--mut);font-size:13px;margin:0 0 16px}
h2{font-size:11px;font-weight:700;letter-spacing:.7px;margin:0 0 12px;color:var(--mut);text-transform:uppercase;display:flex;align-items:center;gap:7px}
.card{background:linear-gradient(180deg,#111725,#0d1320);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0}
.ic{width:18px;height:18px;stroke-width:2;flex:none;vertical-align:-3px} .ic.lg{width:23px;height:23px} h1 .ic{width:22px;height:22px;color:var(--acc)} h2 .ic{color:var(--acc)}
a.btn,button{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:linear-gradient(180deg,#6366f1,#4f46e5);color:#fff;border:0;border-radius:12px;padding:13px 18px;font-size:15px;font-weight:700;cursor:pointer;text-decoration:none;box-shadow:0 8px 20px -10px #4f46e5;transition:transform .1s,filter .1s}
button:active,a.btn:active{transform:translateY(1px);filter:brightness(1.05)}
.btn.sec,a.sec,button.sec{background:#182034;border:1px solid var(--line);box-shadow:none;color:#cdd7ea}
input,select{width:100%;padding:12px 13px;border-radius:11px;border:1px solid var(--line);background:#0b101c;color:#fff;font-size:15px;outline:none}
input:focus{border-color:#6366f1aa}
input[type=range]{padding:0;height:5px;accent-color:var(--acc)} input[type=checkbox]{width:auto;transform:scale(1.3)}
label{display:block} label small{display:block;margin-bottom:4px}
table{width:100%;border-collapse:collapse} th,td{text-align:left;padding:9px 8px;font-size:13px;border-bottom:1px solid #ffffff0d} th{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.5px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center} small{color:var(--mut)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:4px 0 6px}
.kpi{background:linear-gradient(180deg,#111725,#0d1320);border:1px solid var(--line);border-radius:14px;padding:13px}
.kpi .n{font-size:23px;font-weight:800;letter-spacing:-.5px} .kpi .l{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.4px;margin-top:3px;display:flex;align-items:center;gap:5px} .kpi .ic{width:13px;height:13px}
.stage{position:relative;width:100%;line-height:0;border-radius:18px;overflow:hidden;border:1px solid var(--line)}
video{width:100%;background:#000;display:block} #ov{position:absolute;inset:0;width:100%;height:100%}
.kiosk{display:flex;flex-direction:column;min-height:100vh;padding:14px 14px calc(14px + env(safe-area-inset-bottom));gap:11px}
#res{font-size:21px;font-weight:800;text-align:center;min-height:30px;margin:4px 0;display:flex;align-items:center;justify-content:center;gap:9px;letter-spacing:-.3px}
.ok{color:var(--ok)}.no{color:var(--no)}
.per{display:flex;align-items:center;gap:11px;padding:9px 0;border-bottom:1px solid #ffffff0a} .per:last-child{border:0} .per img{width:42px;height:42px;border-radius:11px;object-fit:cover;background:#182034;border:1px solid var(--line)}
.chip{display:inline-flex;align-items:center;gap:5px;background:#6366f118;color:#a5b4fc;border:1px solid #6366f133;padding:4px 10px;border-radius:20px;font-size:12px;margin:2px;font-weight:600}
.step{display:flex;gap:12px;margin:0 0 15px;align-items:flex-start} .step:last-child{margin:0}
.stepic{width:38px;height:38px;border-radius:11px;background:#6366f118;border:1px solid #6366f133;color:var(--acc);display:flex;align-items:center;justify-content:center;flex:none}
.bar{background:#182034;border-radius:6px;height:8px;overflow:hidden;margin-top:5px} .bar>i{display:block;height:100%;border-radius:6px}
</style>"""

TOP="""<div class=top><a class=brand href="/">{{scan}}<b>Asistencia</b></a>
<nav><a href="/kiosk">Kiosko</a><a href="/admin">Admin</a><a href="/demo">Demo</a></nav></div>"""

PORTADA=HEAD+TOP+"""<div class=wrap>
<h1>{{scan}}Asistencia Facial</h1><div class=sub>Reconocimiento facial 100% en el teléfono, sin nube.</div>
<div class=kpis><div class=kpi><div class=n id=kp>–</div><div class=l>{{users}}Personas</div></div>
<div class=kpi><div class=n id=km>–</div><div class=l>{{clock}}Marcas hoy</div></div>
<div class=kpi><div class=n id=kl>–</div><div class=l>{{shield}}Anti-foto</div></div></div>
<a class=btn href="/kiosk" style=width:100%;margin-top:12px;padding:16px;font-size:16px>{{camera:lg}}Abrir kiosko de marcado</a>
<div class=row style=margin-top:10px;flex-wrap:nowrap>
 <a class="btn sec" href="/admin" style=flex:1>{{sliders}}Admin</a>
 <a class="btn sec" href="/demo" style=flex:1>{{cpu}}Demo</a>
 <a class="btn sec" href="/info" style=flex:1>{{info}}Info</a></div>
<div class=card><small>Instálala como app: menú de Chrome (⋮) → <b>Instalar app</b> → ícono a pantalla completa.</small></div></div>
<script>
fetch('/people').then(r=>r.json()).then(p=>kp.textContent=p.count);
fetch('/report').then(r=>r.json()).then(l=>km.textContent=l.rows.reduce((a,b)=>a+b.marcas,0));
fetch('/config').then(r=>r.json()).then(c=>kl.textContent=c.liveness?'ON':'OFF');
</script>"""

KIOSK=HEAD+"""<div class=kiosk>
<div style=display:flex;align-items:center;justify-content:space-between>
 <a class=brand href="/">{{scan}}<b id=bn>Asistencia</b></a>
 <button class=sec style=padding:9px11px onclick=fs()>{{max}}</button></div>
<div class=stage><video id=v autoplay playsinline muted></video><canvas id=ov></canvas></div>
<div style=text-align:center;font-size:12px;color:var(--mut)><span style=color:#22d3ee>●</span> ojos&nbsp; <span style=color:#fbbf24>●</span> nariz&nbsp; <span style=color:#f472b6>●</span> boca&nbsp;·&nbsp;5 puntos del detector</div>
<div id=res>Enfoca tu cara…</div>
<button style=width:100%;padding:18px;font-size:17px onclick=mark()>{{check:lg}}Marcar asistencia</button>
<canvas id=c style=display:none></canvas><canvas id=d style=display:none></canvas></div>
<script>
let busy=false,detecting=false;const oc=ov.getContext('2d');
const COL=['#22d3ee','#22d3ee','#fbbf24','#f472b6','#f472b6'];
fetch('/config').then(r=>r.json()).then(c=>{if(c.business)bn.textContent=c.business;});
function fs(){let e=document.documentElement;e.requestFullscreen&&e.requestFullscreen();}
navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:640}}).then(s=>{v.srcObject=s;
 v.onloadedmetadata=()=>{ov.width=v.videoWidth;ov.height=v.videoHeight;loop();};})
 .catch(e=>{res.textContent='Sin cámara: '+e;res.className='no';});
async function loop(){
 if(v.videoWidth&&!detecting){detecting=true;
  let sc=document.getElementById('d'),sw=Math.min(360,v.videoWidth);
  sc.width=sw;sc.height=sw*v.videoHeight/v.videoWidth;sc.getContext('2d').drawImage(v,0,0,sc.width,sc.height);
  try{let b=await new Promise(r=>sc.toBlob(r,'image/jpeg',0.7));let fd=new FormData();fd.append('file',b,'d.jpg');
   let j=await(await fetch('/detect',{method:'POST',body:fd})).json();drawFaces(j.faces);}catch(e){}
  detecting=false;}
 setTimeout(loop,150);}
function drawFaces(fs){oc.clearRect(0,0,ov.width,ov.height);
 for(let f of fs){let x1=f.box[0]*ov.width,y1=f.box[1]*ov.height,x2=f.box[2]*ov.width,y2=f.box[3]*ov.height;
  oc.strokeStyle='#6366f1';oc.lineWidth=Math.max(2,ov.width/150);oc.strokeRect(x1,y1,x2-x1,y2-y1);oc.shadowBlur=12;
  for(let i=0;i<f.points.length;i++){let p=f.points[i];oc.fillStyle=COL[i]||'#22d3ee';oc.shadowColor=oc.fillStyle;
   oc.beginPath();oc.arc(p[0]*ov.width,p[1]*ov.height,Math.max(4,ov.width/90),0,7);oc.fill();}
  oc.shadowBlur=0;oc.fillStyle='#a5b4fc';oc.font='bold '+Math.max(13,ov.width/27)+'px sans-serif';oc.fillText('rostro '+Math.round(f.score*100)+'%',x1,y1-6);}}
function mark(){if(busy)return;busy=true;
 let cv=document.getElementById('c');cv.width=v.videoWidth;cv.height=v.videoHeight;cv.getContext('2d').drawImage(v,0,0);res.textContent='…';res.className='';
 cv.toBlob(b=>{let f=new FormData();f.append('file',b,'s.jpg');
  fetch('/attendance',{method:'POST',body:f}).then(r=>r.json()).then(d=>{
   if(d.marked){let h=d.horas!=null?' ('+d.horas+'h)':'';res.innerHTML='{{check:lg}}'+d.name+' · '+(d.tipo=='entrada'?'ENTRADA':'SALIDA')+' '+d.time.slice(11,16)+h;res.className='ok';}
   else if(d.spoof){res.innerHTML='{{shield:lg}}'+d.name+': cara real, no foto';res.className='no';}
   else if(d.duplicate){res.innerHTML='{{clock:lg}}'+d.name+' ya marcó '+d.last;res.className='';}
   else{res.innerHTML='{{x:lg}}No reconocido';res.className='no';}
   setTimeout(()=>{res.textContent='Enfoca tu cara…';res.className='';},3500);busy=false;
  }).catch(e=>{res.textContent='Error';res.className='no';busy=false;});},'image/jpeg',0.9);}
</script>"""

INFO=HEAD+TOP+"""<div class=wrap><h1>{{info}}¿Cómo funciona?</h1>
<div class=sub>Todo corre dentro del teléfono. Las fotos nunca salen del equipo.</div>
<div class=card><div style=margin-bottom:4px><span class=chip>Kirin 810</span><span class=chip>ONNX</span><span class=chip>InsightFace</span><span class=chip>512 dim</span><span class=chip>on-device</span></div></div>
<div class=card>
<div class=step><div class=stepic>{{user}}</div><div><b>1 · Detección (SCRFD)</b><br><small>Encuentra el rostro y sus 5 puntos clave (ojos, nariz, comisuras).</small></div></div>
<div class=step><div class=stepic>{{scan}}</div><div><b>2 · Alineación</b><br><small>Encuadra la cara a 112×112 estándar. Precisión de 0.45 → 0.72.</small></div></div>
<div class=step><div class=stepic>{{cpu}}</div><div><b>3 · Embedding (ArcFace)</b><br><small>Convierte la cara en 512 números, su huella única. ~40 ms.</small></div></div>
<div class=step><div class=stepic>{{chart}}</div><div><b>4 · Comparación</b><br><small>Compara con las personas enroladas (coseno). Si supera el umbral, marca.</small></div></div>
<div class=step><div class=stepic>{{shield}}</div><div><b>5 · Anti-foto (liveness)</b><br><small>Verifica que sea un rostro real, no una foto o pantalla.</small></div></div></div></div>"""

ADMIN=HEAD+TOP+"""<div class=wrap><h1>{{sliders}}Panel de administración</h1><div class=sub id=asub>Gestión de personas, configuración y reportes.</div>
<div class=kpis><div class=kpi><div class=n id=kp>–</div><div class=l>{{users}}Personas</div></div>
<div class=kpi><div class=n id=km>–</div><div class=l>{{clock}}Marcas hoy</div></div>
<div class=kpi><div class=n id=kh>–</div><div class=l>{{chart}}Presentes</div></div></div>
<div class=card><h2>{{user-plus}}Enrolar persona</h2><input id=nm placeholder="Nombre" style=margin-bottom:10px>
 <div class=row><button onclick=cam() style=flex:1>{{camera}}Cámara</button><label class="btn sec" style="flex:1;cursor:pointer">{{image}}Subir foto<input id=fl type=file accept=image/* hidden onchange=enrollFile()></label></div>
 <div id=cambox style=display:none;margin-top:12px><div class=stage><video id=cv autoplay playsinline muted></video></div><button style=margin-top:10px;width:100% onclick=snap()>{{camera}}Capturar y enrolar</button></div>
 <p style=margin-top:10px><span id=em></span></p><canvas id=cc style=display:none></canvas></div>
<div class=card><h2>{{users}}Personas (<span id=pc>0</span>)</h2><div id=pl></div></div>
<div class=card><h2>{{sliders}}Configuración</h2>
 <label><small>Nombre del negocio (aparece en el kiosko)</small><input id=bz placeholder="(vacío)"></label>
 <label style=margin-top:12px><small>Umbral de reconocimiento · <b id=tv>0.35</b></small><input id=th type=range min=0.25 max=0.6 step=0.01 oninput="tv.textContent=th.value"></label>
 <label style=margin-top:12px><small>Anti-duplicado · no re-marcar antes de <b id=dv>5</b> min</small><input id=dw type=range min=0 max=30 step=1 oninput="dv.textContent=dw.value"></label>
 <div class=row style="margin-top:14px;gap:9px"><input id=lv type=checkbox> <small style="display:flex;align-items:center;gap:6px;color:var(--txt)">{{shield}}Anti-foto (liveness) activado</small></div>
 <label style=margin-top:12px><small>Exigencia anti-foto · <b id=ltv>0.5</b></small><input id=lt type=range min=0.3 max=0.8 step=0.05 oninput="ltv.textContent=lt.value"></label>
 <button onclick=savecfg() style=margin-top:14px>{{save}}Guardar</button> <span id=cm></span></div>
<div class=card><h2 style=justify-content:space-between><span style=display:flex;align-items:center;gap:7px>{{chart}}Reporte del día</span><a class="btn sec" href="/export.csv" style=padding:8px12px;font-size:13px>{{download}}CSV</a></h2><table id=rp></table></div>
<div class=card><h2>{{clock}}Marcas recientes</h2><table id=lg></table></div></div>
<script>
let PEOPLE=[],ROWS=[];
function F(k,v){let d=new FormData();for(let x in v)d.append(x,v[x]);return fetch(k,{method:'POST',body:d}).then(r=>r.json());}
function delPerson(i){let n=PEOPLE[i].name;if(confirm('¿Eliminar a '+n+'?'))F('/delete_person',{name:n}).then(load);}
function renPerson(i){let n=PEOPLE[i].name,x=prompt('Nuevo nombre',n);if(x&&x!=n)F('/rename_person',{old:n,new:x}).then(load);}
function delMark(i){if(confirm('¿Borrar esta marca?'))F('/delete_mark',{ts:ROWS[i][0]}).then(load);}
function post(blob){let n=nm.value;if(!n){em.textContent='falta el nombre';return;}let d=new FormData();d.append('name',n);d.append('file',blob,'e.jpg');em.textContent='…';
 fetch('/enroll',{method:'POST',body:d}).then(r=>r.json()).then(x=>{em.textContent=x.message||x.error;nm.value='';load();});}
function enrollFile(){if(fl.files[0])post(fl.files[0]);}
function cam(){cambox.style.display='block';navigator.mediaDevices.getUserMedia({video:{facingMode:'user'}}).then(s=>cv.srcObject=s).catch(e=>em.textContent='sin cámara: '+e);}
function snap(){cc.width=cv.videoWidth;cc.height=cv.videoHeight;cc.getContext('2d').drawImage(cv,0,0);cc.toBlob(b=>post(b),'image/jpeg',0.9);}
function savecfg(){let d=new FormData();d.append('business',bz.value);d.append('threshold',th.value);d.append('dup_window',dw.value*60);d.append('liveness',lv.checked?'1':'0');d.append('live_threshold',lt.value);
 fetch('/config',{method:'POST',body:d}).then(r=>r.json()).then(x=>{cm.textContent='guardado ✓';});}
function ei(n){return '<svg class=ic viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round>'+n+'</svg>';}
const IE='<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"/>';
const IT='<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>';
function load(){
 fetch('/config').then(r=>r.json()).then(c=>{bz.value=c.business||'';th.value=c.threshold;tv.textContent=c.threshold;dw.value=Math.round(c.dup_window/60);dv.textContent=Math.round(c.dup_window/60);lv.checked=c.liveness;lt.value=c.live_threshold;ltv.textContent=c.live_threshold;});
 fetch('/people').then(r=>r.json()).then(p=>{PEOPLE=p.people;pc.textContent=p.count;kp.textContent=p.count;
  pl.innerHTML=p.people.map((x,i)=>'<div class=per>'+(x.photo?'<img src=/photo/'+encodeURIComponent(x.name)+'>':'<img>')+'<span style=flex:1>'+x.name+'</span><button class=sec style=padding:9px11px onclick=renPerson('+i+')>'+ei(IE)+'</button> <button class=sec style=padding:9px11px onclick=delPerson('+i+')>'+ei(IT)+'</button></div>').join('')||'<small>vacío</small>';});
 fetch('/report').then(r=>r.json()).then(l=>{km.textContent=l.rows.reduce((a,b)=>a+b.marcas,0);kh.textContent=l.rows.length;
  rp.innerHTML='<tr><th>Persona</th><th>Entrada</th><th>Salida</th><th>Horas</th></tr>'+
  l.rows.map(r=>'<tr><td>'+r.name+'</td><td>'+r.entrada+'</td><td>'+r.salida+'</td><td>'+(r.horas||'—')+'</td></tr>').join('')||'<tr><td colspan=4><small>sin marcas hoy</small></td></tr>';});
 fetch('/log').then(r=>r.json()).then(l=>{ROWS=l.rows;lg.innerHTML='<tr><th>Hora</th><th>Nombre</th><th>Tipo</th><th></th></tr>'+
  l.rows.slice(0,30).map((r,i)=>'<tr><td>'+r[0].slice(5,16)+'</td><td>'+r[1]+'</td><td>'+(r[3]||'—')+'</td><td><button class=sec style="padding:6px8px" onclick=delMark('+i+')>'+ei(IT)+'</button></td></tr>').join('')||'<tr><td colspan=4><small>sin marcas</small></td></tr>';});}
load();
</script>"""

DEMO=HEAD+TOP+"""<div class=wrap><h1>{{cpu}}Demostración técnica</h1><div class=sub>Los datos internos reales que el modelo produce para tu cara.</div>
<div class=stage><video id=v autoplay playsinline muted></video></div>
<button style=margin-top:12px;width:100% onclick=go()>{{cpu}}Analizar mi rostro</button>
<div id=out></div><canvas id=c style=display:none></canvas></div>
<script>
navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:640}}).then(s=>v.srcObject=s);
function go(){let cv=document.getElementById('c');cv.width=v.videoWidth;cv.height=v.videoHeight;cv.getContext('2d').drawImage(v,0,0);
 out.innerHTML='<div class=card>analizando…</div>';
 cv.toBlob(b=>{let f=new FormData();f.append('file',b,'a.jpg');
  fetch('/analyze',{method:'POST',body:f}).then(r=>r.json()).then(d=>{
   if(!d.faces){out.innerHTML='<div class=card>No se detectó rostro</div>';return;}
   let bars=d.matches.map(m=>'<div style=margin:6px0><div class=row style=justify-content:space-between><span>'+m.name+'</span><b>'+m.sim.toFixed(3)+'</b></div><div class=bar><i style="background:'+(m.sim>=d.threshold?'#34d399':'#6366f1')+';width:'+Math.max(2,m.sim*100)+'%"></i></div></div>').join('')||'<small>nadie enrolado</small>';
   out.innerHTML='<div class=card><h2>{{user}}Detección (SCRFD)</h2>Rostros: <b>'+d.faces+'</b> · confianza <b>'+(d.det_score*100).toFixed(0)+'%</b></div>'
    +'<div class=card><h2>{{cpu}}Embedding (ArcFace)</h2><b>'+d.dims+' dimensiones</b> · norma '+d.norm+' · rango ['+d.vmin+', '+d.vmax+']<br><small style=word-break:break-all>primeros 16: '+d.embedding.join(', ')+' …</small></div>'
    +'<div class=card><h2>{{chart}}Similitud coseno</h2>'+bars+'<div style=margin-top:8px;color:var(--mut);font-size:13px>umbral '+d.threshold+'</div></div>'
    +(d.live!=null?'<div class=card><h2>{{shield}}Liveness (anti-foto)</h2><b style=font-size:20px class='+(d.live>=0.5?'ok':'no')+'>'+(d.live*100).toFixed(0)+'% real</b> &nbsp;<small>'+(d.live>=0.5?'rostro vivo':'posible foto/pantalla')+'</small></div>':'')
    +'<div class=card><h2>{{check}}Decisión</h2><b style=font-size:24px class='+(d.decision!='desconocido'?'ok':'no')+'>'+d.decision+'</b></div>';
  });},'image/jpeg',0.9);}
</script>"""

# ---------- PoC onnxruntime-web (validar APK standalone) ----------
_MODELS={"det":os.path.expanduser("~/face_models_s/detection.onnx"),
         "rec":os.path.expanduser("~/face_models_s/recognition.onnx"),
         "spoof":os.path.expanduser("~/spoof_models/as.onnx")}
@app.get("/model/<m>")
def serve_model(m): return send_file(_MODELS[m]) if m in _MODELS else ("",404)
_poc={}
@app.post("/poc")
def poc_set():
    global _poc; _poc=request.get_json(force=True,silent=True) or {}; return jsonify(ok=True)
@app.get("/poc")
def poc_get(): return jsonify(_poc)
WEBTEST="""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font-family:monospace;background:#0a0e17;color:#e7ecf5;padding:18px">
<h3>PoC onnxruntime-web (motor dentro del navegador)</h3><pre id=st>cargando ort-web del CDN...</pre>
<script src="https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/ort.min.js"></script>
<script>
ort.env.wasm.wasmPaths='https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/';
function log(o){st.textContent=JSON.stringify(o,null,2);fetch('/poc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});}
(async()=>{try{
 if(typeof ort==='undefined'){log({ok:false,err:'no cargo ort-web (sin internet?)'});return;}
 let t0=performance.now();
 let det=await ort.InferenceSession.create('/model/det',{executionProviders:['wasm']});
 let ld=performance.now()-t0;
 let d=new Float32Array(3*640*640);
 let feeds={};feeds[det.inputNames[0]]=new ort.Tensor('float32',d,[1,3,640,640]);
 let t1=performance.now();let o=await det.run(feeds);let inf=performance.now()-t1;
 let rec=await ort.InferenceSession.create('/model/rec',{executionProviders:['wasm']});
 let rd=new Float32Array(3*112*112);let rf={};rf[rec.inputNames[0]]=new ort.Tensor('float32',rd,[1,3,112,112]);
 let t2=performance.now();await rec.run(rf);let rinf=performance.now()-t2;
 log({ok:true,ort:ort.version,carga_det_ms:Math.round(ld),inferencia_det_ms:Math.round(inf),salidas_det:Object.keys(o).length,inferencia_rec_ms:Math.round(rinf)});
}catch(e){log({ok:false,err:''+e});}})();
</script>"""
@app.get("/webtest")
def webtest(): return Response(WEBTEST,mimetype="text/html")

@app.get("/webapp/<path:p>")     # webapp standalone (motor JS) - futura APK
def webapp(p):
    fp=os.path.join(os.path.expanduser("~/webapp"), p)
    return send_file(fp) if os.path.exists(fp) and ".." not in p else ("",404)

@app.get("/")
def home():  return Response(render(PORTADA),mimetype="text/html")
@app.get("/kiosk")
def kiosk(): return Response(render(KIOSK),mimetype="text/html")
@app.get("/admin")
def admin(): return Response(render(ADMIN),mimetype="text/html")
@app.get("/info")
def info():  return Response(render(INFO),mimetype="text/html")
@app.get("/demo")
def demo():  return Response(render(DEMO),mimetype="text/html")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8090,threaded=True)
