"""Streamlit interactions with small valid/invalid workbooks."""
import importlib.util
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit is not installed')
class AppTests(unittest.TestCase):
    def app(self, invalid=False, unknown=False):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).with_name('ui_fixture.py')), default_timeout=30)
        app.query_params['invalid'] = '1' if invalid else '0'
        app.query_params['unknown'] = '1' if unknown else '0'
        return app.run()

    def test_valid_ui_plans_and_defragments(self):
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([m.value for m in app.metric], ['3 ks', '10 ks', '7 ks', '13 ks'])
        self.assertEqual(app.dataframe[0].value['Počet ks'].sum(), 20)
        app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([m.value for m in app.metric], ['1', '1'])

    def test_invalid_ui_blocks_planning(self):
        app = self.app(invalid=True)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('záporné' in e.value for e in app.error))
        self.assertEqual(len(app.button), 0)

    def test_unknown_location_warns_but_planning_continues(self):
        app = self.app(unknown=True)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertTrue(any('Ignorované' in w.value for w in app.warning))
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual([m.value for m in app.metric], ['3 ks', '10 ks', '7 ks', '13 ks'])


if __name__ == '__main__':
    unittest.main()
