#!/data/data/com.termux/files/usr/bin/python
# Nucleo de reconocimiento facial: detectar -> ALINEAR (5 puntos) -> embedding -> DB.
# La alineacion por landmarks mejora la precision del embedding ArcFace.
import os, sys, subprocess, numpy as np
from PIL import Image
import onnxruntime as ort

MDL = os.environ.get("FACE_MDL", os.path.expanduser("~/face_models_s"))
DB  = os.path.expanduser("~/face_db.npz")
THRESHOLD = 0.35

# Plantilla estandar de ArcFace (5 puntos para cara 112x112)
TEMPLATE = np.array([[38.2946,51.6963],[73.5318,51.5014],[56.0252,71.7366],
                     [41.5493,92.3655],[70.7299,92.2041]], dtype=np.float32)

_det = ort.InferenceSession(MDL+"/detection.onnx",   providers=["CPUExecutionProvider"])
_rec = ort.InferenceSession(MDL+"/recognition.onnx", providers=["CPUExecutionProvider"])
_din, _rin = _det.get_inputs()[0].name, _rec.get_inputs()[0].name
_douts = [o.name for o in _det.get_outputs()]

SPOOF = os.path.expanduser("~/spoof_models/as.onnx")   # anti-spoofing (liveness)
_spoof = ort.InferenceSession(SPOOF, providers=["CPUExecutionProvider"]) if os.path.exists(SPOOF) else None

def anti_spoof(img, box, inc=1.5):
    """Devuelve prob 0-1 de que sea un rostro REAL (no foto/pantalla). None si no hay modelo."""
    if _spoof is None: return None
    x1,y1,x2,y2 = box[:4]; l=max(x2-x1, y2-y1)*inc; xc,yc=(x1+x2)/2,(y1+y2)/2
    X1,Y1,X2,Y2 = int(xc-l/2),int(yc-l/2),int(xc+l/2),int(yc+l/2)
    H,W = img.shape[:2]; canvas=np.zeros((Y2-Y1,X2-X1,3),np.uint8)
    sx1,sy1,sx2,sy2 = max(0,X1),max(0,Y1),min(W,X2),min(H,Y2)
    canvas[sy1-Y1:sy2-Y1, sx1-X1:sx2-X1] = img[sy1:sy2, sx1:sx2]
    face = np.asarray(Image.fromarray(canvas).resize((128,128)))[:,:,::-1]   # RGB->BGR
    blob = (face.transpose(2,0,1).astype(np.float32)/255.0)[None].copy()
    out = _spoof.run(None,{"input":blob})[0][0]
    ex = np.exp(out-out.max()); p=ex/ex.sum()
    return float(p[1])

def _prep(img, size=640):
    h,w = img.shape[:2]; s = min(size/h, size/w)
    nh,nw = int(round(h*s)), int(round(w*s))
    r = np.array(Image.fromarray(img).resize((nw,nh)))
    c = np.zeros((size,size,3), np.uint8); c[:nh,:nw] = r
    return ((c.astype(np.float32)-127.5)/128.0).transpose(2,0,1)[None], s

def _nms(d, thr=0.4):
    x1,y1,x2,y2,sc=d[:,0],d[:,1],d[:,2],d[:,3],d[:,4]
    a=(x2-x1+1)*(y2-y1+1); o=sc.argsort()[::-1]; k=[]
    while o.size>0:
        i=o[0]; k.append(i)
        xx1=np.maximum(x1[i],x1[o[1:]]); yy1=np.maximum(y1[i],y1[o[1:]])
        xx2=np.minimum(x2[i],x2[o[1:]]); yy2=np.minimum(y2[i],y2[o[1:]])
        w=np.maximum(0,xx2-xx1+1); h=np.maximum(0,yy2-yy1+1); inter=w*h
        ovr=inter/(a[i]+a[o[1:]]-inter); o=o[1:][ovr<=thr]
    return k

def _umeyama(src, dst):
    # transform de similitud src->dst (skimage), devuelve matriz 3x3
    num,dim = src.shape
    sm,dm = src.mean(0), dst.mean(0)
    sd,dd = src-sm, dst-dm
    A = dd.T @ sd / num
    d = np.ones(dim);
    if np.linalg.det(A) < 0: d[dim-1] = -1
    T = np.eye(dim+1)
    U,S,V = np.linalg.svd(A)
    if np.linalg.matrix_rank(A) == dim-1:
        if np.linalg.det(U)*np.linalg.det(V) > 0: T[:dim,:dim] = U@V
        else:
            s=d[dim-1]; d[dim-1]=-1; T[:dim,:dim]=U@np.diag(d)@V; d[dim-1]=s
    else:
        T[:dim,:dim] = U@np.diag(d)@V
    scale = 1.0/sd.var(0).sum() * (S@d)
    T[:dim,dim] = dm - scale*(T[:dim,:dim]@sm)
    T[:dim,:dim] *= scale
    return T

def detect(img, thresh=0.5, size=640):
    blob,s = _prep(img,size); out=_det.run(_douts,{_din:blob}); B=[]
    for idx,st in enumerate([8,16,32]):
        sc=out[idx][:,0]; bp=out[idx+3]*st; kp=out[idx+6]*st; hw=size//st
        ax,ay=np.meshgrid(np.arange(hw),np.arange(hw))
        ac=np.stack([ax,ay],-1).astype(np.float32).reshape(-1,2)*st; ac=np.repeat(ac,2,0)
        x1=ac[:,0]-bp[:,0]; y1=ac[:,1]-bp[:,1]; x2=ac[:,0]+bp[:,2]; y2=ac[:,1]+bp[:,3]
        kxs = ac[:,0:1] + kp[:,0::2]; kys = ac[:,1:2] + kp[:,1::2]      # (N,5)
        krow = np.stack([kxs,kys],-1).reshape(len(sc),10)              # x0,y0,...
        b = np.concatenate([np.stack([x1,y1,x2,y2,sc],-1), krow], 1)   # (N,15)
        B.append(b[sc>=thresh])
    d=np.concatenate(B,0)
    if len(d)==0: return None
    d=d[_nms(d[:,:5])]; d[:,:4]/=s; d[:,5:]/=s
    return d

def embed_face(img, row):
    kps = row[5:].reshape(5,2).astype(np.float32)
    M = _umeyama(TEMPLATE, kps)                       # plantilla -> coords imagen
    coeffs = (M[0,0],M[0,1],M[0,2], M[1,0],M[1,1],M[1,2])
    face = Image.fromarray(img).transform((112,112), Image.AFFINE, coeffs, resample=Image.BILINEAR)
    blob = ((np.asarray(face).astype(np.float32)-127.5)/127.5).transpose(2,0,1)[None]
    e = _rec.run(None,{_rin:blob})[0][0]
    return e/np.linalg.norm(e)

def get_embedding(path):
    img=np.array(Image.open(path).convert("RGB")); d=detect(img)
    if d is None: return None
    return embed_face(img, d[((d[:,2]-d[:,0])*(d[:,3]-d[:,1])).argmax()])

def _load():
    if not os.path.exists(DB): return [], np.zeros((0,512),np.float32)
    z=np.load(DB, allow_pickle=True); return list(z["names"]), z["vecs"]
def _save(names, vecs): np.savez(DB, names=np.array(names,object), vecs=vecs)

def enroll(name, path):
    e=get_embedding(path)
    if e is None: return False, "no se detecto cara"
    names,vecs=_load(); names.append(name); vecs=np.vstack([vecs,e[None]]); _save(names,vecs)
    return True, f"enrolado '{name}' (base: {len(names)} caras)"

def identify(path, threshold=THRESHOLD):
    e=get_embedding(path)
    if e is None: return None, 0.0
    names,vecs=_load()
    if len(names)==0: return None, 0.0
    sims=vecs@e; i=int(sims.argmax())
    return (names[i], float(sims[i])) if sims[i]>=threshold else ("desconocido", float(sims[i]))

def identify_live(path, threshold=THRESHOLD):
    img=np.array(Image.open(path).convert("RGB")); d=detect(img)
    if d is None: return {"name":None,"sim":0.0,"live":None}
    row=d[((d[:,2]-d[:,0])*(d[:,3]-d[:,1])).argmax()]
    live=anti_spoof(img,row); e=embed_face(img,row); names,vecs=_load()
    name,sim=(None,0.0)
    if names:
        sims=vecs@e; i=int(sims.argmax()); name,sim=names[i],float(sims[i])
    return {"name":name if sim>=threshold else "desconocido","sim":sim,"live":live}

def delete_person(name):
    names,vecs=_load()
    keep=[i for i,n in enumerate(names) if n!=name]
    _save([names[i] for i in keep], vecs[keep] if keep else np.zeros((0,512),np.float32))
    return len(names)-len(keep)

def rename_person(old,new):
    names,vecs=_load()
    if old not in names: return False
    _save([new if n==old else n for n in names], vecs); return True

def analyze(path):   # todos los datos internos del modelo (para demostrar)
    img=np.array(Image.open(path).convert("RGB")); d=detect(img)
    if d is None: return {"faces":0}
    row=d[((d[:,2]-d[:,0])*(d[:,3]-d[:,1])).argmax()]
    e=embed_face(img,row); names,vecs=_load()
    ranked=sorted([(n,float(v@e)) for n,v in zip(names,vecs)],key=lambda x:-x[1]) if len(names) else []
    best = ranked[0] if ranked else (None,0.0)
    live = anti_spoof(img,row)
    return {"faces":int(len(d)),"det_score":round(float(row[4]),3),
        "embedding":[round(float(x),4) for x in e[:16]], "dims":int(len(e)),
        "norm":round(float(np.linalg.norm(e)),3),"vmin":round(float(e.min()),3),"vmax":round(float(e.max()),3),
        "threshold":THRESHOLD,"decision":best[0] if best[1]>=THRESHOLD else "desconocido",
        "live":round(live,3) if live is not None else None,
        "matches":[{"name":n,"sim":round(s,3)} for n,s in ranked[:6]]}

if __name__=="__main__":
    if len(sys.argv)>=3 and sys.argv[1]=="enroll":  print(enroll(sys.argv[2], sys.argv[3])[1])
    elif len(sys.argv)>=3 and sys.argv[1]=="identify":
        n,s=identify(sys.argv[2]); print(f"-> {n}  (similitud {s:.2f})")
    else:
        T=os.path.expanduser("~/face_test")
        if os.path.exists(DB): os.remove(DB)
        enroll("Joe Biden", T+"/biden.jpg"); enroll("Barack Obama", T+"/obama1.jpg")
        n,s=identify(T+"/obama2.jpg")
        print(f"Identifico Obama (con ALINEACION) -> {n}  (similitud {s:.3f})")
        print("(antes sin alinear era 0.446; deberia subir)")
