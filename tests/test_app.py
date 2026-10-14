"""Streamlit interactions with small valid/invalid workbooks."""
import importlib.util
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit is not installed')
class AppTests(unittest.TestCase):
    def metrics(self, app):
        return {metric.label: metric.value for metric in app.metric}

    def app(self, invalid=False, unknown=False, low_sales=False, legacy=False, stale_import=False):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).with_name('ui_fixture.py')), default_timeout=30)
        app.query_params['invalid'] = '1' if invalid else '0'
        app.query_params['unknown'] = '1' if unknown else '0'
        app.query_params['low_sales'] = '1' if low_sales else '0'
        app.query_params['legacy'] = '1' if legacy else '0'
        app.query_params['stale_import'] = '1' if stale_import else '0'
        return app.run()

    def test_valid_ui_plans_and_defragments(self):
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        metrics = self.metrics(app)
        self.assertEqual([metrics[k] for k in ('Príjem spolu', 'Do primáru', 'Do SWAPu', 'Primárne lokácie')], ['20 ks', '9 ks', '11 ks', '1'])
        self.assertTrue(any('Primárna alokácia môže prekročiť cieľ' in c.value for c in app.caption))
        self.assertTrue(any('Aktuálna zásoba: 3 ks · Cieľ primáru: 10 ks' in c.value for c in app.caption))
        self.assertEqual(app.dataframe[0].value['Počet ks'].sum(), 20)
        app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        metrics = self.metrics(app)
        self.assertEqual([metrics[k] for k in ('Rozdrobené SKU', 'Uvoľnené lokácie', 'Odporúčané presuny')], ['1', '1', '1'])

    def test_invalid_ui_blocks_planning(self):
        app = self.app(invalid=True)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('záporné' in e.value for e in app.error))
        self.assertEqual(len(app.button), 0)

    def test_unknown_location_warns_but_planning_continues(self):
        app = self.app(unknown=True)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertEqual(len(app.warning), 0)
        self.assertTrue(any('Vynechané záznamy zásob: 1' in m.value for m in app.markdown))
        app.checkbox[1].check().run()
        self.assertTrue(any('Ignorované' in m.value for m in app.markdown))
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        metrics = self.metrics(app)
        self.assertEqual([metrics[k] for k in ('Do primáru', 'Do SWAPu')], ['9 ks', '11 ks'])
        self.assertFalse(app.checkbox[1].value)

    def test_results_survive_diagnostics_toggle_and_rerun(self):
        app = self.app(unknown=True)
        app.button[0].click().run()
        app.checkbox[1].check().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.metrics(app)['Do primáru'], '9 ks')
        app.checkbox[1].uncheck().run()
        self.assertEqual(self.metrics(app)['Do SWAPu'], '11 ks')
        app.run()
        self.assertFalse(app.checkbox[1].value)
        self.assertEqual(app.dataframe[0].value['Počet ks'].sum(), 20)

    def test_stale_putaway_result_is_removed_when_inputs_change(self):
        app = self.app()
        app.button[0].click().run()
        app.number_input[0].set_value(30).run()
        self.assertNotIn('Do primáru', self.metrics(app))
        app.button[0].click().run()
        self.assertEqual(self.metrics(app)['Do SWAPu'], '21 ks')

    def test_stale_defrag_result_is_removed_when_rules_change(self):
        app = self.app()
        app.button[1].click().run()
        self.assertEqual(self.metrics(app)['Uvoľnené lokácie'], '1')
        app.checkbox[0].check().run()
        self.assertNotIn('Uvoľnené lokácie', self.metrics(app))

    def test_repository_workbook_renders_and_plans(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertTrue(any('Vynechané záznamy zásob: 7' in m.value for m in app.markdown))
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.dataframe[0].value['Počet ks'].sum(), 20)

    def test_low_sales_primary_20_in_kpi_table_and_chart(self):
        app = self.app(low_sales=True)
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.metrics(app)['Do primáru'], '20 ks')
        self.assertEqual(self.metrics(app)['Do SWAPu'], '0 ks')
        table = app.dataframe[0].value
        self.assertEqual(table.loc[table.Typ == 'Primár', 'Počet ks'].sum(), 20)
        self.assertEqual(table.loc[table.Typ == 'SWAP / nadzásoba', 'Počet ks'].sum(), 0)
        self.assertTrue(any('20 ks do primáru (100%) · 0 ks do SWAPu (0%)' in c.value for c in app.caption))
        # Verify the actual Arrow dataset sent to the donut, not only its caption.
        import pyarrow as pa
        chart = app.get('arrow_vega_lite_chart')[0].proto
        dataset = chart.data.data if chart.data.data else chart.datasets[0].data.data
        chart_data = pa.ipc.open_stream(dataset).read_all().to_pandas()
        self.assertEqual(chart_data['Počet ks'].tolist(), [20, 0])

    def test_old_target_capped_session_result_is_invalidated(self):
        app = self.app(low_sales=True, legacy=True)
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn('Do primáru', self.metrics(app))
        app.button[0].click().run()
        self.assertEqual(self.metrics(app)['Do primáru'], '20 ks')
        self.assertEqual(self.metrics(app)['Do SWAPu'], '0 ks')

    def test_old_imported_planner_is_reloaded_from_current_source(self):
        app = self.app(low_sales=True, stale_import=True)
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.metrics(app)['Do primáru'], '20 ks')
        self.assertEqual(self.metrics(app)['Do SWAPu'], '0 ks')


if __name__ == '__main__':
    unittest.main()
