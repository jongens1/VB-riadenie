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
st.caption("Interný nástroj pre optimalizáciu ukladania produktov na lokácie s kontrolou kapacity")

DEFAULT_EXCEL_PATH = "data.xlsx"

# --- HELPER PRE INTEGRITU STĹPCOV ---
def get_column_name(df, candidate_names):
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


# --- VÝPOČET GEOMETRICKEJ KAPACITY LOKÁCIE ---
def calculate_location_capacity(loc_w, loc_d, loc_h, prod_w, prod_d, prod_h, stackability):
    """Vypočíta maximálny počet kusov daného produktu, ktorý sa vojde na lokáciu."""
    if any(v <= 0 or pd.isna(v) for v in [loc_w, loc_d, loc_h, prod_w, prod_d, prod_h]):
        return 4 # Výpredajová / záložná hodnota ak chýbajú rozmery
    
    # 1. Výšková kapacita (Stohovateľnosť vs Výška lokácie)
    max_stack_by_height = int(loc_h // prod_h)
    if max_stack_by_height == 0:
        return 0 # Produkt sa výškovo nevojde
    
    eff_stackability = min(int(stackability), max_stack_by_height)
    
    # 2. Pôdorysné rozloženie (Možnosť 1: bez rotácie, Možnosť 2: rotácia o 90 deg)
    fit_orient1 = int(loc_w // prod_w) * int(loc_d // prod_d)
    fit_orient2 = int(loc_w // prod_d) * int(loc_d // prod_w)
    
    max_floor_units = max(fit_orient1, fit_orient2)
    
    # 3. Celková max kapacita
    return max_floor_units * eff_stackability


# --- LOGIKA ZASKLADŇOVANIA ---
def find_best_locations(selected_produkt, total_qty_to_store, df_sku_aktual, df_location, df_produkty):
    qty_col_sku = get_column_name(df_sku_aktual, ['Množstvo', 'Množství', 'Qty', 'Počet'])
    loc_col_sku = get_column_name(df_sku_aktual, ['Lokace', 'Lokácia', 'Location', 'Názov lokácie'])
    prod_col_sku = get_column_name(df_sku_aktual, ['Produkt', 'SKU', 'Product'])

    loc_col_loc = get_column_name(df_location, ['Názov lokácie', 'Lokace', 'Lokácia', 'Location']) or df_location.columns[0]
    loc_w_col = get_column_name(df_location, ['Šířka (cm)', 'Šírka (cm)', 'Šírka', 'Šířka'])
    loc_d_col = get_column_name(df_location, ['Hloubka (cm)', 'Hĺbka (cm)', 'Hloubka', 'Hĺbka'])
    loc_h_col = get_column_name(df_location, ['Výška (cm)', 'Výška'])

    prod_col_prod = get_column_name(df_produkty, ['Produkt', 'SKU', 'Product'])
    prod_row = df_produkty[df_produkty[prod_col_prod] == selected_produkt]
    
    if prod_row.empty:
        return [], "Produkt nebol nájdený v hárku 'Produkty'."
    
    prod_row = prod_row.iloc[0]
    stohovatelnost = prod_row.get('Stohovateľnosť', 1)
    if pd.isna(stohovatelnost) or stohovatelnost < 1:
        stohovatelnost = 1

    # Získanie rozmerov produktu
    sku_rows = df_sku_aktual[df_sku_aktual[prod_col_sku] == selected_produkt]
    if not sku_rows.empty:
        prod_h = sku_rows.get('Výška', pd.Series([85])).iloc[0]
        prod_w = sku_rows.get('Šírka', pd.Series([60])).iloc[0]
        prod_d = sku_rows.get('Hloubka', pd.Series([60])).iloc[0]
    else:
        prod_h, prod_w, prod_d = 85, 60, 60 # Výchozie rozmery v cm

    # Agregácia obsadenosti lokácií
    obsadenost_lokacii = df_sku_aktual.groupby(loc_col_sku).agg({
        qty_col_sku: 'sum',
        prod_col_sku: list
    }).reset_index()

    # Mergnutie dát o lokáciách
    df_loc_merged = pd.merge(
        df_location, 
        obsadenost_lokacii, 
        left_on=loc_col_loc, 
        right_on=loc_col_sku, 
        how='left'
    )
    df_loc_merged[qty_col_sku] = df_loc_merged[qty_col_sku].fillna(0)
    
    # Výpočet kapacity pre každú lokáciu
    def calc_cap(row):
        l_w = row.get(loc_w_col, 120)
        l_d = row.get(loc_d_col, 80)
        l_h = row.get(loc_h_col, 200)
        return calculate_location_capacity(l_w, l_d, l_h, prod_w, prod_d, prod_h, stohovatelnost)

    df_loc_merged['Max_Kapacita'] = df_loc_merged.apply(calc_cap, axis=1)
    df_loc_merged['Volna_Kapacita'] = df_loc_merged['Max_Kapacita'] - df_loc_merged[qty_col_sku]
    df_loc_merged['Volna_Kapacita'] = df_loc_merged['Volna_Kapacita'].apply(lambda x: max(0, x))

    # Pravidlo KONSOLIDÁCIE
    def has_same_sku(sku_list):
        if isinstance(sku_list, list):
            return selected_produkt in sku_list
        return False
        
    df_loc_merged['Rovnake_SKU_Pritomne'] = df_loc_merged[prod_col_sku].apply(has_same_sku)

    # Vyradíme lokácie bez voľnej kapacity
    df_available = df_loc_merged[df_loc_merged['Volna_Kapacita'] > 0].copy()

    if df_available.empty:
        return [], "V sklade nezostali žiadne lokácie s voľnou kapacitou pre tento produkt!"

    # Zotriedenie: 1. Konsolidácia, 2. Najviac voľnej kapacity
    candidates = df_available.sort_values(
        by=['Rovnake_SKU_Pritomne', 'Volna_Kapacita'], 
        ascending=[False, False]
    )

    # Rozdelenie kusov na lokácie (Split allocation)
    allocations = []
    remaining_qty = total_qty_to_store

    for idx, row in candidates.iterrows():
        if remaining_qty <= 0:
            break
            
        alloc_qty = min(remaining_qty, int(row['Volna_Kapacita']))
        
        reason = "Konsolidácia (doplnenie na existujúcu pozíciu)" if row['Rovnake_SKU_Pritomne'] else "Voľná kapacita lokácie"
        
        allocations.append({
            'Location': row[loc_col_loc],
            'Allocated_Qty': alloc_qty,
            'Free_Before': int(row['Volna_Kapacita']),
            'Max_Cap': int(row['Max_Kapacita']),
            'Reason': reason
        })
        
        remaining_qty -= alloc_qty

    if remaining_qty > 0:
        return allocations, f"⚠️ Upozornenie: Podarilo sa naplánovať len {total_qty_to_store - remaining_qty} ks z {total_qty_to_store} ks. Sklad je plný!"

    return allocations, "Úspešne naplánované celkové množstvo."


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

    if st.button("🚀 Vypočítať optimálne lokácie", type="primary"):
        allocations, status_msg = find_best_locations(
            selected_produkt, 
            qty_input, 
            df_sku_aktual, 
            df_location, 
            df_produkty
        )
        
        if "⚠️" in status_msg:
            st.warning(status_msg)
        elif allocations:
            st.success(f"✅ {status_msg}")

        if allocations:
            st.subheader("📍 Plán zaskladnenia po lokáciách:")
            alloc_df = pd.DataFrame(allocations)
            alloc_df.columns = ["Lokácia", "Počet ks na zaskladnenie", "Voľná kapacita pred", "Max Kapacita lokácie", "Dôvod výberu"]
            st.table(alloc_df)

with tab2:
    st.subheader("Náhľad na dáta v systéme")
    subtab1, subtab2, subtab3 = st.tabs(["SKU aktuál", "Locations / Location", "Produkty"])
    
    with subtab1:
        st.dataframe(df_sku_aktual, use_container_width=True)
    with subtab2:
        st.dataframe(df_location, use_container_width=True)
    with subtab3:
        st.dataframe(df_produkty, use_container_width=True)
