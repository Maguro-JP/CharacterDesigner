import sys, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
S=4; N=1024; W=N*S
def cr(pts, n=24, closed=True):
    P=pts+pts[:3] if closed else [pts[0]]+pts+[pts[-1]]
    out=[]
    for i in range(len(P)-3):
        p0,p1,p2,p3=P[i:i+4]
        for k in range(n):
            t=k/n; t2=t*t; t3=t2*t
            out.append(tuple(S*0.5*((2*p1[j])+(-p0[j]+p2[j])*t+(2*p0[j]-5*p1[j]+4*p2[j]-p3[j])*t2+(-p0[j]+3*p1[j]-3*p2[j]+p3[j])*t3) for j in (0,1)))
    return out
def grad(c1,c2):
    g=Image.new("RGB",(W,W)); d=ImageDraw.Draw(g)
    for y in range(W):
        t=y/W; d.line([(0,y),(W,y)],fill=tuple(int(c1[i]+(c2[i]-c1[i])*t) for i in range(3)))
    return g
def hexc(h): return tuple(int(h[i:i+2],16) for i in (1,3,5))
# face+neck silhouette, facing left
FACE=[(430,200),(330,240),(270,320),(258,400),(252,440),(226,490),(236,506),(260,512),(256,532),(248,544),(262,556),(256,574),(270,596),(300,625),(350,640),(380,650),(395,700),(392,780),(330,860),(220,940),(200,1030),(720,1030),(700,900),(560,820),(540,720),(560,600),(600,420),(580,280),(520,215)]
HAIR=[(440,150),(330,180),(250,260),(232,340),(262,330),(290,300),(305,345),(345,305),(395,330),(450,300),(500,380),(520,480),(530,600),(560,720),(620,820),(700,880),(660,780),(700,790),(670,680),(720,700),(680,560),(710,440),(680,290),(600,180),(520,150)]
def icon(name,bg1,bg2,fig,hair,pen,acc,txt):
    img=grad(hexc(bg1),hexc(bg2)); d=ImageDraw.Draw(img)
    d.polygon(cr(FACE),fill=hexc(fig))
    d.polygon(cr(HAIR),fill=hexc(hair))
    # strand highlight
    d.line(cr([(480,190),(580,290),(620,440),(640,600),(690,760)],closed=False),fill=hexc(acc),width=7*S)
    # eye lash
    d.line(cr([(282,418),(302,428),(322,424)],closed=False),fill=hexc(hair),width=7*S)
    # stylus: slash, right side
    L=Image.new("RGBA",(W,W),(0,0,0,0)); ld=ImageDraw.Draw(L)
    cx,cy,ln,wd=830*S,430*S,540*S,44*S
    ld.rounded_rectangle([cx-wd/2,cy-ln/2,cx+wd/2,cy+ln/2],radius=wd/2,fill=hexc(pen))
    ld.rectangle([cx-wd/2,cy+ln/2-150*S,cx+wd/2,cy+ln/2-128*S],fill=hexc(acc))
    ld.polygon([(cx-wd/2,cy+ln/2-30*S),(cx+wd/2,cy+ln/2-30*S),(cx,cy+ln/2+60*S)],fill=hexc(pen))
    L=L.rotate(-32,center=(cx,cy),resample=Image.BICUBIC)
    img.paste(L,(0,0),L)
    f=ImageFont.truetype("/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf",150*S)
    d=ImageDraw.Draw(img); d.text((925*S,925*S),"CD",font=f,fill=hexc(txt),anchor="rb")
    m=Image.new("L",(W,W),0); ImageDraw.Draw(m).rounded_rectangle([0,0,W-1,W-1],radius=int(W*0.225),fill=255)
    out=Image.new("RGBA",(W,W)); out.paste(img,(0,0),m)
    out.resize((N,N),Image.LANCZOS).save(name)
V=[("icon-white-red.png","#ffffff","#f3ece6","#e03a2f","#1c1c1c","#1c1c1c","#ff8a1f","#e03a2f"),
   ("icon-black-orange.png","#1a1a1a","#000000","#ff8a1f","#f5f5f5","#f5f5f5","#e03a2f","#ff8a1f"),
   ("icon-navy-teal.png","#16223f","#0a1226","#2ec4b6","#e8f1f2","#e8f1f2","#ff8a1f","#2ec4b6"),
   ("icon-red-white.png","#e8402f","#b5241a","#ffffff","#141414","#141414","#ffb347","#ffffff")]
for v in V: icon(*v)
