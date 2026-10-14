import unittest
import pandas as pd
from warehouse import (plan_putaway, analyze_defragmentation, validate_input_data,
                       get_product_info, calculate_location_capacity, Warehouse)


def fixture(rows=(), sales=10):
    stock = pd.DataFrame(rows, columns=['Produkt', 'Lokace', 'Množstvo'])
    locations = pd.DataFrame({'Názov lokácie': ['L1', 'L2', 'L3'],
                              'Šírka': [100]*3, 'Hloubka': [100]*3, 'Výška': [100]*3})
    products = pd.DataFrame({'Produkt': ['A', 'B'], 'Prodeje měsíc': [sales, 10],
                             'Šírka': [10, 50], 'Hloubka': [100, 100],
                             'Výška': [100, 100], 'Stohovatelnost': [1, 1]})
    return stock, locations, products


class PlanningTests(unittest.TestCase):
    def test_sales_2_target_2_inbound_20_capacity_56_all_primary(self):
        stock, locations, products = fixture(sales=2)
        locations['Šírka'] = 560
        self.assertEqual(Warehouse(stock, locations, products).free_capacity('L1', 'A'), 56)
        plan, summary = plan_putaway('A', 20, 30, stock, locations, products)
        self.assertEqual((summary['target_stock_needed'], summary['current_stock'], summary['needed_for_target']), (2, 0, 2))
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].sum(), 20)
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 0)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'free_before'].tolist(), [56])
        self.assertFalse(any('Cieľová zásoba je pokrytá' in reason for reason in plan.reason))

    def test_target_100_inbound_50_capacity_60_all_primary(self):
        plan, _ = plan_putaway('A', 50, 30, *self.capacity_fixture(sales=100))
        self.assertEqual(plan.type.tolist(), ['PRIMARY'])
        self.assertEqual(plan.quantity.tolist(), [50])

    def test_replenishes_existing_location_to_capacity_and_swaps_remainder(self):
        data = fixture([('A', 'L1', 8)])
        plan, summary = plan_putaway('A', 20, 30, *data)
        self.assertEqual(summary['needed_for_target'], 2)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].sum(), 2)
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 18)

    def test_target_across_multiple_locations(self):
        data = fixture(sales=15)
        plan, _ = plan_putaway('A', 30, 30, *data)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].tolist(), [10, 10])
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 10)
        self.assertNotIn('L3', plan.location.tolist())
        self.assertEqual(plan.quantity.sum(), 30)

    def test_already_above_target_all_swaps(self):
        data = fixture([('A', 'L1', 10)])
        plan, _ = plan_putaway('A', 5, 30, *data)
        self.assertEqual(plan.type.tolist(), ['SWAP'])

    def test_zero_sales_one_location(self):
        plan, _ = plan_putaway('A', 25, 30, *fixture(sales=0))
        self.assertEqual(len(plan[plan.type == 'PRIMARY']), 1)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].sum(), 10)
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 15)

    def capacity_fixture(self, rows=(), sales=19):
        stock, locations, products = fixture(rows, sales=sales)
        locations['Šírka'] = 600  # SKU A: 60 units per location.
        return stock, locations, products

    def test_example_a_empty_location_fills_60_and_swaps_10(self):
        stock, locations, products = self.capacity_fixture([('A', 'L1', 5)])
        locations.loc[0, 'Šírka'] = 50  # Existing stock is on a full 5-unit location.
        plan, summary = plan_putaway('A', 70, 30, stock, locations, products)
        self.assertEqual((summary['current_stock'], summary['target_stock_needed'], summary['needed_for_target']), (5, 19, 14))
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].tolist(), [60])
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'location'].tolist(), ['L2'])
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 10)
        self.assertNotIn('L3', plan.location.tolist())
        self.assertIn('cieľová zásoba je pokrytá', plan.loc[plan.type == 'SWAP', 'reason'].iloc[0])

    def test_example_b_same_sku_fills_55_and_swaps_15(self):
        plan, _ = plan_putaway('A', 70, 30, *self.capacity_fixture([('A', 'L1', 5)]))
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'location'].tolist(), ['L1'])
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].tolist(), [55])
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 15)

    def test_example_c_small_inbound_all_goes_to_primary(self):
        plan, _ = plan_putaway('A', 8, 30, *self.capacity_fixture([('A', 'L1', 5)]))
        self.assertEqual(plan.type.tolist(), ['PRIMARY'])
        self.assertEqual(plan.quantity.tolist(), [8])

    def test_example_d_covered_target_all_70_goes_to_swap(self):
        plan, summary = plan_putaway('A', 70, 30, *self.capacity_fixture([('A', 'L1', 25)]))
        self.assertEqual(summary['needed_for_target'], 0)
        self.assertEqual(plan.type.tolist(), ['SWAP'])
        self.assertEqual(plan.quantity.tolist(), [70])

    def test_example_e_two_full_locations_overshoot_target(self):
        plan, _ = plan_putaway('A', 200, 30, *self.capacity_fixture(sales=100))
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].tolist(), [60, 60])
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'location'].tolist(), ['L1', 'L2'])
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 80)

    def test_zero_sales_fills_only_one_60_unit_location(self):
        plan, _ = plan_putaway('A', 200, 30, *self.capacity_fixture(sales=0))
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].tolist(), [60])
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 140)

    def test_zero_sales_existing_full_does_not_open_new_location(self):
        plan, _ = plan_putaway('A', 5, 30, *fixture([('A', 'L1', 10)], sales=0))
        self.assertEqual(plan.type.tolist(), ['SWAP'])

    def test_zero_sales_partial_existing_only(self):
        plan, _ = plan_putaway('A', 8, 30, *fixture([('A', 'L1', 8)], sales=0))
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'location'].tolist(), ['L1'])
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].sum(), 2)

    def test_no_mixing_including_same_sku_in_mixed_location(self):
        data = fixture([('A', 'L1', 1), ('B', 'L1', 1), ('B', 'L2', 1)])
        plan, _ = plan_putaway('A', 20, 30, *data)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'location'].tolist(), ['L3'])
        self.assertEqual(Warehouse(*data).free_capacity('L1', 'A'), 0)

    def test_same_sku_priority_and_own_quantity_capacity(self):
        data = fixture([('A', 'L1', 2), ('A', 'L1', 1)], sales=20)
        plan, _ = plan_putaway('A', 9, 30, *data)
        self.assertEqual(plan.location.tolist(), ['L1', 'L2'])
        self.assertEqual(plan.quantity.tolist(), [7, 2])

    def test_mixed_opt_in_uses_other_product_capacity(self):
        data = fixture([('B', 'L1', 1)], sales=40)
        wh = Warehouse(*data)
        self.assertEqual(wh.free_capacity('L1', 'A', True), 5)
        plan, _ = plan_putaway('A', 25, 30, *data, allow_mixed_sku=True)
        self.assertEqual(plan.location.tolist(), ['L2', 'L3', 'L1'])
        self.assertEqual(plan.quantity.tolist(), [10, 10, 5])

    def test_defrag_rejects_overfull_targets(self):
        moves, freed, _ = analyze_defragmentation(*fixture([('A', 'L1', 6), ('A', 'L2', 6)]))
        self.assertTrue(moves.empty)
        self.assertEqual(freed, 0)

    def test_defrag_aggregates_duplicate_rows(self):
        moves, freed, fragmented = analyze_defragmentation(*fixture([('A', 'L1', 2), ('A', 'L1', 1), ('A', 'L2', 4)]))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves.iloc[0].quantity, 3)
        self.assertEqual(moves.iloc[0].target, 'L2')
        self.assertEqual((freed, fragmented), (1, 1))

    def test_defrag_excludes_mixed_target_and_counts_actual_freed(self):
        data = fixture([('A', 'L1', 5), ('B', 'L1', 1), ('A', 'L2', 2)])
        moves, freed, _ = analyze_defragmentation(*data)
        self.assertTrue(moves.empty)  # L1 cannot be a target; emptying A from L1 does not free it.
        self.assertEqual(freed, 0)

    def test_defrag_mixed_capacity_and_freed_source(self):
        data = fixture([('A', 'L1', 4), ('B', 'L1', 1), ('A', 'L2', 2)])
        # Mixed L1 has room for only one more A, so L2 must be the target.
        moves, freed, _ = analyze_defragmentation(*data, allow_mixed_sku=True)
        self.assertTrue(moves.empty)  # Moving out of L1 alone frees no location.
        self.assertEqual(freed, 0)

    def test_defrag_mixed_opt_in_can_free_a_pure_source(self):
        data = fixture([('A', 'L1', 2), ('B', 'L1', 1), ('A', 'L2', 1)])
        moves, freed, _ = analyze_defragmentation(*data, allow_mixed_sku=True)
        self.assertEqual(moves.target.tolist(), ['L1'])
        self.assertEqual(freed, 1)

    def test_negative_sales_and_zero_stackability_are_warned_defaults(self):
        stock, locations, products = fixture(sales=-1)
        products.loc[0, 'Stohovatelnost'] = 0
        errors, warnings = validate_input_data(stock, locations, products)
        self.assertEqual(errors, [])
        self.assertTrue(warnings)
        info = get_product_info('A', products, stock)
        self.assertEqual((info.monthly_sales, info.stackability), (0, 1))

    def test_product_dimensions_take_precedence(self):
        stock, locations, products = fixture([('A', 'L1', 1)])
        stock['Šírka'] = 99
        self.assertEqual(get_product_info('A', products, stock).width, 10)
        products = products.drop(columns=['Šírka'])
        self.assertEqual(get_product_info('A', products, stock).width, 99)
        stock = stock.drop(columns=['Šírka'])
        info = get_product_info('A', products, stock)
        self.assertEqual(info.width, 60)
        self.assertTrue(info.warnings)

    def test_rotation_and_height_limit(self):
        self.assertEqual(calculate_location_capacity(80, 120, 170, 60, 80, 85, 3), 4)

    def test_validation_blocks_invalid_values_and_keys(self):
        for rows in ([('A', 'L1', -1)], [('A', 'L1', 'oops')], [('A', 'L1', 1.5)],
                     [('UNKNOWN', 'L1', 1)], [('A', 'L1', float('inf'))]):
            with self.subTest(rows=rows):
                self.assertTrue(validate_input_data(*fixture(rows))[0])
                with self.assertRaises(ValueError):
                    plan_putaway('A', 1, 30, *fixture(rows))

    def test_unknown_locations_do_not_count_toward_target(self):
        data = fixture([('A', 'L1', 2), ('A', 'UNKNOWN', 100)])
        errors, warnings = validate_input_data(*data)
        self.assertEqual(errors, [])
        self.assertTrue(any('Ignorované' in w for w in warnings))
        plan, summary = plan_putaway('A', 20, 30, *data)
        self.assertEqual(summary['current_stock'], 2)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].sum(), 8)
        self.assertEqual(plan.loc[plan.type == 'SWAP', 'quantity'].sum(), 12)

    def test_unknown_locations_do_not_affect_defragmentation(self):
        moves, freed, fragmented = analyze_defragmentation(*fixture([
            ('A', 'L1', 2), ('A', 'L2', 3), ('A', 'UNKNOWN', 100)]))
        self.assertEqual((freed, fragmented), (1, 1))
        self.assertEqual(moves.quantity.tolist(), [2])
        self.assertNotIn('UNKNOWN', moves.source.tolist() + moves.target.tolist())

    def test_ignored_rows_are_not_validated_or_used_for_dimensions(self):
        stock, locations, products = fixture([('A', 'L1', 2), ('MISSING', 'UNKNOWN', 'bad')])
        self.assertEqual(validate_input_data(stock, locations, products)[0], [])
        stock, locations, products = fixture([('A', 'L1', 2), ('A', 'UNKNOWN', 100)])
        products = products.drop(columns=['Šírka'])
        stock['Šírka'] = [10, 1000]
        wh = Warehouse(stock, locations, products)
        self.assertEqual(wh.info('A').width, 10)
        self.assertEqual(wh.capacity('L1', 'A'), 10)

    def test_all_stock_can_be_ignored(self):
        data = fixture([('A', 'UNKNOWN', 100)])
        plan, summary = plan_putaway('A', 3, 30, *data)
        self.assertEqual(summary['current_stock'], 0)
        self.assertEqual(plan.loc[plan.type == 'PRIMARY', 'quantity'].sum(), 3)
        moves, freed, fragmented = analyze_defragmentation(*data)
        self.assertTrue(moves.empty)
        self.assertEqual((freed, fragmented), (0, 0))

    def test_validation_required_columns_duplicates_and_dimensions(self):
        stock, locations, products = fixture()
        self.assertTrue(validate_input_data(stock.drop(columns=['Množstvo']), locations, products)[0])
        locations.loc[1, 'Názov lokácie'] = ' L1 '
        self.assertTrue(validate_input_data(stock, locations, products)[0])
        products.loc[0, 'Šírka'] = 0
        self.assertTrue(validate_input_data(stock, locations, products)[0])

    def test_fractional_numeric_strings_and_zero_rows(self):
        data = fixture([('A', 'L1', '0'), ('B', 'L1', '0')])
        data[2]['Stohovatelnost'] = ['1.0', '1.0']
        plan, _ = plan_putaway('A', 1, 30, *data)
        self.assertEqual(plan.location.tolist(), ['L1'])


if __name__ == '__main__':
    unittest.main()
