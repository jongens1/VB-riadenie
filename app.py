"""Run with `streamlit run app.py`; importing this module does not launch the UI."""
import io
from pathlib import Path
from zipfile import BadZipFile
import pandas as pd
from warehouse import (
    ALLOCATION_COLUMNS, MOVE_COLUMNS, resolve_columns, normalize_key,
    validate_input_data, get_product_info, calculate_location_capacity,
    build_location_occupancy, plan_putaway, analyze_defragmentation,
)


def load_data_from_excel(source):
    with pd.ExcelFile(source) as workbook:
        loc_sheet = next((s for s in ('Locations', 'Location') if s in workbook.sheet_names), None)
        if loc_sheet is None or not {'SKU aktuál', 'Produkty'}.issubset(workbook.sheet_names):
            raise ValueError('Excel musí obsahovať hárky SKU aktuál, Locations alebo Location a Produkty.')
        return tuple(pd.read_excel(workbook, sheet_name=s) for s in ('SKU aktuál', loc_sheet, 'Produkty'))


def main():
    import streamlit as st

    st.set_page_config(page_title='VB · Riadenie skladu', page_icon='📦', layout='wide')
    st.title('Riadenie skladu · Veľká Biela')
    st.caption('Naplánujte príjem, oddeľte nadzásobu a uvoľnite lokácie konsolidáciou.')
    with st.sidebar:
        st.header('Dáta a pravidlá')
        uploaded = st.file_uploader('Excel so skladovými dátami', type=['xlsx'])
        days = st.slider('Cieľová zásoba v dňoch', 7, 90, 30)
        mixed = st.checkbox('Povoliť miešanie SKU', value=False)
        if mixed:
            st.warning('Kapacita zmiešaných lokácií je odhad podľa podielu obsadenia SKU. Pred presunom overte fyzické uloženie.')
        st.caption('Rozmery sú v cm. Všetka vstupná zásoba sa počíta do primáru; SWAP sa v zdrojových dátach osobitne nerozlišuje.')
    try:
        source = uploaded.getvalue() if uploaded else Path(__file__).with_name('data.xlsx').read_bytes()

        @st.cache_data
        def read_workbook(data):
            return load_data_from_excel(io.BytesIO(data))

        stock, locations, products = read_workbook(source)
    except (OSError, ValueError, KeyError, ImportError, BadZipFile) as exc:
        st.error(f'Excel sa nepodarilo načítať: {exc}')
        st.stop()
    errors, warnings = validate_input_data(stock, locations, products)
    for message in errors:
        st.error(message)
    for message in warnings:
        st.warning(message)
    if errors:
        st.info('Opravte vstupné dáta a nahrajte súbor znova. Výpočty sú pozastavené.')
        st.stop()
    st.caption(f"Zdroj: {uploaded.name if uploaded else 'data.xlsx'} · {len(products):,} produktov · {len(locations):,} lokácií")
    putaway_tab, defrag_tab, data_tab = st.tabs(['Príjem a SWAP', 'Uvoľnenie lokácií', 'Vstupné dáta'])
    with putaway_tab:
        pc = resolve_columns(products)
        keys = products[pc['sku']].map(normalize_key).tolist()
        names = dict(zip(keys, products[pc['name']].astype(str))) if pc['name'] else {}
        left, right = st.columns([3, 1])
        sku = left.selectbox('Produkt', keys, format_func=lambda k: f'{k} · {names.get(k, k)}')
        quantity = right.number_input('Príjem (ks)', min_value=1, value=20, step=1)
        info = get_product_info(sku, products, stock)
        st.caption(f'Predaj: {info.monthly_sales:g} ks/mesiac · Rozmery: {info.width:g} × {info.depth:g} × {info.height:g} cm · Stohovanie: {info.stackability}')
        for message in info.warnings:
            st.warning(message)
        if st.button('Vypočítať plán príjmu', type='primary'):
            allocations, summary = plan_putaway(sku, quantity, days, stock, locations, products, mixed)
            for message in summary['warnings']:
                if message not in warnings and message not in info.warnings:
                    st.warning(message)
            a, b, c, d = st.columns(4)
            a.metric('Aktuálna zásoba', f"{summary['current_stock']} ks")
            b.metric('Cieľ primáru', f"{summary['target_stock_needed']} ks" if summary['target_stock_needed'] is not None else '1 lokácia')
            c.metric('Do primáru', f"{allocations.loc[allocations.type == 'PRIMARY', 'quantity'].sum()} ks")
            d.metric('Do SWAPu', f"{allocations.loc[allocations.type == 'SWAP', 'quantity'].sum()} ks")
            display = allocations.rename(columns=dict(zip(ALLOCATION_COLUMNS, ['Typ', 'Lokácia', 'Počet ks', 'Voľná kapacita pred', 'Kapacita', 'Dôvod'])))
            display['Typ'] = display['Typ'].map({'PRIMARY': 'Primár', 'SWAP': 'SWAP / nadzásoba'})
            st.dataframe(display, hide_index=True, width='stretch')
            st.download_button('Stiahnuť plán CSV', display.to_csv(index=False).encode('utf-8-sig'), 'plan-prijmu.csv', 'text/csv', on_click='ignore')
    with defrag_tab:
        st.subheader('Konsolidácia rozdrobených SKU')
        st.write('Plán zlúči celé SKU do jednej existujúcej lokácie, ak kapacita a pravidlá miešania dovolia. Presuny vykonávajte v poradí tabuľky.')
        if st.button('Analyzovať možnosti presunov'):
            moves, freed, fragmented = analyze_defragmentation(stock, locations, products, mixed)
            extra_warnings = [m for m in moves.attrs.get('warnings', []) if m not in warnings]
            if extra_warnings:
                st.warning(f'Pri konsolidácii sa použili odhady alebo nejednotné rozmery ({len(extra_warnings)} upozornení).')
                with st.expander('Podrobnosti použitých rozmerov'):
                    for message in extra_warnings:
                        st.warning(message)
            a, b = st.columns(2)
            a.metric('Rozdrobené SKU', fragmented)
            b.metric('Uvoľnené lokácie', freed)
            if moves.empty:
                st.info('Pri aktuálnych pravidlách nebola nájdená konsolidácia do jednej existujúcej lokácie.')
            else:
                display = moves.rename(columns=dict(zip(MOVE_COLUMNS, ['SKU', 'Produkt', 'Zdroj', 'Presunúť ks', 'Cieľ', 'Uvoľní zdroj'])))
                st.dataframe(display, hide_index=True, width='stretch')
                st.download_button('Stiahnuť presuny CSV', display.to_csv(index=False).encode('utf-8-sig'), 'presuny.csv', 'text/csv', on_click='ignore')
    with data_tab:
        for title, frame in (('SKU aktuál', stock), ('Locations', locations), ('Produkty', products)):
            with st.expander(f'{title} · {len(frame):,} riadkov'):
                st.dataframe(frame, hide_index=True, width='stretch')
    st.caption('Výstupy sú návrhy. Potvrdené skladové pohyby zapíšte do zdrojového systému a načítajte aktuálny Excel.')


if __name__ == '__main__':
    main()
