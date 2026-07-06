// Motor facial standalone con onnxruntime-web (corre 100% en el navegador).
// Portado de face_core.py a JS: detección SCRFD + alineación + embedding ArcFace.
const TEMPLATE=[[38.2946,51.6963],[73.5318,51.5014],[56.0252,71.7366],[41.5493,92.3655],[70.7299,92.2041]];

const ENGINE = {
  det:null, rec:null, spoof:null, _c:null, _a:null,

  async loadDet(u='/model/det'){ this.det=await ort.InferenceSession.create(u,{executionProviders:['wasm']}); },
  async loadRec(u='/model/rec'){ this.rec=await ort.InferenceSession.create(u,{executionProviders:['wasm']}); },
  async loadSpoof(u='/model/spoof'){ this.spoof=await ort.InferenceSession.create(u,{executionProviders:['wasm']}); },

  // prob 0-1 de rostro REAL (no foto/pantalla). null si no hay modelo.
  async antiSpoof(src, box, inc=1.5){
    if(!this.spoof) return null;
    const D=this._dims(src), W=D[0], H=D[1];
    const cx=(box.x1+box.x2)/2, cy=(box.y1+box.y2)/2, l=Math.max(box.x2-box.x1, box.y2-box.y1)*inc;
    const X1=cx-l/2, Y1=cy-l/2;
    const cnv=this._sp||(this._sp=document.createElement('canvas')); cnv.width=128; cnv.height=128;
    const ctx=cnv.getContext('2d'); ctx.setTransform(1,0,0,1,0,0);
    ctx.fillStyle='#000'; ctx.fillRect(0,0,128,128);
    // recorte con relleno negro donde se sale del cuadro (igual que Python)
    const sx1=Math.max(0,X1), sy1=Math.max(0,Y1), sx2=Math.min(W,X1+l), sy2=Math.min(H,Y1+l), sc=128/l;
    if(sx2>sx1 && sy2>sy1){ try{ ctx.drawImage(src, sx1,sy1,sx2-sx1,sy2-sy1, (sx1-X1)*sc,(sy1-Y1)*sc,(sx2-sx1)*sc,(sy2-sy1)*sc); }catch(e){} }
    const img=ctx.getImageData(0,0,128,128).data, n=128*128, data=new Float32Array(3*n);
    for(let i=0;i<n;i++){ data[i]=img[i*4+2]/255; data[n+i]=img[i*4+1]/255; data[2*n+i]=img[i*4]/255; } // BGR
    const feeds={}; feeds[this.spoof.inputNames[0]]=new ort.Tensor('float32',data,[1,3,128,128]);
    const o=(await this.spoof.run(feeds))[this.spoof.outputNames[0]].data;
    const m=Math.max(o[0],o[1]), e0=Math.exp(o[0]-m), e1=Math.exp(o[1]-m);
    return e1/(e0+e1);
  },

  _dims(s){ return [s.videoWidth||s.naturalWidth||s.width, s.videoHeight||s.naturalHeight||s.height]; },

  _prepDet(src, size=640){
    const [vw,vh]=this._dims(src);
    const scale=Math.min(size/vh, size/vw);
    const nw=Math.round(vw*scale), nh=Math.round(vh*scale);
    const cnv=this._c||(this._c=document.createElement('canvas')); cnv.width=size; cnv.height=size;
    const ctx=cnv.getContext('2d'); ctx.setTransform(1,0,0,1,0,0);
    ctx.fillStyle='#000'; ctx.fillRect(0,0,size,size); ctx.drawImage(src,0,0,nw,nh);
    const img=ctx.getImageData(0,0,size,size).data, n=size*size, data=new Float32Array(3*n);
    for(let i=0;i<n;i++){ data[i]=(img[i*4]-127.5)/128; data[n+i]=(img[i*4+1]-127.5)/128; data[2*n+i]=(img[i*4+2]-127.5)/128; }
    return {tensor:new ort.Tensor('float32',data,[1,3,size,size]), scale};
  },

  _nms(b, thr=0.4){
    b.sort((a,c)=>c.s-a.s); const keep=[];
    while(b.length){ const x=b.shift(); keep.push(x);
      b=b.filter(o=>{ const xx1=Math.max(x.x1,o.x1),yy1=Math.max(x.y1,o.y1),xx2=Math.min(x.x2,o.x2),yy2=Math.min(x.y2,o.y2);
        const w=Math.max(0,xx2-xx1),h=Math.max(0,yy2-yy1),it=w*h;
        return it/((x.x2-x.x1)*(x.y2-x.y1)+(o.x2-o.x1)*(o.y2-o.y1)-it+1e-6)<=thr; }); }
    return keep;
  },

  async detect(src, thresh=0.5, size=640){
    const {tensor,scale}=this._prepDet(src,size);
    const feeds={}; feeds[this.det.inputNames[0]]=tensor;
    const out=await this.det.run(feeds), on=this.det.outputNames, strides=[8,16,32]; let boxes=[];
    for(let idx=0; idx<3; idx++){
      const st=strides[idx], sc=out[on[idx]].data, bb=out[on[idx+3]].data, kp=out[on[idx+6]].data, w=size/st, N=sc.length;
      for(let i=0;i<N;i++){ if(sc[i]<thresh) continue;
        const cell=Math.floor(i/2), ax=(cell%w)*st, ay=Math.floor(cell/w)*st;
        const pts=[]; for(let j=0;j<5;j++) pts.push([ax+kp[i*10+2*j]*st, ay+kp[i*10+2*j+1]*st]);
        boxes.push({x1:ax-bb[i*4]*st, y1:ay-bb[i*4+1]*st, x2:ax+bb[i*4+2]*st, y2:ay+bb[i*4+3]*st, s:sc[i], pts}); }
    }
    boxes=this._nms(boxes,0.4);
    for(const b of boxes){ b.x1/=scale;b.y1/=scale;b.x2/=scale;b.y2/=scale; b.pts=b.pts.map(p=>[p[0]/scale,p[1]/scale]); }
    return boxes;
  },

  biggest(boxes){ return boxes.length? boxes.reduce((a,b)=>((b.x2-b.x1)*(b.y2-b.y1)>(a.x2-a.x1)*(a.y2-a.y1)?b:a)) : null; },

  // transform de similitud src->dst por mínimos cuadrados (rotación+escala+traslación)
  _estSim(src,dst){
    const n=src.length; let mx=0,my=0,mu=0,mv=0;
    for(let i=0;i<n;i++){mx+=src[i][0];my+=src[i][1];mu+=dst[i][0];mv+=dst[i][1];}
    mx/=n;my/=n;mu/=n;mv/=n;
    let sa=0,sb=0,sd=0;
    for(let i=0;i<n;i++){ const x=src[i][0]-mx,y=src[i][1]-my,u=dst[i][0]-mu,v=dst[i][1]-mv;
      sa+=x*u+y*v; sb+=x*v-y*u; sd+=x*x+y*y; }
    const a=sa/sd, b=sb/sd;
    return {a,b,tx:mu-(a*mx-b*my), ty:mv-(b*mx+a*my)};   // u=a*x-b*y+tx ; v=b*x+a*y+ty
  },

  // recorta+alinea la cara a 112x112 RGBA usando los 5 puntos
  _align(src, kps){
    const {a,b,tx,ty}=this._estSim(TEMPLATE, kps);       // template->imagen
    const s=a*a+b*b, ai=a/s, bi=b/s, ci=-b/s, di=a/s;     // inversa (imagen->template)
    const ei=-(ai*tx+bi*ty), fi=-(ci*tx+di*ty);
    const cnv=this._a||(this._a=document.createElement('canvas')); cnv.width=112; cnv.height=112;
    const ctx=cnv.getContext('2d'); ctx.setTransform(ai,ci,bi,di,ei,fi); ctx.drawImage(src,0,0);
    ctx.setTransform(1,0,0,1,0,0);
    return ctx.getImageData(0,0,112,112).data;
  },

  async embed(src, box){
    const img=this._align(src, box.pts), n=112*112, data=new Float32Array(3*n);
    for(let i=0;i<n;i++){ data[i]=(img[i*4]-127.5)/127.5; data[n+i]=(img[i*4+1]-127.5)/127.5; data[2*n+i]=(img[i*4+2]-127.5)/127.5; }
    const feeds={}; feeds[this.rec.inputNames[0]]=new ort.Tensor('float32',data,[1,3,112,112]);
    const out=await this.rec.run(feeds); const e=out[this.rec.outputNames[0]].data;
    let nrm=0; for(let i=0;i<e.length;i++) nrm+=e[i]*e[i]; nrm=Math.sqrt(nrm);
    const v=new Float32Array(e.length); for(let i=0;i<e.length;i++) v[i]=e[i]/nrm;
    return v;
  },

  cosine(a,b){ let d=0; for(let i=0;i<a.length;i++) d+=a[i]*b[i]; return d; },

  // pipeline completo sobre una imagen/video: devuelve {box, emb} o null
  async embedFace(src, thresh=0.5){
    const box=this.biggest(await this.detect(src,thresh)); if(!box) return null;
    return {box, emb: await this.embed(src, box)};
  }
};
