"""Deterministic workbook provider for Streamlit AppTest."""
from unittest.mock import patch
import pandas as pd
import streamlit as st
from app import main

invalid = st.query_params.get('invalid') == '1'
stock = pd.DataFrame({'Produkt': ['A', 'A'], 'Lokace': ['L1', 'L2'], 'Množstvo': [2, -1 if invalid else 1]})
locations = pd.DataFrame({'Názov lokácie': ['L1', 'L2', 'L3'], 'Šírka': [100]*3, 'Hloubka': [100]*3, 'Výška': [100]*3})
products = pd.DataFrame({'Produkt': ['A'], 'Prodeje měsíc': [10], 'Šírka': [10], 'Hloubka': [100], 'Výška': [100], 'Stohovatelnost': [1]})
with patch('app.Path.read_bytes', return_value=b'invalid-ui' if invalid else b'valid-ui'), patch('app.load_data_from_excel', return_value=(stock, locations, products)):
    main()
