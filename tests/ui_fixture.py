"""Deterministic workbook provider for Streamlit AppTest."""
from unittest.mock import patch
import hashlib
import pandas as pd
import streamlit as st
from app import main

invalid = st.query_params.get('invalid') == '1'
unknown = st.query_params.get('unknown') == '1'
low_sales = st.query_params.get('low_sales') == '1'
if st.query_params.get('stale_import') == '1' and not st.session_state.get('stale_import_seeded'):
    import warehouse
    def stale_plan(*args, **kwargs):
        raise AssertionError('The old imported planner must not be called')
    warehouse.plan_putaway = stale_plan
    st.cache_resource.clear()
    st.session_state['stale_import_seeded'] = True
stock = pd.DataFrame({'Produkt': ['A', 'A'], 'Lokace': ['L1', 'L2'], 'Množstvo': [2, -1 if invalid else 1]})
if unknown:
    stock.loc[len(stock)] = ['A', 'UNKNOWN', 100]
stock.index = range(10, 10 + len(stock) * 10, 10)
locations = pd.DataFrame({'Názov lokácie': ['L1', 'L2', 'L3'], 'Šírka': [100]*3, 'Hloubka': [100]*3, 'Výška': [100]*3})
products = pd.DataFrame({'Produkt': ['A'], 'Prodeje měsíc': [10], 'Šírka': [10], 'Hloubka': [100], 'Výška': [100], 'Stohovatelnost': [1]})
if low_sales:
    stock = stock.iloc[0:0].copy()
    products['Prodeje měsíc'] = 2
    locations['Šírka'] = 560
source = b'low-sales-ui' if low_sales else (b'unknown-ui' if unknown else (b'invalid-ui' if invalid else b'valid-ui'))
if st.query_params.get('legacy') == '1' and not st.session_state.get('legacy_seeded'):
    old_signature = (hashlib.sha256(source).hexdigest(), 'A', 20, 30, False)
    old_plan = pd.DataFrame({'type': ['PRIMARY', 'SWAP'], 'location': ['L1', 'SWAP'],
                            'quantity': [2, 18], 'free_before': [56, None],
                            'capacity': [56, None], 'reason': ['Old target cap', 'Old remainder']})
    old_summary = dict(target_stock_needed=2, needed_for_target=2, current_stock=0, warnings=[])
    st.session_state['putaway_result'] = (old_signature, old_plan, old_summary)
    st.session_state['legacy_seeded'] = True
# Only mock the workbook; main also reads warehouse.py to identify the loaded rules.
from pathlib import Path
original_read_bytes = Path.read_bytes
def read_test_source(path):
    return original_read_bytes(path) if path.name == 'warehouse.py' else source
with patch('app.Path.read_bytes', read_test_source), patch('app.load_data_from_excel', return_value=(stock, locations, products)):
    main()
