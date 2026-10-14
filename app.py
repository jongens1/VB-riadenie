import streamlit as st
import pandas as pd
import math
import os

# Konfigurácia stránky
st.set_page_config(
    page_title="Plánovač Zaskladňovania VB",
    page_icon="🏗️",
    layout="wide"
)

st.title("🏗️ Plánovač Riadenia Zaskladňovania (Veľká Biela)")
st.caption("Interný nástroj pre optimalizáciu ukladania produktov na lokácie")

# Názov predvoleného súboru v GitHub repozitári
DEFAULT_EXCEL_PATH = "data.xlsx"

# --- NAHRATIE A SPRACOVANIE DÁT ---
@st.cache_data
def load_data_from_excel(file_path_or_buffer):
    excel_data = pd.ExcelFile(file_path_or_buffer)
    sheet_names = excel_data.sheet_names
    
    # Dynamická kontrola názvu hárku pre lokácie
    loc_sheet = 'Locations' if 'Locations' in sheet_names else 'Location'
    
    df_sku_aktual = pd.read_excel(excel_data, sheet_name='SKU aktuál')
    df_location = pd.read_excel(excel_data, sheet_name=loc_sheet)
    df_produkty = pd.read_excel(excel_data, sheet_name='Produkty')
    return df_sku_aktual, df_location, df_produkty

st.sidebar.header("📁 Správa dát")
uploaded_file = st.sidebar.file_uploader("Nahraj vlastný Excel (voliteľné)", type=["xlsx", "xls"])

df_sku_aktual, df_location, df_produkty = None, None, None

# Načítanie dát
if uploaded_file is not None:
    try:
        df_sku_aktual, df_location, df_produkty = load_data_from_excel(uploaded_file)
        st.sidebar.success("✅ Načítaný nový nahraný súbor!")
    except Exception as e:
        st.sidebar.error(f"Chyba pri čítaní nahraného súboru: {e}")
        st.stop()
elif os.path.exists(DEFAULT_EXCEL_PATH):
    try:
        df_sku_aktual, df_location, df_produkty = load_data_from_excel(DEFAULT_EXCEL_PATH)
        st.sidebar.info("ℹ️ Používajú sa predvolené dáta zo súboru `data.xlsx`")
    except Exception as e:
        st.sidebar.error(f"Chyba pri čítaní `data.xlsx`: {e}")
        st.stop()
else:
    st.error(f"❌ Súbor `{DEFAULT_EXCEL_PATH}` sa nenašiel v repozitári a nebol nahraný žiaden súbor.")
    st.stop()


# --- LOGIKA ZASKLADŇOVANIA ---
def find_best_location(selected_produkt, qty, df_sku_aktual, df_location, df_produkty):
    # 1. Parameter produktu z hárku Produkty
    prod_row = df_produkty[df_produkty['Produkt'] == selected_produkt]
    if prod_row.empty:
        return None, "Produkt nebol nájdený v hárku 'Produkty'."
    
    prod_row = prod_row.iloc[0]
    
    stohovatelnost = prod_row.get('Stohovateľnosť', 1)
    if pd.isna(stohovatelnost) or stohovatelnost < 1:
        stohovatelnost = 1

    # 2. Výpočet potrieb pre stohovanie
    potrebne_stlpce = math.ceil(qty / stohovatelnost)
    
    # 3. Zistenie obsadenosti lokácií z 'SKU aktuál'
    obsadenost_lokacii = df_sku_aktual.groupby('Lokace').agg({
        'Množství': 'sum',
        'Produkt': list
    }).reset_index()

    # Identifikácia názvu stĺpca pre lokáciu v tabuľke lokácií (Názov lokácie vs Lokácie vs Location)
    loc_col = 'Názov lokácie' if 'Názov lokácie' in df_location.columns else df_location.columns[0]

    # 4. Spojenie lokácií s ich aktuálnym stavom
    df_loc_merged = pd.merge(
        df_location, 
        obsadenost_lokacii, 
        left_on=loc_col, 
        right_on='Lokace', 
        how='left'
    )
    df_loc_merged['Množství'] = df_loc_merged['Množství'].fillna(0)
    
    # 5. Pravidlo KONSOLIDÁCIE
    def has_same_sku(sku_list):
        if isinstance(sku_list, list):
            return selected_produkt in sku_list
        return False
        
    df_loc_merged['Rovnake_SKU_Pritomne'] = df_loc_merged['Produkt'].apply(has_same_sku)

    # 6. Prioritizácia kandidátov (1. Konsolidácia, 2. Najmenej obsadené)
    candidates = df_loc_merged.sort_values(
        by=['Rovnake_SKU_Pritomne', 'Množství'], 
        ascending=[False, True]
    )

    if candidates.empty:
        return None, "Nenašli sa žiadne dostupné lokácie."

    best_loc = candidates.iloc[0]
    
    reason = "Lokácia vybraná na základe "
    if best_loc['Rovnake_SKU_Pritomne']:
        reason += "konsolidácie (rovnaký produkt sa tu už nachádza)."
    else:
        reason += "dostupnej voľnej kapacity."

    return best_loc[loc_col], reason


# --- UŽÍVATEĽSKÉ ROZHRANIE ---
tab1, tab2 = st.tabs(["🎯 Plánovač Zaskladnenia", "📊 Prehľad Dát"])

with tab1:
    st.subheader("Vstup pre Príjem Tovaru")
    
    col_input1, col_input2 = st.columns(2)
    
    with col_input1:
        seznam_produktov = df_produkty['Produkt'].dropna().unique().tolist()
        selected_produkt = st.selectbox("Vyber Produkt (Kód)", options=seznam_produktov)
        
    with col_input2:
        qty_input = st.number_input("Počet kusov na zaskladnenie", min_value=1, value=1, step=1)

    if selected_produkt:
        prod_info = df_produkty[df_produkty['Produkt'] == selected_produkt].iloc[0]
        
        st.markdown("---")
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        col_d1.metric("Názov produktu", str(prod_info.get('Název produktu', 'N/A')))
        col_d2.metric("Predaje / mesiac", int(prod_info.get('Prodeje měsíc', 0)) if not pd.isna(prod_info.get('Prodeje měsíc')) else 0)
        col_d3.metric("Stohovateľnosť", int(prod_info.get('Stohovateľnosť', 1)) if not pd.isna(prod_info.get('Stohovateľnosť')) else 1)
        col_d4.metric("GeoSize", str(prod_info.get('Rozměr produktu (GeoSize)', 'N/A')))
        st.markdown("---")

    if st.button("🚀 Vypočítať optimálnu lokáciu", type="primary"):
        target_loc, reason = find_best_location(
            selected_produkt, 
            qty_input, 
            df_sku_aktual, 
            df_location, 
            df_produkty
        )
        
        if target_loc:
            st.success(f"📍 **Odporúčaná zaskladňovacia lokácia: `{target_loc}`**")
            st.info(f"💡 **Dôvod výberu:** {reason}")
        else:
            st.error(f"❌ Chyba: {reason}")

with tab2:
    st.subheader("Náhľad na dáta v systéme")
    subtab1, subtab2, subtab3 = st.tabs(["SKU aktuál", "Locations", "Produkty"])
    
    with subtab1:
        st.dataframe(df_sku_aktual, use_container_width=True)
    with subtab2:
        st.dataframe(df_location, use_container_width=True)
    with subtab3:
        st.dataframe(df_produkty, use_container_width=True)
