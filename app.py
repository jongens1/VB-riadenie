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

# Názov predvoleného súboru
DEFAULT_EXCEL_PATH = "data.xlsx"

# --- HELPER PRE INTEGRITU STĹPCOV ---
def get_column_name(df, candidate_names):
    """Vráti prvý existujúci názov stĺpca zo zoznamu kandidátov."""
    for name in candidate_names:
        if name in df.columns:
            return name
    return None

# --- NAHRATIE A SPRACOVANIE DÁT ---
@st.cache_data
def load_data_from_excel(file_path_or_buffer):
    excel_data = pd.ExcelFile(file_path_or_buffer)
    sheet_names = excel_data.sheet_names
    
    loc_sheet = 'Locations' if 'Locations' in sheet_names else ('Location' if 'Location' in sheet_names else sheet_names[1])
    
    df_sku_aktual = pd.read_excel(excel_data, sheet_name='SKU aktuál')
    df_location = pd.read_excel(excel_data, sheet_name=loc_sheet)
    df_produkty = pd.read_excel(excel_data, sheet_name='Produkty')
    return df_sku_aktual, df_location, df_produkty

st.sidebar.header("📁 Správa dát")
uploaded_file = st.sidebar.file_uploader("Nahraj vlastný Excel (voliteľné)", type=["xlsx", "xls"])

df_sku_aktual, df_location, df_produkty = None, None, None

if uploaded_file is not None:
    try:
        df_sku_aktual, df_location, df_produkty = load_data_from_excel(uploaded_file)
        st.sidebar.success("✅ Načítaný ručne nahraný súbor!")
    except Exception as e:
        st.sidebar.error(f"Chyba pri čítaní nahraného súboru: {e}")
        st.stop()
elif os.path.exists(DEFAULT_EXCEL_PATH):
    try:
        df_sku_aktual, df_location, df_produkty = load_data_from_excel(DEFAULT_EXCEL_PATH)
        st.sidebar.info("ℹ️ Používajú sa dáta zo súboru `data.xlsx`")
    except Exception as e:
        st.sidebar.error(f"Chyba pri čítaní `data.xlsx`: {e}")
        st.stop()
else:
    st.error(f"❌ Súbor `{DEFAULT_EXCEL_PATH}` sa nenašiel v repozitári.")
    st.stop()


# --- LOGIKA ZASKLADŇOVANIA ---
def find_best_location(selected_produkt, qty, df_sku_aktual, df_location, df_produkty):
    # 1. Identifikácia stĺpcov v 'SKU aktuál' (zohľadňuje Množstvo vs Množství)
    qty_col_sku = get_column_name(df_sku_aktual, ['Množstvo', 'Množství', 'Qty', 'Počet'])
    loc_col_sku = get_column_name(df_sku_aktual, ['Lokace', 'Lokácia', 'Location', 'Názov lokácie'])
    prod_col_sku = get_column_name(df_sku_aktual, ['Produkt', 'SKU', 'Product'])

    if not qty_col_sku or not loc_col_sku:
        return None, f"V hárku 'SKU aktuál' sa nenašli stĺpce pre lokáciu alebo množstvo."

    # 2. Identifikácia stĺpca v 'Locations'
    loc_col_loc = get_column_name(df_location, ['Názov lokácie', 'Lokace', 'Lokácia', 'Location']) or df_location.columns[0]

    # 3. Získanie parametrov produktu z 'Produkty'
    prod_col_prod = get_column_name(df_produkty, ['Produkt', 'SKU', 'Product'])
    prod_row = df_produkty[df_produkty[prod_col_prod] == selected_produkt]
    
    if prod_row.empty:
        return None, "Produkt nebol nájdený v hárku 'Produkty'."
    
    prod_row = prod_row.iloc[0]
    
    stohovatelnost = prod_row.get('Stohovateľnosť', 1)
    if pd.isna(stohovatelnost) or stohovatelnost < 1:
        stohovatelnost = 1

    # 4. Agregácia obsadenosti lokácií
    obsadenost_lokacii = df_sku_aktual.groupby(loc_col_sku).agg({
        qty_col_sku: 'sum',
        prod_col_sku: list
    }).reset_index()

    # 5. Spojenie lokácií s ich stavom
    df_loc_merged = pd.merge(
        df_location, 
        obsadenost_lokacii, 
        left_on=loc_col_loc, 
        right_on=loc_col_sku, 
        how='left'
    )
    df_loc_merged[qty_col_sku] = df_loc_merged[qty_col_sku].fillna(0)
    
    # 6. Pravidlo KONSOLIDÁCIE
    def has_same_sku(sku_list):
        if isinstance(sku_list, list):
            return selected_produkt in sku_list
        return False
        
    df_loc_merged['Rovnake_SKU_Pritomne'] = df_loc_merged[prod_col_sku].apply(has_same_sku)

    # 7. Zotriedenie kandidátov (Konsolidácia -> Najmenej obsadená lokácia)
    candidates = df_loc_merged.sort_values(
        by=['Rovnake_SKU_Pritomne', qty_col_sku], 
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

    return best_loc[loc_col_loc], reason


# --- UŽÍVATEĽSKÉ ROZHRANIE ---
tab1, tab2 = st.tabs(["🎯 Plánovač Zaskladnenia", "📊 Prehľad Dát"])

with tab1:
    st.subheader("Vstup pre Príjem Tovaru")
    
    col_input1, col_input2 = st.columns(2)
    
    prod_col_prod = get_column_name(df_produkty, ['Produkt', 'SKU', 'Product'])
    
    with col_input1:
        seznam_produktov = df_produkty[prod_col_prod].dropna().unique().tolist()
        selected_produkt = st.selectbox("Vyber Produkt (Kód)", options=seznam_produktov)
        
    with col_input2:
        qty_input = st.number_input("Počet kusov na zaskladnenie", min_value=1, value=1, step=1)

    if selected_produkt:
        prod_info = df_produkty[df_produkty[prod_col_prod] == selected_produkt].iloc[0]
        
        st.markdown("---")
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        col_d1.metric("Názov produktu", str(prod_info.get('Název produktu', 'N/A')))
        
        prodeje_val = prod_info.get('Prodeje měsíc', 0)
        col_d2.metric("Predaje / mesiac", int(prodeje_val) if not pd.isna(prodeje_val) else 0)
        
        stoh_val = prod_info.get('Stohovateľnosť', 1)
        col_d3.metric("Stohovateľnosť", int(stoh_val) if not pd.isna(stoh_val) else 1)
        
        geosize_val = prod_info.get('Rozměr produktu (GeoSize)', prod_info.get('Geo Size', 'N/A'))
        col_d4.metric("GeoSize", str(geosize_val))
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
    subtab1, subtab2, subtab3 = st.tabs(["SKU aktuál", "Locations / Location", "Produkty"])
    
    with subtab1:
        st.dataframe(df_sku_aktual, use_container_width=True)
    with subtab2:
        st.dataframe(df_location, use_container_width=True)
    with subtab3:
        st.dataframe(df_produkty, use_container_width=True)
