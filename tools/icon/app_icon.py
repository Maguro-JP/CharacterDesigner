import math, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
S=3; N=1024; W=N*S
# pen profile along length t (0=back end, 1=nib tip): (radius px, material)
L=1000
def prof(t):
    y=t*L
    if y<12:  return 15*math.sqrt(max(0,1-((12-y)/12)**2))+0.5,'cap'
    if y<40:  return 15.5+(y-12)*0.02,'cap'
    if y<44:  return 16.5,'chrome'
    if y<600: return 16.5+(y-44)/556*13.5,'body'
    if y<604: return 30.3,'chrome'
    if y<860: return 30.5+1.5*math.sin((y-604)/256*math.pi),'grip'
    if y<935: return 30-(y-860)/75*18,'cone'
    if y<939: return 12-(y-935),'cone'
    if y<947: return 4.2,'nib'
    if y<951.2: return 4.2*math.sqrt(max(0,1-((y-947)/4.2)**2))+0.3,'nib'
    return 0,None
MAT={'cap':((38,38,42),0.5,40),'chrome':((180,182,188),1.0,8),'body':((30,31,36),0.45,30),'grip':((22,22,24),0.15,6),
     'cone':((40,40,44),0.6,25),'nibsleeve':((150,152,158),0.9,10),'nib':((62,62,64),0.2,3)}
def render():
    w=80; img=np.zeros((L,w,4),np.float32); c=w/2
    lx,ly,lz=-0.55,-0.25,0.8; ln=math.sqrt(lx*lx+ly*ly+lz*lz); lx,ly,lz=lx/ln,ly/ln,lz/ln
    for y in range(L):
        r,m=prof(y/L)
        if not m or r<=0: continue
        base,spec,shin=MAT[m]
        for x in range(w):
            u=(x+0.5-c)/r
            if abs(u)>1: continue
            a=min(1,(r-abs(x+0.5-c))+0.5)
            nx=u; nz=math.sqrt(1-u*u)
            d=max(0,nx*lx+nz*lz)
            hx,hz=lx,lz+1; hn=math.hypot(hx,hz); s=max(0,(nx*hx+nz*hz)/hn)**shin*spec
            rim=max(0,u)**6*0.35
            col=[base[i]*(0.25+0.95*d)+255*(s*0.9+rim*0.5) for i in range(3)]
            if m=='grip' and (y//6)%2==0: col=[v*0.8 for v in col]
            img[y,x]=[*col,255*a]
    # side rocker switch on body
    im=Image.fromarray(np.clip(img,0,255).astype(np.uint8),'RGBA')
    d=ImageDraw.Draw(im)
    d.rounded_rectangle([c-33,640,c-19,760],radius=7,fill=(26,26,30,255),outline=(95,95,100,255))
    d.line([c-31,700,c-21,700],fill=(8,8,8,255),width=3)
    d.line([c-29,648,c-29,692],fill=(130,130,138,200),width=2)
    d.line([c-29,708,c-29,752],fill=(130,130,138,200),width=2)
    # thin red accent ring (not a brand mark)
    d.rectangle([c-30,598,c+30,602],fill=(224,58,47,255))
    return im
def overlay(txt1,txt2):
    pen=render()
    # place: back end near top-right corner, tip beside the C
    x0,y0=980,30; x1,y1=600,860
    ang=math.degrees(math.atan2(x1-x0,y1-y0))  # rotation from vertical
    length=math.hypot(x1-x0,y1-y0)
    k=length/L*S
    p=pen.resize((int(pen.width*k),int(L*k)),Image.LANCZOS)
    pr=p.rotate(ang,expand=True,resample=Image.BICUBIC)
    lay=Image.new("RGBA",(W,W),(0,0,0,0))
    cx,cy=(x0+x1)/2*S,(y0+y1)/2*S
    pos=(int(cx-pr.width/2),int(cy-pr.height/2))
    sh=Image.new("RGBA",pr.size,(0,0,0,0)); sh.putalpha(pr.getchannel("A").point(lambda a:int(a*0.45)).filter(ImageFilter.GaussianBlur(9*S)))
    lay.alpha_composite(sh,(pos[0]+16*S,pos[1]+22*S)); lay.alpha_composite(pr,pos)
    f=ImageFont.truetype("/usr/share/fonts/opentype/inter/InterDisplay-BlackItalic.otf",230*S)
    m=Image.new("L",(W,W),0); ImageDraw.Draw(m).text((W-62*S,W-52*S),"CD",font=f,fill=255,anchor="rb")
    sd=Image.new("RGBA",(W,W),(0,0,0,0)); sd.putalpha(m.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(10*S)).point(lambda a:int(a*0.6)))
    lay.alpha_composite(sd,(6*S,8*S))
    wh=Image.new("RGBA",(W,W),(255,255,255,0)); wh.putalpha(m.filter(ImageFilter.MaxFilter(25)))
    lay.alpha_composite(wh)
    g=np.zeros((W,W,4),np.uint8); a1=np.array(txt1); a2=np.array(txt2)
    t=np.clip((np.arange(W)/W-0.78)/0.18,0,1)[:,None]
    g[...,:3]=(a1*(1-t[...,None])+a2*t[...,None]).astype(np.uint8); g[...,3]=np.array(m)
    lay.alpha_composite(Image.fromarray(g,'RGBA'))
    return lay.resize((N,N),Image.LANCZOS)
def icon(girl,out,mirror=False):
    g=Image.open(girl).convert("RGB")
    if mirror: g=ImageOps.mirror(g)
    b=g.resize((N,N),Image.LANCZOS).convert("RGBA")
    b.alpha_composite(overlay((255,138,31),(224,58,47)))
    mk=Image.new("L",(N,N),0); ImageDraw.Draw(mk).rounded_rectangle([0,0,N-1,N-1],radius=230,fill=255)
    o=Image.new("RGBA",(N,N)); o.paste(b,(0,0),mk); o.save(out)
icon("girl-s11.png","icon2-a.png")
icon("girl-s12.png","icon2-b.png",mirror=True)
