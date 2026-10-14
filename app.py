"""Streamlit dashboard. Business rules live unchanged in warehouse.py."""
import hashlib
from html import escape
import io
from pathlib import Path
from zipfile import BadZipFile

import pandas as pd
from warehouse import (
    ALLOCATION_COLUMNS, MOVE_COLUMNS, resolve_columns, normalize_key,
    validate_input_data, get_product_info, calculate_location_capacity,
    build_location_occupancy, plan_putaway, analyze_defragmentation,
    exclude_unknown_locations,
)


COLORS = {
    'primary': '#3288F5', 'steel': '#205A99', 'light': '#8BCCFF',
    'background': '#0B1423', 'surface': '#122238', 'text': '#E6F1FF',
    'muted': '#9CB3CD', 'border': '#27415F',
}


def inject_custom_css():
    import streamlit as st
    variables = ';'.join(f'--vb-{name}:{value}' for name, value in COLORS.items())
    st.markdown('<style>:root{' + variables + ';}' + '''
        .stApp {background:var(--vb-background); color:var(--vb-text);}
        .block-container {padding-top:1.4rem; padding-bottom:2rem; max-width:1440px;}
        [data-testid="stSidebar"] {background:#0E1B2E; border-right:1px solid var(--vb-border);}
        [data-testid="stSidebar"] .block-container {padding-top:1.2rem;}
        .vb-hero {padding:1.3rem 1.6rem; margin-bottom:.9rem; border:1px solid var(--vb-border);
          border-radius:18px; background:linear-gradient(115deg,#142C49,#102039 70%,#172F4B);}
        .vb-eyebrow {color:var(--vb-light); font-size:.72rem; font-weight:700; letter-spacing:.16em; text-transform:uppercase;}
        .vb-hero h1 {font-size:clamp(1.5rem,2.4vw,2.15rem); line-height:1.25; padding:.4rem 0; margin:0; color:var(--vb-text);}
        .vb-hero p {color:var(--vb-muted); margin:0; font-size:.95rem;}
        [data-testid="stMetric"] {background:linear-gradient(145deg,#162D48,#112137);
          border:1px solid var(--vb-border); border-radius:14px; padding:.85rem 1rem; min-height:100px;}
        [data-testid="stMetricLabel"] {color:var(--vb-muted); font-size:.8rem;}
        [data-testid="stMetricValue"] {color:var(--vb-light); font-size:1.6rem; font-weight:650;}
        [data-testid="stMetricValue"] > div {overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
        .vb-status {background:#13263D; border:1px solid #25486B; border-left:3px solid var(--vb-primary);
          border-radius:10px; padding:.55rem .85rem; margin:.45rem 0 .7rem; font-size:.85rem; color:#BAD6F5;}
        .vb-status strong {color:var(--vb-text);}
        [data-testid="stAlert"] {border-radius:10px; padding:.55rem .8rem; font-size:.85rem;}
        [data-testid="stAlert"][data-baseweb] {background:#152B44;}
        [data-testid="stExpander"] {border-color:var(--vb-border); border-radius:12px;}
        [data-testid="stDataFrame"] {border:1px solid var(--vb-border); border-radius:10px; overflow:hidden;}
        button[kind="primary"] {background:linear-gradient(100deg,#276BD3,#3288F5);
          border:1px solid #5299F6; color:white; border-radius:10px; font-weight:600;}
        button[kind="primary"]:hover {background:linear-gradient(100deg,#3288F5,#489EFF); border-color:#8BCCFF;}
        button[kind="secondary"] {border-color:var(--vb-border); border-radius:10px;}
        [data-baseweb="tab-list"] {gap:1.2rem; border-bottom:1px solid var(--vb-border);}
        [data-baseweb="tab"][aria-selected="true"] {color:var(--vb-light); font-weight:650;}
        [data-baseweb="tab-highlight"] {background:var(--vb-primary);}
        @media (max-width:700px) {
          .block-container {padding:3.8rem .7rem 1rem;} .vb-hero {padding:1rem;}
          [data-testid="stMetric"] {min-height:80px; padding:.6rem .8rem;}
        }
    </style>''', unsafe_allow_html=True)


def render_header():
    import streamlit as st
    st.markdown('''<header class="vb-hero">
      <div class="vb-eyebrow">VB / Skladový dashboard</div>
      <h1>Riadenie skladu • Veľká Biela</h1>
      <p>Plánovanie príjmu, SWAP zásob a konsolidácia skladových lokácií.</p>
    </header>''', unsafe_allow_html=True)


def render_kpi_cards(items):
    """Use native accessible metrics, with one shared card design."""
    import streamlit as st
    for column, (label, value, help_text) in zip(st.columns(len(items)), items):
        column.metric(label, value, help=help_text)


def render_alert_summary(warnings, ignored_rows=0):
    import streamlit as st
    text = f'Dáta načítané s {len(warnings)} upozorneniami.' if warnings else 'Dáta načítané bez upozornení.'
    if ignored_rows:
        text += f' Vynechané záznamy zásob: {ignored_rows}.'
    st.markdown(f'<div class="vb-status" role="status"><strong>{escape(text)}</strong> '
                'Podrobnosti sú dostupné cez diagnostiku v bočnom paneli.</div>', unsafe_allow_html=True)


def render_diagnostics_panel(warnings, errors=(), title='Diagnostika dát', expanded=False):
    import streamlit as st
    warnings = list(dict.fromkeys(warnings))
    if not warnings and not errors:
        return
    with st.expander(f'{title} · {len(errors)} chýb / {len(warnings)} upozornení', expanded=expanded):
        for message in errors:
            st.error(message)
        # Text rows keep a long diagnostic list compact; warning details remain searchable.
        for message in warnings:
            st.markdown(f'- {escape(message)}')


def _chart_config():
    return {'background': 'transparent', 'view': {'stroke': None},
            'axis': {'labelColor': COLORS['muted'], 'titleColor': COLORS['muted'],
                     'gridColor': COLORS['border'], 'domain': False},
            'legend': {'labelColor': COLORS['text'], 'title': None}}


def render_putaway_chart(allocations):
    import streamlit as st
    data = pd.DataFrame({
        'Uloženie': ['Primárne lokácie', 'SWAP / nadzásoba'],
        'Počet ks': [int(allocations.loc[allocations.type == 'PRIMARY', 'quantity'].sum()),
                     int(allocations.loc[allocations.type == 'SWAP', 'quantity'].sum())],
    })
    # Native Vega-Lite support is bundled with Streamlit; no extra dependencies.
    spec = {
        'height': 245,
        'mark': {'type': 'arc', 'innerRadius': 65, 'outerRadius': 105, 'cornerRadius': 5},
        'encoding': {
            'theta': {'field': 'Počet ks', 'type': 'quantitative', 'stack': True},
            'color': {'field': 'Uloženie', 'type': 'nominal',
                      'scale': {'domain': data['Uloženie'].tolist(), 'range': [COLORS['primary'], COLORS['light']]},
                      'legend': {'orient': 'bottom'}},
            'tooltip': [{'field': 'Uloženie', 'type': 'nominal'}, {'field': 'Počet ks', 'type': 'quantitative'}],
        }, 'config': _chart_config(),
    }
    with st.container(border=True):
        st.subheader('Rozdelenie príjmu')
        st.vega_lite_chart(data, spec, width='stretch')
        total = int(data['Počet ks'].sum())
        primary, swap = data['Počet ks'].tolist()
        st.caption(f'{primary:,} ks do primáru ({primary / total:.0%}) · {swap:,} ks do SWAPu ({swap / total:.0%})')


def render_defrag_chart(fragmented, freed, move_count):
    import streamlit as st
    data = pd.DataFrame({'Ukazovateľ': ['Rozdrobené SKU', 'Uvoľnené lokácie', 'Odporúčané presuny'],
                         'Počet': [fragmented, freed, move_count]})
    with st.container(border=True):
        st.subheader('Výsledok konsolidácie')
        st.vega_lite_chart(data, {
            'height': 170, 'mark': {'type': 'bar', 'cornerRadiusEnd': 5},
            'encoding': {
                'y': {'field': 'Ukazovateľ', 'type': 'nominal', 'sort': data.Ukazovateľ.tolist(), 'title': None},
                'x': {'field': 'Počet', 'type': 'quantitative', 'axis': {'tickMinStep': 1}},
                'color': {'field': 'Ukazovateľ', 'type': 'nominal', 'legend': None,
                          'scale': {'domain': data.Ukazovateľ.tolist(), 'range': [COLORS['steel'], COLORS['primary'], COLORS['light']]}},
                'tooltip': [{'field': 'Ukazovateľ', 'type': 'nominal'}, {'field': 'Počet', 'type': 'quantitative'}],
            }, 'config': _chart_config(),
        }, width='stretch')
        st.caption('Ukazovatele majú rôzne jednotky: SKU, lokácie a jednotlivé presuny.')


def load_data_from_excel(source):
    with pd.ExcelFile(source) as workbook:
        loc_sheet = next((s for s in ('Locations', 'Location') if s in workbook.sheet_names), None)
        if loc_sheet is None or not {'SKU aktuál', 'Produkty'}.issubset(workbook.sheet_names):
            raise ValueError('Excel musí obsahovať hárky SKU aktuál, Locations alebo Location a Produkty.')
        return tuple(pd.read_excel(workbook, sheet_name=s) for s in ('SKU aktuál', loc_sheet, 'Produkty'))


def _collapse_diagnostics():
    import streamlit as st
    st.session_state['show_diagnostics'] = False


def main():
    import streamlit as st

    st.set_page_config(page_title='VB · Riadenie skladu', page_icon='📦', layout='wide')
    inject_custom_css()
    render_header()
    with st.sidebar:
        st.header('Dáta a pravidlá')
        uploaded = st.file_uploader('Excel so skladovými dátami', type=['xlsx'])
        st.caption('Použite hárky SKU aktuál, Locations / Location a Produkty.')
        st.divider()
        days = st.slider('Cieľová zásoba v dňoch', 7, 90, 30)
        mixed = st.checkbox('Povoliť miešanie SKU', value=False)
        if mixed:
            st.caption('Miešanie je povolené. Fyzické uloženie vyžaduje kontrolu; kapacita je odhad.')
        st.divider()
        st.checkbox('Zobraziť diagnostiku dát', key='show_diagnostics', value=False)
        st.caption('Rozmery sú v cm. Vstupná zásoba sa počíta do primáru; SWAP sa v zdroji osobitne nerozlišuje.')
    try:
        source = uploaded.getvalue() if uploaded else Path(__file__).with_name('data.xlsx').read_bytes()

        @st.cache_data
        def read_workbook(data):
            return load_data_from_excel(io.BytesIO(data))

        raw_stock, locations, products = read_workbook(source)
    except (OSError, ValueError, KeyError, ImportError, BadZipFile) as exc:
        st.error(f'Excel sa nepodarilo načítať: {exc}')
        st.stop()
    errors, warnings = validate_input_data(raw_stock, locations, products)
    warnings = list(dict.fromkeys(warnings))
    stock, _ = exclude_unknown_locations(raw_stock, locations)
    source_name = uploaded.name if uploaded else 'data.xlsx'
    source_id = hashlib.sha256(source).hexdigest()
    render_kpi_cards([
        ('Produkty', f'{len(products):,}', 'Počet produktov v zdrojovom hárku.'),
        ('Lokácie', f'{len(locations):,}', 'Počet lokácií v katalógu Locations.'),
        ('Upozornenia v dátach', str(len(warnings)), 'Podrobnosti sprístupníte v bočnom paneli.'),
        ('Zdroj dát', source_name, source_name),
    ])
    if errors:
        st.error(f'Výpočet je pozastavený: {len(errors)} chýb v dátach. Opravte údaje a nahrajte Excel znova.')
        render_diagnostics_panel(warnings, errors, expanded=True)
        st.stop()
    render_alert_summary(warnings, len(raw_stock) - len(stock))
    if st.session_state['show_diagnostics']:
        render_diagnostics_panel(warnings, expanded=True)
        if not warnings:
            st.caption('Kontrola dát neodhalila upozornenia.')
    putaway_tab, defrag_tab, data_tab = st.tabs(['Príjem a SWAP', 'Uvoľnenie lokácií', 'Vstupné dáta'])
    with putaway_tab:
        with st.container(border=True):
            st.subheader('Naplánovať príjem')
            st.caption('Cieľová zásoba spúšťa použitie primáru; vybraná lokácia sa plní do voľnej kapacity.')
            pc = resolve_columns(products)
            keys = products[pc['sku']].map(normalize_key).tolist()
            names = dict(zip(keys, products[pc['name']].astype(str))) if pc['name'] else {}
            left, right = st.columns([3, 1])
            sku = left.selectbox('Produkt', keys, format_func=lambda k: f'{k} · {names.get(k, k)}')
            quantity = right.number_input('Príjem (ks)', min_value=1, value=20, step=1)
            info = get_product_info(sku, products, stock)
            st.caption(f'Predaj: {info.monthly_sales:g} ks/mesiac · Rozmery: {info.width:g} × {info.depth:g} × {info.height:g} cm · Stohovanie: {info.stackability}')
            clicked = st.button('Vypočítať plán príjmu', type='primary', on_click=_collapse_diagnostics)
        signature = (source_id, sku, quantity, days, mixed)
        if clicked:
            with st.spinner('Pripravujem plán príjmu…'):
                allocations, summary = plan_putaway(sku, quantity, days, stock, locations, products, mixed)
            st.session_state['putaway_result'] = (signature, allocations, summary)
        result = st.session_state.get('putaway_result')
        if result and result[0] != signature:
            del st.session_state['putaway_result']
            result = None
        if result:
            _, allocations, summary = result
            primary = allocations[allocations.type == 'PRIMARY']
            swap = int(allocations.loc[allocations.type == 'SWAP', 'quantity'].sum())
            st.subheader('Plán príjmu')
            render_kpi_cards([
                ('Príjem spolu', f'{quantity} ks', 'Súčet primárneho uloženia a SWAPu.'),
                ('Do primáru', f'{int(primary.quantity.sum())} ks', 'Kusy odporúčané do primárnych lokácií.'),
                ('Do SWAPu', f'{swap} ks', 'Kusy odporúčané do paletovej zóny / nadzásoby.'),
                ('Primárne lokácie', str(primary.location.nunique()), 'Počet lokácií použitých v tomto pláne.'),
            ])
            target = f"{summary['target_stock_needed']} ks" if summary['target_stock_needed'] is not None else 'max. 1 lokácia'
            missing = f"{summary['needed_for_target']} ks" if summary['needed_for_target'] is not None else 'pravidlo jednej lokácie'
            st.caption(f"Aktuálna zásoba: {summary['current_stock']} ks · Cieľ primáru: {target} · Horizont: {days} dní · Chýba do cieľa pred príjmom: {missing}")
            if summary['needed_for_target'] is not None and primary.quantity.sum() > summary['needed_for_target']:
                st.caption('Primárna alokácia môže prekročiť cieľ, pretože vybrané lokácie sa plnia do kapacity. Ďalšia lokácia sa už nepoužije.')
            render_putaway_chart(allocations)
            with st.container(border=True):
                st.subheader('Odporúčané uloženie')
                display = allocations.rename(columns=dict(zip(ALLOCATION_COLUMNS, ['Typ', 'Lokácia', 'Počet ks', 'Voľná kapacita pred', 'Kapacita', 'Dôvod'])))
                display['Typ'] = display['Typ'].map({'PRIMARY': 'Primár', 'SWAP': 'SWAP / nadzásoba'})
                for column in ('Voľná kapacita pred', 'Kapacita'):
                    display[column] = display[column].map(lambda value: '—' if pd.isna(value) else str(int(value)))
                st.dataframe(display, hide_index=True, width='stretch')
                st.download_button('Stiahnuť plán CSV', display.to_csv(index=False).encode('utf-8-sig'), 'plan-prijmu.csv', 'text/csv', on_click='ignore')
            render_diagnostics_panel(summary['warnings'], title='Detaily plánu príjmu')
        elif info.warnings:
            render_diagnostics_panel(info.warnings, title='Rozmery vybraného produktu')
    with defrag_tab:
        with st.container(border=True):
            st.subheader('Konsolidácia rozdrobených SKU')
            st.caption('Zlúčenie celého SKU do jednej existujúcej lokácie podľa kapacity a pravidiel miešania.')
            clicked = st.button('Analyzovať možnosti presunov', type='primary', on_click=_collapse_diagnostics)
        signature = (source_id, mixed)
        if clicked:
            with st.spinner('Analyzujem skladové lokácie…'):
                moves, freed, fragmented = analyze_defragmentation(stock, locations, products, mixed)
            st.session_state['defrag_result'] = (signature, moves, freed, fragmented)
        result = st.session_state.get('defrag_result')
        if result and result[0] != signature:
            del st.session_state['defrag_result']
            result = None
        if result:
            _, moves, freed, fragmented = result
            render_kpi_cards([
                ('Rozdrobené SKU', str(fragmented), 'SKU uložené na viacerých lokáciách.'),
                ('Uvoľnené lokácie', str(freed), 'Lokácie, ktoré sa po navrhnutých presunoch vyprázdnia.'),
                ('Odporúčané presuny', str(len(moves)), 'Počet riadkov plánu pohybov.'),
            ])
            render_defrag_chart(fragmented, freed, len(moves))
            if moves.empty:
                st.caption('Pri aktuálnych pravidlách nebola nájdená konsolidácia do jednej existujúcej lokácie.')
            else:
                with st.container(border=True):
                    st.subheader('Odporúčané skladové presuny')
                    st.caption('Presuny vykonávajte v poradí tabuľky.')
                    display = moves.rename(columns=dict(zip(MOVE_COLUMNS, ['SKU', 'Produkt', 'Zdroj', 'Presunúť ks', 'Cieľ', 'Uvoľní zdroj'])))
                    st.dataframe(display, hide_index=True, width='stretch')
                    st.download_button('Stiahnuť presuny CSV', display.to_csv(index=False).encode('utf-8-sig'), 'presuny.csv', 'text/csv', on_click='ignore')
            render_diagnostics_panel(moves.attrs.get('warnings', []), title='Detaily konsolidácie')
    with data_tab:
        st.caption('Použité dáta po vynechaní záznamov s neznámymi lokáciami. Zdrojový Excel zostáva nezmenený.')
        for title, frame in (('SKU aktuál', stock), ('Locations', locations), ('Produkty', products)):
            with st.expander(f'{title} · {len(frame):,} riadkov'):
                # Arrow conversion requires a contiguous display index in some versions.
                st.dataframe(frame.reset_index(drop=True), hide_index=True, width='stretch')
    st.caption('Výstupy sú návrhy. Potvrdené skladové pohyby zapíšte do zdrojového systému a načítajte aktuálny Excel.')


if __name__ == '__main__':
    main()
