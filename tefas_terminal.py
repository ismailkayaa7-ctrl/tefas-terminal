"""
TEFAS Terminal — Fon performans ve risk taraması.
Önceki app.py'den bağımsız, yeni bir tasarım ve ek özellik (ay içi 3 dilim sıralaması) içerir.
"""

import calendar
import numpy as np
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------------------
# Sayfa ayarları ve görsel kimlik
# --------------------------------------------------------------------------------------

st.set_page_config(page_title="TEFAS Terminal", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Inter:wght@400;500;600&display=swap');

:root {
    --bg: #101820;
    --surface: #17222E;
    --surface-2: #1C2A38;
    --text: #EDEAE0;
    --muted: #8B97A3;
    --gold: #C9A227;
    --gain: #4FA98A;
    --loss: #C05B44;
    --rule: rgba(237,234,224,0.10);
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: var(--bg); color: var(--text); }

/* Streamlit'in varsayılan yuvarlatılmış kart/gölge görünümünü kaldır */
div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] { gap: 0.5rem; }
section[data-testid="stSidebar"] { background-color: var(--surface); border-right: 1px solid var(--rule); }
div[data-testid="stMetric"] {
    background-color: var(--surface);
    border: 1px solid var(--rule);
    border-radius: 2px;
    padding: 0.9rem 1.1rem;
}
div[data-testid="stMetricValue"] { font-family: 'Source Serif 4', serif; color: var(--text); }
div[data-testid="stMetricLabel"] { color: var(--muted); font-size: 0.85rem; }

.terminal-title {
    font-family: 'Source Serif 4', serif;
    font-weight: 600;
    font-size: 2.1rem;
    color: var(--text);
    margin-bottom: 0;
}
.terminal-sub {
    color: var(--muted);
    font-size: 0.95rem;
    margin-top: 0.15rem;
    margin-bottom: 1.4rem;
}
.rule { border-top: 1px solid var(--rule); margin: 1.1rem 0 1.4rem 0; }

.stTabs [data-baseweb="tab-list"] { gap: 1.6rem; border-bottom: 1px solid var(--rule); }
.stTabs [data-baseweb="tab"] {
    background: transparent; color: var(--muted);
    font-size: 0.95rem; padding-bottom: 0.6rem;
}
.stTabs [aria-selected="true"] { color: var(--gold) !important; border-bottom: 2px solid var(--gold) !important; }

.dilim-baslik {
    font-family: 'Source Serif 4', serif;
    font-size: 1.05rem;
    color: var(--text);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.4rem;
    margin-bottom: 0.6rem;
}
.dilim-satir {
    display: flex; justify-content: space-between;
    padding: 0.45rem 0.1rem;
    border-bottom: 1px solid var(--rule);
    font-size: 0.92rem;
}
.dilim-kod { color: var(--text); font-weight: 500; }
.dilim-gun { color: var(--muted); font-size: 0.8rem; margin-left: 0.4rem; }
.dilim-getiri { font-variant-numeric: tabular-nums; font-weight: 600; }
.pozitif { color: var(--gain); }
.negatif { color: var(--loss); }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="terminal-title">TEFAS Terminal</div>', unsafe_allow_html=True)
st.markdown('<div class="terminal-sub">Fon performans matrisi ve ay içi getiri sıralaması</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------------------
# Veri yükleme ve temizlik
# --------------------------------------------------------------------------------------

@st.cache_data
def verileri_yukle():
    df = pd.read_parquet('tefas.parquet')
    df.columns = [str(c).lower().strip() for c in df.columns]
    col_map = {}
    for c in df.columns:
        if 'tarih' in c: col_map['tarih'] = c
        elif 'kod' in c: col_map['fon_kodu'] = c
        elif 'ad' in c: col_map['fon_adi'] = c
        elif 'fiyat' in c: col_map['fiyat'] = c
    return df, col_map


def normalize_tr(s):
    s = str(s).upper()
    return (s.replace('İ', 'I').replace('Ç', 'C').replace('Ğ', 'G')
             .replace('Ş', 'S').replace('Ö', 'O').replace('Ü', 'U'))


KATEGORI_ANAHTAR_KELIMELER = [
    ("Serbest", ["SERBEST"]),
    ("Altın", ["ALTIN"]),
    ("Kıymetli Maden", ["GUMUS", "KIYMETLI MADEN", "PLATIN"]),
    ("Para Piyasası", ["PARA PIYASASI"]),
    ("Katılım", ["KATILIM"]),
    ("Borçlanma Araçları", ["BORCLANMA"]),
    ("Hisse Senedi", ["HISSE SENEDI", "HISSE"]),
    ("Değişken", ["DEGISKEN"]),
    ("Karma", ["KARMA"]),
    ("Fon Sepeti", ["FON SEPETI"]),
    ("Endeks", ["ENDEKS"]),
    ("Girişim Sermayesi", ["GIRISIM SERMAYESI"]),
    ("Gayrimenkul", ["GAYRIMENKUL"]),
]


def kategori_belirle(ad):
    """Fon adındaki anahtar kelimelerden kategori tahmini yapar.
    Not: TEFAS'ın resmi sınıflandırması değil, isim bazlı bir tahmindir."""
    normalize_edilmis = normalize_tr(ad)
    for kategori, kelimeler in KATEGORI_ANAHTAR_KELIMELER:
        if any(normalize_tr(k) in normalize_edilmis for k in kelimeler):
            return kategori
    return "Diğer"


@st.cache_data(ttl=60 * 60 * 12)  # 12 saatte bir tazelenir
def aktif_fon_kodlarini_getir():
    """TEFAS'ın resmi API'sinden şu an gerçekten işlem gören fonların kod listesini çeker.
    İnternet yoksa ya da API değiştiyse None döner (bu durumda filtre uygulanmaz)."""
    try:
        from pytefas import Crawler
    except ImportError:
        return None

    tefas = Crawler(timeout=10, max_retry=1)
    bugun = pd.Timestamp.today().normalize()
    for gerigit in range(0, 5):  # hafta sonu / resmi tatil ihtimaline karşı geriye doğru dene
        tarih = (bugun - pd.Timedelta(days=gerigit)).strftime("%Y-%m-%d")
        try:
            bilgi = tefas.fetch_many(tarih, kinds=("YAT", "EMK", "BYF"), columns="info")
            if bilgi is not None and not bilgi.empty:
                return set(bilgi["fund_code"].unique())
        except Exception:
            continue
    return None


def veriyi_temizle(df, t_col, k_col, f_col, sicrama_esik):
    df = df.copy()
    df[t_col] = pd.to_datetime(df[t_col], errors='coerce')
    # Sıfır / negatif fiyatlar eksik veri kabul edilip elenir
    df.loc[df[f_col] <= 0, f_col] = np.nan
    df = df.dropna(subset=[t_col, k_col, f_col]).sort_values([k_col, t_col])

    # Tek günlük aşırı sıçramalar (bölünme / veri hatası şüphesi) nötrlenir:
    # sıçrama günü "gerçek getirisi sıfır" kabul edilip fiyat zinciri kesintisiz devam eder.
    ust_sinir = 1 + sicrama_esik / 100.0
    alt_sinir = 1 - sicrama_esik / 100.0

    def duzelt(seri):
        fiyatlar = seri.to_numpy(copy=True)
        for i in range(1, len(fiyatlar)):
            onceki = fiyatlar[i - 1]
            if onceki == 0:
                continue
            oran = fiyatlar[i] / onceki
            if oran > ust_sinir or oran < alt_sinir:
                fiyatlar[i] = onceki
        return pd.Series(fiyatlar, index=seri.index)

    df[f_col] = df.groupby(k_col)[f_col].transform(duzelt)
    return df


ham_df, col_map = verileri_yukle()

if ham_df.empty:
    st.warning("Veritabanında veri bulunamadı!")
elif not {'tarih', 'fon_kodu', 'fiyat'} <= col_map.keys():
    st.error(f"Excel sütunları otomatik eşleştirilemedi. Mevcut sütunlar: {list(ham_df.columns)}")
else:
    t_col, k_col, f_col = col_map['tarih'], col_map['fon_kodu'], col_map['fiyat']

    # --- Kenar çubuğu ---
    st.sidebar.markdown("**Analiz parametreleri**")
    risksiz_faiz = st.sidebar.number_input("Yıllık risksiz faiz (%)", value=40.0, step=1.0) / 100.0

    st.sidebar.markdown("**Veri temizliği**")
    sicrama_esik = st.sidebar.slider(
        "Sıçrama filtre eşiği (%)", min_value=20, max_value=150, value=60, step=5,
        help="Bir günde bu yüzdeden fazla değişen fiyatlar birim pay bölünmesi / veri hatası kabul edilip nötrlenir."
    )
    min_gun = st.sidebar.number_input(
        "Güvenilir kabul edilecek min. işlem günü", min_value=5, max_value=250, value=30, step=5,
        help="Bu değerin altında geçmişi olan fonlar 'Düşük Güvenilirlik' etiketiyle işaretlenir."
    )

    df = veriyi_temizle(ham_df, t_col, k_col, f_col, sicrama_esik)

    st.sidebar.markdown("**Aktif fon filtresi**")
    aktif_kodlar = aktif_fon_kodlarini_getir()
    if aktif_kodlar is None:
        st.sidebar.caption("⚠️ TEFAS'tan güncel fon listesi çekilemedi (internet/API sorunu). Bu filtre şu an uygulanamıyor.")
    else:
        sadece_aktif = st.sidebar.checkbox(
            "Sadece hâlâ TEFAS'ta işlem gören fonları göster", value=True,
            help=f"TEFAS'ın resmi API'sinden az önce çekilen güncel listeye göre {len(aktif_kodlar)} fon işlem görüyor. "
                 "Bu listede olmayan fon kodları (muhtemelen işlem görmeyi durdurmuş) tamamen dışlanır."
        )
        if sadece_aktif:
            df = df[df[k_col].isin(aktif_kodlar)]

    ad_col = col_map.get('fon_adi')
    if ad_col:
        st.sidebar.markdown("**Kategori filtresi**")
        fon_kategori = ham_df.drop_duplicates(subset=k_col).set_index(k_col)[ad_col].apply(kategori_belirle)
        tum_kategoriler = sorted(fon_kategori.unique(), key=lambda x: (x != "Serbest", x))
        secili_kategoriler = []
        with st.sidebar.expander("Kategoriye göre filtrele", expanded=False):
            for kat in tum_kategoriler:
                sayi = (fon_kategori == kat).sum()
                if st.checkbox(f"{kat} ({sayi})", value=True, key=f"kat_{kat}"):
                    secili_kategoriler.append(kat)
        izinli_kodlar = fon_kategori[fon_kategori.isin(secili_kategoriler)].index
        df = df[df[k_col].isin(izinli_kodlar)]

    genel_sekme, dilim_sekme = st.tabs(["Genel performans", "Ay içi 3 dilim sıralaması"])

    # ------------------------------------------------------------------------------
    # Sekme 1: Genel performans matrisi
    # ------------------------------------------------------------------------------
    with genel_sekme:
        donem = st.selectbox("Analiz periyodu", ["Son 1 Ay", "Son 3 Ay", "Son 6 Ay", "Son 1 Yıl", "Tümü"])
        gun_map = {"Son 1 Ay": 30, "Son 3 Ay": 90, "Son 6 Ay": 180, "Son 1 Yıl": 365, "Tümü": 99999}
        gun_sayisi = gun_map[donem]

        max_tarih = df[t_col].max()
        if gun_sayisi != 99999:
            df_filt = df[df[t_col] >= max_tarih - pd.Timedelta(days=gun_sayisi)]
        else:
            df_filt = df

        piv = df_filt.pivot_table(index=t_col, columns=k_col, values=f_col, aggfunc='last').dropna(axis=1, how='all')

        if piv.empty:
            st.warning("Seçilen dönemde yeterli veri bulunamadı.")
        else:
            gunluk_getiriler = piv.pct_change().dropna(how='all')

            ilk_fiyatlar = piv.bfill().iloc[0]
            son_fiyatlar = piv.ffill().iloc[-1]
            toplam_getiri = (son_fiyatlar / ilk_fiyatlar) - 1

            islem_gunu = piv.count()
            yillik_getiri = (1 + toplam_getiri) ** (252 / islem_gunu.clip(lower=1)) - 1
            volatilite = gunluk_getiriler.std() * np.sqrt(252)
            sharpe = (yillik_getiri - risksiz_faiz) / volatilite

            neg_getiriler = gunluk_getiriler[gunluk_getiriler < 0]
            asagi_vol = neg_getiriler.std() * np.sqrt(252)
            sortino = (yillik_getiri - risksiz_faiz) / asagi_vol

            kumulatif = (1 + gunluk_getiriler.fillna(0)).cumprod()
            tepe = kumulatif.cummax()
            dusnis = (kumulatif - tepe) / tepe
            max_dd = dusnis.min()

            calmar = yillik_getiri / abs(max_dd)
            var_95 = gunluk_getiriler.quantile(0.05)
            skew = gunluk_getiriler.skew()
            kurt = gunluk_getiriler.kurtosis()

            sonuc_df = pd.DataFrame({
                'İşlem Günü': islem_gunu,
                'Yıllık Getiri (%)': (yillik_getiri * 100).round(2),
                'Volatilite (%)': (volatilite * 100).round(2),
                'Sharpe Oranı': sharpe.round(2),
                'Sortino Oranı': sortino.round(2),
                'Max Düşüş (%)': (max_dd * 100).round(2),
                'Calmar Oranı': calmar.round(2),
                'Günlük VaR (%95)': (var_95 * 100).round(2),
                'Çarpıklık': skew.round(2),
                'Basıklık': kurt.round(2),
            }).dropna()

            sonuc_df['Veri Kalitesi'] = np.where(sonuc_df['İşlem Günü'] < min_gun, 'Düşük Güvenilirlik', 'Normal')
            sonuc_df = sonuc_df.sort_values(by="Sharpe Oranı", ascending=False)

            c1, c2, c3 = st.columns(3)
            c1.metric("Taranan fon", len(sonuc_df))
            en_iyi = sonuc_df.iloc[0]
            c2.metric("En yüksek Sharpe", en_iyi.name, f"{en_iyi['Sharpe Oranı']}")
            c3.metric("Ortalama yıllık getiri", f"%{sonuc_df['Yıllık Getiri (%)'].mean():.1f}")

            st.markdown('<div class="rule"></div>', unsafe_allow_html=True)

            tum_metrikler = ['İşlem Günü', 'Yıllık Getiri (%)', 'Volatilite (%)', 'Sharpe Oranı', 'Sortino Oranı',
                              'Max Düşüş (%)', 'Calmar Oranı', 'Günlük VaR (%95)', 'Çarpıklık', 'Basıklık',
                              'Veri Kalitesi']
            secili_metrikler = st.multiselect(
                "Gösterilecek metrikler", options=tum_metrikler, default=tum_metrikler, key="genel_metrik_secim"
            )

            def satir_renklendir(row):
                if sonuc_df.loc[row.name, 'Veri Kalitesi'] == 'Düşük Güvenilirlik':
                    return ['background-color: rgba(201,162,39,0.10)'] * len(row)
                return [''] * len(row)

            gosterilecek = sonuc_df[secili_metrikler] if secili_metrikler else sonuc_df
            st.dataframe(gosterilecek.style.apply(satir_renklendir, axis=1), use_container_width=True)

            with st.expander("Veri temizliği hakkında"):
                st.markdown(f"""
                - Sıfır/negatif fiyatlar eksik veri kabul edilip hesap dışı bırakıldı.
                - Tek günde %{sicrama_esik}'den fazla değişen fiyatlar bölünme/veri hatası kabul edilip nötrlendi.
                - {min_gun} günden az işlem geçmişi olan fonlar 'Düşük Güvenilirlik' etiketiyle işaretlendi.
                """)

    # ------------------------------------------------------------------------------
    # Sekme 2: Ay içi 3 dilim sıralaması (1-10 / 11-20 / 21-ay sonu)
    # ------------------------------------------------------------------------------
    with dilim_sekme:
        st.caption("Seçilen ay, gerçek takvim günlerine göre üç dilime bölünür: 1-10, 11-20, 21-ay sonu. "
                   "Her dilim için fonlar, dilim içindeki getirilerine göre ayrı ayrı sıralanır.")

        mevcut_aylar = sorted(df[t_col].dt.to_period('M').unique())
        ay_isimleri_tr = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                           "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        ay_etiketleri = {p: f"{ay_isimleri_tr[p.month - 1]} {p.year}" for p in mevcut_aylar}

        secili_ay = st.selectbox(
            "Ay seç", options=mevcut_aylar, index=len(mevcut_aylar) - 1,
            format_func=lambda p: ay_etiketleri[p]
        )
        yil, ay = secili_ay.year, secili_ay.month
        ay_son_gun = calendar.monthrange(yil, ay)[1]
        dilimler = [("1 - 10", 1, 10), ("11 - 20", 11, 20), (f"21 - {ay_son_gun}", 21, ay_son_gun)]

        st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
        kolonlar = st.columns(3)

        for (etiket, gun_bas, gun_bit), kolon in zip(dilimler, kolonlar):
            filt = df[(df[t_col].dt.year == yil) & (df[t_col].dt.month == ay)
                      & (df[t_col].dt.day >= gun_bas) & (df[t_col].dt.day <= gun_bit)]

            with kolon:
                st.markdown(f'<div class="dilim-baslik">{ay_etiketleri[secili_ay]} · {etiket}</div>',
                             unsafe_allow_html=True)

                if filt.empty:
                    st.caption("Bu dilimde veri yok.")
                    continue

                piv_d = filt.pivot_table(index=t_col, columns=k_col, values=f_col, aggfunc='last')
                ilk = piv_d.bfill().iloc[0]
                son = piv_d.ffill().iloc[-1]
                getiri = ((son / ilk - 1) * 100).round(2)
                gun_d = piv_d.count()
                sonuc_d = pd.DataFrame({'Getiri': getiri, 'Gün': gun_d}).dropna()
                sonuc_d = sonuc_d.sort_values('Getiri', ascending=False)

                for kod, satir in sonuc_d.head(15).iterrows():
                    sinif = 'pozitif' if satir['Getiri'] >= 0 else 'negatif'
                    isaret = '+' if satir['Getiri'] >= 0 else ''
                    st.markdown(f"""
                    <div class="dilim-satir">
                        <span><span class="dilim-kod">{kod}</span><span class="dilim-gun">{int(satir['Gün'])} gün</span></span>
                        <span class="dilim-getiri {sinif}">{isaret}{satir['Getiri']}%</span>
                    </div>
                    """, unsafe_allow_html=True)

                st.download_button(
                    f"{etiket} verisini indir (CSV)",
                    sonuc_d.to_csv().encode('utf-8'),
                    file_name=f"tefas_dilim_{yil}{ay:02d}_{gun_bas}-{gun_bit}.csv",
                    key=f"indir_{gun_bas}_{gun_bit}",
                )

        # --------------------------------------------------------------------------
        # Ay geneli ortalama sıralama (puan): her dilimde 1. olan 1 puan, 2. olan 2 puan...
        # 3 dilimdeki sıraların ortalaması alınır, en düşük ortalama en istikrarlı fonu gösterir.
        # --------------------------------------------------------------------------
        st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
        st.markdown('<div class="dilim-baslik">Ay geneli ortalama sıralama (puan)</div>', unsafe_allow_html=True)
        st.caption(
            f"Her 10 günlük dilimde en yüksek getiriyi sağlayan fon 1. sırayı alır. Üç dilimdeki sıraların "
            f"ortalaması alınır; en düşük ortalama en istikrarlı şampiyonu gösterir. Yalnızca genel geçmişi en "
            f"az {min_gun} gün olan fonlar dahil edilir."
        )

        sira_parcalari = []
        for etiket, gun_bas, gun_bit in dilimler:
            filt = df[(df[t_col].dt.year == yil) & (df[t_col].dt.month == ay)
                      & (df[t_col].dt.day >= gun_bas) & (df[t_col].dt.day <= gun_bit)]
            if filt.empty:
                continue
            piv_d = filt.pivot_table(index=t_col, columns=k_col, values=f_col, aggfunc='last')
            ilk = piv_d.bfill().iloc[0]
            son = piv_d.ffill().iloc[-1]
            getiri_d = ((son / ilk - 1) * 100).dropna()
            sira_d = getiri_d.rank(ascending=False, method='min')
            sira_parcalari.append(pd.DataFrame({
                f'{etiket} Getiri (%)': getiri_d.round(2),
                f'{etiket} Sıra': sira_d,
            }))

        if sira_parcalari:
            birlesik = pd.concat(sira_parcalari, axis=1)
            sira_kolonlari = [c for c in birlesik.columns if c.endswith('Sıra')]
            birlesik['Ortalama Sıra (Puan)'] = birlesik[sira_kolonlari].mean(axis=1).round(2)

            # En az min_gun gündür fiyatlanan fonlar (bu aya bakılmaksızın, genel geçmiş)
            genel_gun_sayisi = df.groupby(k_col)[t_col].nunique()
            uygun_kodlar = genel_gun_sayisi[genel_gun_sayisi >= min_gun].index

            birlesik = birlesik[birlesik.index.isin(uygun_kodlar)].dropna(subset=['Ortalama Sıra (Puan)'])
            birlesik = birlesik.sort_values('Ortalama Sıra (Puan)')

            if birlesik.empty:
                st.info(f"En az {min_gun} günlük geçmişi olan ve bu ayın tüm dilimlerinde verisi bulunan fon yok.")
            else:
                tum_kolonlar = list(birlesik.columns)
                on_secili = ['Ortalama Sıra (Puan)'] + [c for c in tum_kolonlar if c.endswith('Getiri (%)')]
                secili_kolonlar = st.multiselect(
                    "Gösterilecek metrikler", options=tum_kolonlar, default=on_secili, key="dilim_metrik_secim"
                )
                st.dataframe(
                    birlesik[secili_kolonlar] if secili_kolonlar else birlesik,
                    use_container_width=True
                )
                st.download_button(
                    "Genel ortalama sıralamayı indir (CSV)",
                    birlesik.to_csv().encode('utf-8'),
                    file_name=f"tefas_ortalama_siralama_{yil}{ay:02d}.csv",
                    key="indir_ortalama_siralama",
                )
