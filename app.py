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
st.caption("Aplikácia pre riadenie primárnych zásob, SWAPu a defragmentáciu skladu")

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

st.sidebar.header("📁 Správa dát & Nastavenia")
uploaded_file = st.sidebar.file_uploader("Nahraj vlastný Excel (voliteľné)", type=["xlsx", "xls"])

target_days = st.sidebar.slider(
    "⏱️ Cieľová zásoba pre bežné produkty (dni)", 
    min_value=7, 
    max_value=90, 
    value=30, 
    step=1,
    help="Koľko dní predaja chceme držať na primárnych lokáciách pre štandardné produkty."
)

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
    if any(v <= 0 or pd.isna(v) for v in [loc_w, loc_d, loc_h, prod_w, prod_d, prod_h]):
        return 4
    
    max_stack_by_height = int(loc_h // prod_h)
    if max_stack_by_height == 0:
        return 0
    
    eff_stackability = min(int(stackability), max_stack_by_height)
    
    fit_orient1 = int(loc_w // prod_w) * int(loc_d // prod_d)
    fit_orient2 = int(loc_w // prod_d) * int(loc_d // prod_w)
    
    max_floor_units = max(fit_orient1, fit_orient2)
    return max_floor_units * eff_stackability


# --- LOGIKA ZASKLADŇOVANIA ---
def find_best_locations_with_swap(selected_produkt, total_qty_to_store, days_target, df_sku_aktual, df_location, df_produkty):
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
        return [], {}, "Produkt nebol nájdený v hárku 'Produkty'."
    
    prod_row = prod_row.iloc[0]
    
    stoh_col = get_column_name(df_produkty, ['Stohovatelnost', 'Stohovateľnosť', 'Stackability', 'Stohovanie'])
    stoh_raw = prod_row.get(stoh_col, 1) if stoh_col else 1
    try:
        stohovatelnost = int(float(stoh_raw)) if (not pd.isna(stoh_raw) and float(stoh_raw) >= 1) else 1
    except (ValueError, TypeError):
        stohovatelnost = 1

    monthly_sales = prod_row.get('Prodeje měsíc', 0)
    if pd.isna(monthly_sales) or monthly_sales < 0:
        monthly_sales = 0
        
    is_zero_sales = (monthly_sales == 0)

    sku_rows = df_sku_aktual[df_sku_aktual[prod_col_sku] == selected_produkt]
    if not sku_rows.empty:
        prod_h = sku_rows.get('Výška', pd.Series([85])).iloc[0]
        prod_w = sku_rows.get('Šírka', pd.Series([60])).iloc[0]
        prod_d = sku_rows.get('Hloubka', pd.Series([60])).iloc[0]
    else:
        prod_h, prod_w, prod_d = 85, 60, 60

    current_stock = sku_rows[qty_col_sku].sum() if not sku_rows.empty else 0

    obsadenost_lokacii = df_sku_aktual.groupby(loc_col_sku).agg({
        qty_col_sku: 'sum',
        prod_col_sku: list
    }).reset_index()

    df_loc_merged = pd.merge(
        df_location, 
        obsadenost_lokacii, 
        left_on=loc_col_loc, 
        right_on=loc_col_sku, 
        how='left'
    )
    df_loc_merged[qty_col_sku] = df_loc_merged[qty_col_sku].fillna(0)
    
    def calc_cap(row):
        l_w = row.get(loc_w_col, 120)
        l_d = row.get(loc_d_col, 80)
        l_h = row.get(loc_h_col, 200)
        return calculate_location_capacity(l_w, l_d, l_h, prod_w, prod_d, prod_h, stohovatelnost)

    df_loc_merged['Max_Kapacita'] = df_loc_merged.apply(calc_cap, axis=1)
    df_loc_merged['Volna_Kapacita'] = df_loc_merged['Max_Kapacita'] - df_loc_merged[qty_col_sku]
    df_loc_merged['Volna_Kapacita'] = df_loc_merged['Volna_Kapacita'].apply(lambda x: max(0, x))

    def has_same_sku(sku_list):
        if isinstance(sku_list, list):
            return selected_produkt in sku_list
        return False
        
    df_loc_merged['Rovnake_SKU_Pritomne'] = df_loc_merged[prod_col_sku].apply(has_same_sku)
    df_available = df_loc_merged[df_loc_merged['Volna_Kapacita'] > 0].copy()

    candidates = df_available.sort_values(
        by=['Rovnake_SKU_Pritomne', 'Volna_Kapacita'], 
        ascending=[False, False]
    )

    allocations = []
    remaining_inbound = total_qty_to_store

    if is_zero_sales:
        target_stock_needed = "1 Lokácia (Nové SKU)"
        needed_for_target = "Max 1 Lokácia"
        
        has_free_consolidated_loc = any(candidates['Rovnake_SKU_Pritomne']) if not candidates.empty else False
        
        if current_stock > 0 and not has_free_consolidated_loc:
            pass
        elif not candidates.empty:
            row = candidates.iloc[0]
            loc_free_cap = int(row['Volna_Kapacita'])
            qty_to_place = min(remaining_inbound, loc_free_cap)

            reason = "Primárna lokácia (Nové / Bezpredajné SKU - Alokácia 1 lokácie)"
            if row['Rovnake_SKU_Pritomne']:
                reason += " - Konsolidácia"

            allocations.append({
                'Typ': '📍 PRIMÁRNA LOKÁCIA',
                'Location': row[loc_col_loc],
                'Allocated_Qty': qty_to_place,
                'Free_Before': loc_free_cap,
                'Max_Cap': int(row['Max_Kapacita']),
                'Reason': reason
            })

            remaining_inbound -= qty_to_place

    else:
        daily_sales = monthly_sales / 30.0
        target_stock_needed = math.ceil(daily_sales * days_target)
        needed_for_target = max(0, target_stock_needed - current_stock)
        remaining_target_need = needed_for_target

        for idx, row in candidates.iterrows():
            if remaining_inbound <= 0 or remaining_target_need <= 0:
                break

            loc_free_cap = int(row['Volna_Kapacita'])
            qty_to_place = min(remaining_inbound, loc_free_cap)

            reason = f"Primárna lokácia (Pokrytie zásoby na {days_target} dní)"
            if row['Rovnake_SKU_Pritomne']:
                reason += " - Konsolidácia"

            allocations.append({
                'Typ': '📍 PRIMÁRNA LOKÁCIA',
                'Location': row[loc_col_loc],
                'Allocated_Qty': qty_to_place,
                'Free_Before': loc_free_cap,
                'Max_Cap': int(row['Max_Kapacita']),
                'Reason': reason
            })

            remaining_inbound -= qty_to_place
            remaining_target_need = max(0, remaining_target_need - qty_to_place)

    if remaining_inbound > 0:
        swap_reason = "Nadzásoba pre nové/bezpredajné SKU (nad rámec 1 primárnej lokácie)" if is_zero_sales else f"Nadzásoba presahujúca cieľovú zásobu na {days_target} dní"
        
        allocations.append({
            'Typ': '🔄 SWAP / NADZÁSOBA',
            'Location': 'PALETOVÁ ZÓNA / SWAP',
            'Allocated_Qty': remaining_inbound,
            'Free_Before': '-',
            'Max_Cap': '-',
            'Reason': swap_reason
        })

    summary_info = {
        'monthly_sales': int(monthly_sales),
        'is_zero_sales': is_zero_sales,
        'target_days': days_target,
        'target_stock_needed': target_stock_needed,
        'current_stock': int(current_stock),
        'needed_for_target': needed_for_target,
        'stohovatelnost_used': stohovatelnost
    }

    return allocations, summary_info, "Výpočet úspešne dokončený."


# --- LOGIKA DEFRAGMENTÁCIE SKLADU ---
def analyze_defragmentation(df_sku_aktual, df_location, df_produkty):
    qty_col_sku = get_column_name(df_sku_aktual, ['Množstvo', 'Množství', 'Qty', 'Počet'])
    loc_col_sku = get_column_name(df_sku_aktual, ['Lokace', 'Lokácia', 'Location', 'Názov lokácie'])
    prod_col_sku = get_column_name(df_sku_aktual, ['Produkt', 'SKU', 'Product'])

    loc_col_loc = get_column_name(df_location, ['Názov lokácie', 'Lokace', 'Lokácia', 'Location']) or df_location.columns[0]
    loc_w_col = get_column_name(df_location, ['Šířka (cm)', 'Šírka (cm)', 'Šírka', 'Šířka'])
    loc_d_col = get_column_name(df_location, ['Hloubka (cm)', 'Hĺbka (cm)', 'Hloubka', 'Hĺbka'])
    loc_h_col = get_column_name(df_location, ['Výška (cm)', 'Výška'])

    prod_col_prod = get_column_name(df_produkty, ['Produkt', 'SKU', 'Product'])

    # 1. Zistiť produkty, ktoré ležia na viac ako 1 lokácii
    sku_loc_counts = df_sku_aktual.groupby(prod_col_sku)[loc_col_sku].nunique()
    multi_loc_skus = sku_loc_counts[sku_loc_counts > 1].index.tolist()

    moves = []
    freed_locations_count = 0

    for sku in multi_loc_skus:
        sku_rows = df_sku_aktual[df_sku_aktual[prod_col_sku] == sku]
        total_qty = sku_rows[qty_col_sku].sum()

        # Názov produktu
        prod_info = df_produkty[df_produkty[prod_col_prod] == sku]
        prod_name = prod_info['Název produktu'].iloc[0] if not prod_info.empty and 'Název produktu' in prod_info.columns else str(sku)

        # Stohovateľnosť a rozmery
        stoh_col = get_column_name(df_produkty, ['Stohovatelnost', 'Stohovateľnosť', 'Stackability'])
        stoh_raw = prod_info[stoh_col].iloc[0] if (not prod_info.empty and stoh_col) else 1
        try:
            stohovatelnost = int(float(stoh_raw)) if (not pd.isna(stoh_raw) and float(stoh_raw) >= 1) else 1
        except (ValueError, TypeError):
            stohovatelnost = 1

        prod_h = sku_rows.get('Výška', pd.Series([85])).iloc[0]
        prod_w = sku_rows.get('Šírka', pd.Series([60])).iloc[0]
        prod_d = sku_rows.get('Hloubka', pd.Series([60])).iloc[0]

        # Súčasné lokácie pre toto SKU
        current_locs = sku_rows[[loc_col_sku, qty_col_sku]].copy()

        # Vypočítame kapacitu každej z lokácií, kde tovar momentálne leží
        loc_capacities = {}
        for l_id in current_locs[loc_col_sku]:
            l_row = df_location[df_location[loc_col_loc] == l_id]
            if not l_row.empty:
                l_row = l_row.iloc[0]
                cap = calculate_location_capacity(
                    l_row.get(loc_w_col, 120), l_row.get(loc_d_col, 80), l_row.get(loc_h_col, 200),
                    prod_w, prod_d, prod_h, stohovatelnost
                )
            else:
                cap = 10
            loc_capacities[l_id] = cap

        current_locs['Max_Cap'] = current_locs[loc_col_sku].map(loc_capacities)

        # SKÚŠKA: Vojde sa CELÉ celkové množstvo na JEDNU z existujúcich lokácií?
        target_loc_row = current_locs[current_locs['Max_Cap'] >= total_qty]

        if not target_loc_row.empty:
            # DÁ SA KONSOLIDOVAŤ NA EXISTUJÚCU LOKÁCIU
            target_loc = target_loc_row.sort_values(by=qty_col_sku, ascending=False).iloc[0][loc_col_sku]
            sources = current_locs[current_locs[loc_col_sku] != target_loc]

            for idx, s_row in sources.iterrows():
                moves.append({
                    'Produkt (SKU)': sku,
                    'Názov produktu': prod_name,
                    'Zdrojová lokácia (Odtiaľto)': s_row[loc_col_sku],
                    'Presunúť (ks)': int(s_row[qty_col_sku]),
                    'Cieľová lokácia (Sem)': target_loc,
                    'Prínos / Výsledok': f"🧹 Úplné uvoľnenie lokácie {s_row[loc_col_sku]}"
                })
                freed_locations_count += 1

    return pd.DataFrame(moves), freed_locations_count, len(multi_loc_skus)


# --- UŽÍVATEĽSKÉ ROZHRANIE ---
tab1, tab2, tab3 = st.tabs(["🎯 Plánovač Zaskladnenia & SWAP", "🧹 Defragmentácia Skladu", "📊 Prehľad Dát"])

with tab1:
    st.subheader("Vstup pre Príjem Tovaru")
    
    col_input1, col_input2 = st.columns(2)
    prod_col_prod = get_column_name(df_produkty, ['Produkt', 'SKU', 'Product'])
    
    with col_input1:
        seznam_produktov = df_produkty[prod_col_prod].dropna().unique().tolist()
        selected_produkt = st.selectbox("Vyber Produkt (Kód)", options=seznam_produktov)
        
    with col_input2:
        qty_input = st.number_input("Počet kusov na príjme", min_value=1, value=20, step=1)

    if selected_produkt:
        prod_info = df_produkty[df_produkty[prod_col_prod] == selected_produkt].iloc[0]
        
        stoh_col = get_column_name(df_produkty, ['Stohovatelnost', 'Stohovateľnosť', 'Stackability', 'Stohovanie'])
        stoh_raw = prod_info.get(stoh_col, 1) if stoh_col else 1
        try:
            stoh_display = int(float(stoh_raw)) if (not pd.isna(stoh_raw) and float(stoh_raw) >= 1) else 1
        except (ValueError, TypeError):
            stoh_display = 1

        st.markdown("---")
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        col_d1.metric("Názov produktu", str(prod_info.get('Název produktu', 'N/A')))
        
        prodeje_val = prod_info.get('Prodeje měsíc', 0)
        sales_display = int(prodeje_val) if not pd.isna(prodeje_val) else 0
        col_d2.metric("Predaje / mesiac", f"{sales_display} ks" if sales_display > 0 else "0 ks (NOVÝ/BEZ PREDAJOV)")
        
        col_d3.metric("Stohovateľnosť", f"{stoh_display} ks nad sebou")
        
        geosize_val = prod_info.get('Rozměr produktu (GeoSize)', prod_info.get('Geo Size', 'N/A'))
        col_d4.metric("GeoSize", str(geosize_val))
        st.markdown("---")

    if st.button("🚀 Vypočítať rozdelenie (Zaskladnenie vs SWAP)", type="primary"):
        allocations, summary, status_msg = find_best_locations_with_swap(
            selected_produkt, 
            qty_input, 
            target_days,
            df_sku_aktual, 
            df_location, 
            df_produkty
        )
        
        st.subheader("📊 Analýza potrieb zásoby")
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("Predaj za mesiac", f"{summary['monthly_sales']} ks")
        
        if summary['is_zero_sales']:
            col_s2.metric("Režim produktu", "🆕 NOVÝ / BEZ PREDAJOV")
            col_s3.metric("Aktuálne na sklade", f"{summary['current_stock']} ks")
            col_s4.metric("Pravidlo alokácie", f"Max 1 lokácia (Stohovateľnosť: {summary['stohovatelnost_used']})")
        else:
            col_s2.metric(f"Cieľová zásoba ({target_days} dní)", f"{summary['target_stock_needed']} ks")
            col_s3.metric("Aktuálne na sklade", f"{summary['current_stock']} ks")
            col_s4.metric("Chýba do primárnej zásoby", f"{summary['needed_for_target']} ks")

        st.markdown("---")
        st.subheader("📍 Návrh Zaskladnenia a SWAPu:")
        
        alloc_df = pd.DataFrame(allocations)
        alloc_df.columns = ["Typ uloženia", "Lokácia", "Počet ks", "Voľná kap. pred", "Max Kapacita", "Dôvod / Poznámka"]
        
        st.dataframe(alloc_df, use_container_width=True)

with tab2:
    st.subheader("🧹 Návrhy na Defragmentáciu & Zoskupenie Zásob")
    st.caption("Systém vyhodnocuje rozdrobené produkty na viacero lokáciách a navrhuje interné presuny na uvoľnenie lokácií.")
    
    df_moves, freed_locs_cnt, multi_sku_cnt = analyze_defragmentation(df_sku_aktual, df_location, df_produkty)

    col_m1, col_m2 = st.columns(2)
    col_m1.metric("Počet rozdrobených SKU (vloženie na viac lokáciách)", multi_sku_cnt)
    col_m2.metric("Možných uvoľnených lokácií", freed_locs_cnt, delta=f"+{freed_locs_cnt} voľných lokácií", delta_color="normal")

    st.markdown("---")
    
    if not df_moves.empty:
        st.subheader("📋 Zoznam odporúčaných skladových pohybov:")
        st.dataframe(df_moves, use_container_width=True)
    else:
        st.success("🎉 Sklad je v optimálnom stave! Nenahlásené žiadne roztrieštené produkty, ktoré by sa dali jednoducho zlúčiť.")

with tab3:
    st.subheader("Náhľad na dáta v systéme")
    subtab1, subtab2, subtab3 = st.tabs(["SKU aktuál", "Locations / Location", "Produkty"])
    
    with subtab1:
        st.dataframe(df_sku_aktual, use_container_width=True)
    with subtab2:
        st.dataframe(df_location, use_container_width=True)
    with subtab3:
        st.dataframe(df_produkty, use_container_width=True)
