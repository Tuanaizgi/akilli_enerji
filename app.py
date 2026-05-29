"""
AKILLI ENERJİ v3.2 — Railway Deploy Sürümü
"""

import io, os, re, random, datetime, statistics, json, base64
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, render_template, request, jsonify, session
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "akilli_enerji_gizli_2024")

# ── OPSİYONEL: OCR ──────────────────────────────────────────────────────────
OCR_AKTIF = False
try:
    import pytesseract
    from PIL import Image
    import cv2
    pytesseract.get_tesseract_version()
    OCR_AKTIF = True
    print("✓ OCR aktif")
except Exception as e:
    print(f"⚠ OCR devre dışı: {e}")

# ── MOCK VERİ ────────────────────────────────────────────────────────────────
_mock_olcumler = [round(0.4 + i * 0.18 + random.uniform(-0.2, 0.2), 2) for i in range(1, 8)]

def giris_yap(u, s):   return len(u) > 0 and len(s) >= 4
def kayit_ol(u, s):    return True
def olcum_ekle(val):   _mock_olcumler.append(round(val, 2))
def toplam_enerji():   return round(sum(_mock_olcumler), 2)

def gunluk_enerji_grafik_veri():
    random.seed(7)
    return [{"gun": f"{i:02d}", "enerji": round(0.4+i*0.18+random.uniform(-0.2,0.2),2)} for i in range(1,8)]

# ── SABITLER ─────────────────────────────────────────────────────────────────
BIRIM_FIYAT    = 2.28
CO2_KATSAYI    = 0.4
BUTCE_VARSAYIM = 100.0
PIK_SAATLER    = list(range(6,10)) + list(range(17,22))
GUNLUK_HEDEF   = 2.0
SIFRE_MIN, SIFRE_MAX = 4, 8

IL_ORTALAMA = {
    "Adana":18.5,"Adıyaman":13.2,"Afyonkarahisar":14.1,"Ağrı":12.8,"Amasya":13.9,
    "Ankara":16.7,"Antalya":19.2,"Artvin":11.5,"Aydın":17.8,"Balıkesir":15.6,
    "Bilecik":14.2,"Bingöl":12.1,"Bitlis":11.9,"Bolu":13.7,"Burdur":13.4,
    "Bursa":17.3,"Çanakkale":14.8,"Çankırı":12.6,"Çorum":13.5,"Denizli":16.2,
    "Diyarbakır":15.1,"Edirne":14.3,"Elazığ":14.7,"Erzincan":12.3,"Erzurum":13.9,
    "Eskişehir":15.4,"Gaziantep":17.6,"Giresun":12.8,"Gümüşhane":11.7,"Hakkari":10.9,
    "Hatay":17.1,"Isparta":13.6,"Mersin":18.3,"İstanbul":20.1,"İzmir":19.5,
    "Kars":11.2,"Kastamonu":12.4,"Kayseri":15.8,"Kırklareli":14.1,"Kırşehir":13.0,
    "Kocaeli":18.9,"Konya":15.9,"Kütahya":13.8,"Malatya":14.6,"Manisa":16.4,
    "Kahramanmaraş":15.7,"Mardin":14.2,"Muğla":18.7,"Muş":11.8,"Nevşehir":13.3,
    "Niğde":13.1,"Ordu":13.6,"Rize":12.9,"Sakarya":16.1,"Samsun":15.3,
    "Siirt":12.4,"Sinop":12.0,"Sivas":13.7,"Tekirdağ":16.8,"Tokat":13.2,
    "Trabzon":14.5,"Tunceli":10.8,"Şanlıurfa":15.6,"Uşak":14.0,"Van":12.7,
    "Yozgat":12.9,"Zonguldak":14.6,"Aksaray":13.5,"Bayburt":11.1,"Karaman":13.8,
    "Kırıkkale":14.3,"Batman":14.8,"Şırnak":12.1,"Bartın":12.7,"Ardahan":10.5,
    "Iğdır":11.6,"Yalova":15.9,"Karabük":13.4,"Kilis":14.1,"Osmaniye":15.2,"Düzce":13.9
}
ILLER = sorted(IL_ORTALAMA.keys())

_user_state = {}

def get_state():
    try:    uid = session.get("user","default")
    except: uid = "default"
    if uid not in _user_state:
        _user_state[uid] = {"butce":BUTCE_VARSAYIM,"gunluk_hedef":GUNLUK_HEDEF,"secili_il":"İstanbul","tahmin_gecmis":[]}
    return _user_state[uid]

# ── HESAPLAMALAR ─────────────────────────────────────────────────────────────
def sifre_dogrula(s):
    if len(s)<SIFRE_MIN: return False,f"En az {SIFRE_MIN} karakter."
    if len(s)>SIFRE_MAX: return False,f"En fazla {SIFRE_MAX} karakter."
    if not any(c.isalpha() for c in s): return False,"En az 1 harf."
    if not any(c.isdigit() for c in s): return False,"En az 1 rakam."
    return True,""

def verimlilik_skoru(kwh):
    for e,h,r in [(5,"A","#22c55e"),(10,"B","#4ade80"),(20,"C","#a3e635"),(35,"D","#facc15"),(50,"E","#fb923c"),(70,"F","#f87171")]:
        if kwh<=e: return h,r
    return "G","#ef4444"

def ay_sonu_tahmin(kwh):
    bugun=max(datetime.date.today().day,1); t=round((kwh/bugun)*30,2)
    return t,round(t*BIRIM_FIYAT,2)

def co2_hesapla(kwh):
    kg=round(kwh*CO2_KATSAYI,2); return {"co2_kg":kg,"agac_esit":round(kg/21,1)}

def anomali_skoru(veriler):
    if len(veriler)<3: return 0.0
    e=[v["enerji"] for v in veriler]; ort,std=statistics.mean(e),statistics.stdev(e)
    return round((e[-1]-ort)/std,2) if std else 0.0

def mevsimsel_oneri():
    ay=datetime.date.today().month
    if ay in [12,1,2]:  return "❄️","Kış: Isıtıcı filtrelerini kontrol edin."
    elif ay in [3,4,5]: return "🌸","İlkbahar: Klima bakımı için ideal dönem."
    elif ay in [6,7,8]: return "☀️","Yaz: Klimayı 24°C üstünde tutun."
    else:               return "🍂","Sonbahar: Pencere contalarını kontrol edin."

def komsu_karsilastirma(kwh,il):
    ort=IL_ORTALAMA.get(il,15.0); fark=round(((kwh-ort)/ort)*100,1)
    if fark<0:    return f"{il} ortalamasının %{abs(fark)} altındasınız ✓","positive"
    elif fark==0: return f"{il} ortalamasındasınız.","neutral"
    else:         return f"{il} ortalamasının %{fark} üzerindesiniz ↑","negative"

def tasarruf_onerileri(kwh,yb):
    o=[]; bugun=max(datetime.date.today().day,1); g=kwh/bugun; s=datetime.datetime.now().hour; st=get_state()
    if g>1.5:       o.append("Gece 23:00–06:00 cihazları bekleme moduna alın.")
    if s in PIK_SAATLER: o.append("Şu an pik tarife — ağır cihazları kapatın.")
    if yb>70:       o.append("Bütçenizin %70'ini aştınız — tüketimi kısın.")
    if kwh*CO2_KATSAYI>8: o.append("LED ampule geçiş CO₂'yi %40 azaltır.")
    if g>st["gunluk_hedef"]: o.append(f"Günlük hedefiniz ({st['gunluk_hedef']} kWh) aşıldı.")
    o.append("Buzdolabı arkasını temizlemek %10 tasarruf sağlar.")
    o.append("Çamaşır/bulaşık makinelerini gece çalıştırın.")
    return o

# ── OCR ──────────────────────────────────────────────────────────────────────
def goruntu_isle(img_cv2):
    gri=cv2.cvtColor(img_cv2,cv2.COLOR_BGR2GRAY)
    clahe=cv2.createCLAHE(clipLimit=3.0,tileGridSize=(8,8)); gri=clahe.apply(gri)
    gri=cv2.GaussianBlur(gri,(3,3),0)
    return cv2.adaptiveThreshold(gri,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,11,2)

def sayi_cikart(metin):
    kwh_p=re.findall(r'(\d[\d\s]*[.,]\d+|\d+)\s*(?:kwh|kw\.h|kwsa|k\.?w\.?h)',metin.lower().replace('\n',' '))
    if kwh_p:
        try: return float(kwh_p[0].replace(' ','').replace(',','.')), "kwh_etiketli"
        except: pass
    sayac_p=re.findall(r'\b0*(\d{3,6}[.,]\d{1,3})\b',metin)
    if sayac_p:
        try: return float(sayac_p[0].replace(',','.')), "sayac_format"
        except: pass
    genel=re.findall(r'\b(\d{2,6}(?:[.,]\d{1,3})?)\b',metin)
    sayilar=[float(s.replace(',','.')) for s in genel if s.replace(',','.').replace('.','').isdigit() or True]
    uygun=[s for s in sayilar if 1.0<=s<=99999.0]
    if uygun: return max(uygun),"genel_sayi"
    return None,"bulunamadi"

def ocr_isle(image_bytes):
    if not OCR_AKTIF:
        return {"kwh":None,"ham_metin":"","yontem":"","hata":"OCR kurulu değil."}
    try:
        pil_img=Image.open(io.BytesIO(image_bytes)).convert("RGB")
        np_img=np.array(pil_img)
        cv_img=cv2.cvtColor(np_img,cv2.COLOR_RGB2BGR)
        islenmis=goruntu_isle(cv_img)
        config=r'--oem 3 --psm 6 -l tur+eng'
        metin=pytesseract.image_to_string(islenmis,config=config)
        kwh,yontem=sayi_cikart(metin)
        return {"kwh":kwh,"ham_metin":metin.strip(),"yontem":yontem,"hata":None}
    except Exception as e:
        return {"kwh":None,"ham_metin":"","yontem":"","hata":str(e)}

# ── GRAFİKLER ────────────────────────────────────────────────────────────────
def grafik_b64(fig):
    buf=io.BytesIO(); fig.savefig(buf,format="png",transparent=True,dpi=110,bbox_inches='tight')
    buf.seek(0); plt.close(fig)
    return "data:image/png;base64,"+base64.b64encode(buf.read()).decode()

def haftalik_grafik():
    veriler=gunluk_enerji_grafik_veri(); gunler=[v["gun"] for v in veriler]; enerji=[v["enerji"] for v in veriler]
    ort=sum(enerji)/len(enerji); state=get_state()
    fig,ax=plt.subplots(figsize=(5.5,3.2)); fig.patch.set_facecolor("none"); ax.set_facecolor("#111")
    renkler=["#FF9A00" if e>ort else "#455A64" for e in enerji]
    bars=ax.bar(gunler,enerji,color=renkler,width=0.55,zorder=2,edgecolor="#222")
    for bar,val in zip(bars,enerji):
        ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+0.02,f"{val:.1f}",ha="center",va="bottom",color="#ddd",fontsize=7.5)
    if len(enerji)>=3:
        kayan=[sum(enerji[max(0,i-2):i+1])/min(i+1,3) for i in range(len(enerji))]
        ax.plot(gunler,kayan,color="#fff",lw=1.5,ls="--",marker="o",ms=4,zorder=3,label="3g Ort.")
    ax.axhline(state["gunluk_hedef"],color="#42A5F5",lw=1.2,ls=":",label=f"Hedef {state['gunluk_hedef']}kWh")
    ax.axhline(ort,color="#FF7043",lw=1,ls=":")
    ax.text(len(gunler)-0.5,ort+0.03,f"Ort:{ort:.2f}",color="#FF7043",fontsize=7,ha="right")
    ax.set_xlabel("Gün",color="#888",fontsize=8); ax.set_ylabel("kWh",color="#888",fontsize=8)
    ax.tick_params(colors="#888",labelsize=7)
    for sp in ax.spines.values(): sp.set_edgecolor("#333")
    ax.legend(fontsize=7,facecolor="#1a1a1a",edgecolor="#333",labelcolor="white",loc="upper left")
    ax.grid(True,axis="y",alpha=0.12); plt.tight_layout(pad=0.4)
    return grafik_b64(fig)

def yillik_grafik():
    aylar=["Oca","Şub","Mar","Nis","May","Haz","Tem","Ağu","Eyl","Eki","Kas","Ara"]
    rng=np.random.default_rng(99)
    bu=[round(8+i*0.5+rng.uniform(-1,1),1) for i in range(12)]
    gec=[round(9+i*0.4+rng.uniform(-1,1),1) for i in range(12)]
    fig,ax=plt.subplots(figsize=(5.5,2.8)); fig.patch.set_facecolor("none"); ax.set_facecolor("#111")
    x=range(12)
    ax.bar([i-.2 for i in x],gec,width=0.36,color="#455A64",label="Geçen Yıl")
    ax.bar([i+.2 for i in x],bu,width=0.36,color="#FF9A00",label="Bu Yıl")
    ax.set_xticks(range(12)); ax.set_xticklabels(aylar,fontsize=6,color="#888")
    ax.tick_params(colors="#888",labelsize=6)
    for sp in ax.spines.values(): sp.set_edgecolor("#333")
    ax.legend(fontsize=6,facecolor="#1a1a1a",edgecolor="#333",labelcolor="white")
    ax.grid(True,axis="y",alpha=0.12); plt.tight_layout(pad=0.3)
    return grafik_b64(fig)

def isita_haritasi():
    rng=np.random.default_rng(42); veri=rng.uniform(0,2.5,(7,24))
    fig,ax=plt.subplots(figsize=(6,3)); fig.patch.set_facecolor("none")
    im=ax.imshow(veri,cmap="YlOrRd",aspect="auto",interpolation="bilinear")
    ax.set_xticks(range(0,24,2)); ax.set_xticklabels([f"{h:02d}" for h in range(0,24,2)],fontsize=7,color="#aaa")
    ax.set_yticks(range(7)); ax.set_yticklabels(["Pzt","Sal","Çar","Per","Cum","Cmt","Paz"],fontsize=8,color="#aaa")
    plt.colorbar(im,ax=ax,label="kWh",shrink=0.8)
    ax.set_title("Saatlik Tüketim Isı Haritası",color="#ccc",fontsize=9,pad=4)
    plt.tight_layout(pad=0.4)
    return grafik_b64(fig)

# ── AUTH DECORATOR ────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args,**kwargs):
        if "user" not in session: return jsonify({"error":"Giriş gerekli"}),401
        return f(*args,**kwargs)
    return decorated

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user" in session: return render_template("app.html",user=session["user"])
    return render_template("login.html")

@app.route("/api/giris",methods=["POST"])
def api_giris():
    d=request.json; u,p=d.get("kullanici",""),d.get("sifre","")
    if not u or not p: return jsonify({"ok":False,"mesaj":"Alanları doldurun."})
    if giris_yap(u,p): session["user"]=u; return jsonify({"ok":True})
    return jsonify({"ok":False,"mesaj":"Kullanıcı adı veya şifre geçersiz."})

@app.route("/api/kayit",methods=["POST"])
def api_kayit():
    d=request.json; u,p,p2=d.get("kullanici",""),d.get("sifre",""),d.get("sifre2","")
    if not u or not p: return jsonify({"ok":False,"mesaj":"Tüm alanları doldurun."})
    gecerli,hata=sifre_dogrula(p)
    if not gecerli: return jsonify({"ok":False,"mesaj":hata})
    if p!=p2: return jsonify({"ok":False,"mesaj":"Şifreler eşleşmiyor."})
    kayit_ol(u,p); return jsonify({"ok":True,"mesaj":"Kayıt tamamlandı!"})

@app.route("/api/cikis",methods=["POST"])
def api_cikis():
    session.clear(); return jsonify({"ok":True})

@app.route("/api/ocr_durum")
def api_ocr_durum():
    return jsonify({"aktif":OCR_AKTIF})

@app.route("/api/ocr_oku",methods=["POST"])
@login_required
def api_ocr_oku():
    if "foto" not in request.files: return jsonify({"ok":False,"mesaj":"Fotoğraf gönderilmedi.","kwh":None})
    dosya=request.files["foto"]
    dosya.seek(0,2); boyut=dosya.tell(); dosya.seek(0)
    if boyut>10*1024*1024: return jsonify({"ok":False,"mesaj":"Max 10 MB.","kwh":None})
    sonuc=ocr_isle(dosya.read())
    if sonuc["hata"]: return jsonify({"ok":False,"kwh":None,"ham_metin":sonuc["ham_metin"],"mesaj":f"Hata: {sonuc['hata']}"})
    kwh=sonuc["kwh"]
    return jsonify({"ok":kwh is not None,"kwh":kwh,"ham_metin":sonuc["ham_metin"],"yontem":sonuc["yontem"],
                    "mesaj":f"{kwh} kWh okundu" if kwh else "Değer okunamadı. Daha net fotoğraf deneyin."})

@app.route("/api/dashboard")
@login_required
def api_dashboard():
    kwh=toplam_enerji(); state=get_state(); maliyet=round(kwh*BIRIM_FIYAT,2)
    yuzde=round(min(100,(maliyet/state["butce"])*100),1); skor,renk=verimlilik_skoru(kwh)
    tahmin_kwh,tahmin_tl=ay_sonu_tahmin(kwh); co2=co2_hesapla(kwh)
    bugun=max(datetime.date.today().day,1); gunluk_ort=round(kwh/bugun,2)
    hedef_yuzde=round(min(100,(gunluk_ort/state["gunluk_hedef"])*100),1)
    saat=datetime.datetime.now().hour; pik=saat in PIK_SAATLER
    _,mevsim=mevsimsel_oneri(); komsu_txt,komsu_tip=komsu_karsilastirma(kwh,state["secili_il"])
    return jsonify({"kwh":kwh,"maliyet":maliyet,"yuzde_butce":yuzde,"skor":skor,"skor_renk":renk,
        "co2":co2,"tahmin_kwh":tahmin_kwh,"tahmin_tl":tahmin_tl,"gunluk_ort":gunluk_ort,
        "hedef_yuzde":hedef_yuzde,"pik":pik,"pik_saat":saat,
        "oneriler":tasarruf_onerileri(kwh,yuzde),"mevsim":mevsim,
        "komsu":komsu_txt,"komsu_tip":komsu_tip,"butce":state["butce"],
        "gunluk_hedef":state["gunluk_hedef"],"secili_il":state["secili_il"],
        "haftalik_grafik":haftalik_grafik()})

@app.route("/api/rapor")
@login_required
def api_rapor():
    kwh=toplam_enerji(); state=get_state(); co2=co2_hesapla(kwh)
    veriler=gunluk_enerji_grafik_veri(); z=anomali_skoru(veriler)
    ikon,mevsim=mevsimsel_oneri(); komsu_txt,komsu_tip=komsu_karsilastirma(kwh,state["secili_il"])
    return jsonify({"co2":co2,"z_skoru":z,"mevsim_ikon":ikon,"mevsim":mevsim,
        "komsu":komsu_txt,"komsu_tip":komsu_tip,"yillik_grafik":yillik_grafik(),"isita":isita_haritasi()})

@app.route("/api/il_karsilastir",methods=["POST"])
@login_required
def api_il():
    il=request.json.get("il","").strip(); eslesen=None
    for i in ILLER:
        if i.lower()==il.lower(): eslesen=i; break
    if not eslesen:
        for i in ILLER:
            if il.lower() in i.lower(): eslesen=i; break
    if eslesen:
        state=get_state(); state["secili_il"]=eslesen; kwh=toplam_enerji()
        txt,tip=komsu_karsilastirma(kwh,eslesen)
        return jsonify({"ok":True,"il":eslesen,"ort":IL_ORTALAMA[eslesen],"sonuc":txt,"tip":tip})
    return jsonify({"ok":False,"mesaj":f"'{il}' bulunamadı."})

@app.route("/api/olcum_ekle",methods=["POST"])
@login_required
def api_olcum_ekle():
    try:
        val=float(request.json.get("deger",0)); olcum_ekle(val)
        return jsonify({"ok":True,"yeni_toplam":toplam_enerji()})
    except: return jsonify({"ok":False,"mesaj":"Geçersiz değer."})

@app.route("/api/butce_kaydet",methods=["POST"])
@login_required
def api_butce():
    try:
        state=get_state(); state["butce"]=float(request.json.get("butce",0))
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/hedef_kaydet",methods=["POST"])
@login_required
def api_hedef():
    try:
        state=get_state(); state["gunluk_hedef"]=float(request.json.get("hedef",0))
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/chatbot",methods=["POST"])
@login_required
def api_chatbot():
    soru=request.json.get("soru","").lower(); kwh=toplam_enerji(); state=get_state()
    maliyet=kwh*BIRIM_FIYAT; tahmin_kwh,tahmin_tl=ay_sonu_tahmin(kwh)
    co2=co2_hesapla(kwh); skor,_=verimlilik_skoru(kwh)
    yuzde=(maliyet/state["butce"])*100; saat=datetime.datetime.now().hour
    tablo=[
        (["harcad","tükettim","ne kadar","kaç kwh","kullandım"],f"Bu ay {kwh:.2f} kWh — ₺{maliyet:.2f}."),
        (["tahmin","ay sonu","fatura"],f"Ay sonu tahmini: {tahmin_kwh} kWh — ₺{tahmin_tl}."),
        (["co2","karbon","çevre","emisyon"],f"CO₂: {co2['co2_kg']} kg — {co2['agac_esit']} ağaç eşdeğeri."),
        (["tasarruf","azalt","düşür"],"\n".join(["• "+o for o in tasarruf_onerileri(kwh,yuzde)[:4]])),
        (["skor","verimlilik"],f"Verimlilik: {skor} (A=en iyi, G=en kötü)"),
        (["bütçe","limit"],f"Bütçe ₺{state['butce']:.0f} — %{yuzde:.0f} kullanıldı."),
        (["pik","tarife","saat"],f"Pik: 06–10 ve 17–22. Şu an: {'⚡ PİK!' if saat in PIK_SAATLER else 'normal.'}"),
        (["merhaba","selam","hey"],"Merhaba! Tüketim, maliyet, CO₂ veya tasarruf sorabilirsiniz."),
        (["il","şehir","bölge"],f"{state['secili_il']} ort: {IL_ORTALAMA.get(state['secili_il'],15.0)} kWh/ay."),
    ]
    cevap=next((y for k,y in tablo if any(x in soru for x in k)),None)
    if not cevap: cevap="Deneyin: 'tüketim', 'tasarruf', 'tahmin', 'co2', 'bütçe', 'pik saat'."
    return jsonify({"cevap":cevap})

@app.route("/api/iller")
def api_iller():
    return jsonify(ILLER)

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port,debug=False)
