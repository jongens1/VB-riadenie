"""Pure warehouse rules; all dimensions are in cm and quantities in whole units."""
from dataclasses import dataclass
import math
import pandas as pd

ALIASES = {
    'sku': ('Produkt', 'SKU', 'Product'),
    'location': ('Názov lokácie', 'Lokace', 'Lokácia', 'Location'),
    'quantity': ('Množstvo', 'Množství', 'Qty', 'Počet'),
    'width': ('Šírka (cm)', 'Šířka (cm)', 'Šírka', 'Šířka', 'Width (cm)', 'Width'),
    'depth': ('Hĺbka (cm)', 'Hloubka (cm)', 'Hĺbka', 'Hloubka', 'Depth (cm)', 'Depth'),
    'height': ('Výška (cm)', 'Výška', 'Height (cm)', 'Height'),
    'stackability': ('Stohovatelnost', 'Stohovateľnosť', 'Stackability', 'Stohovanie'),
    'sales': ('Prodeje měsíc', 'Predaje mesiac', 'Monthly sales'),
    'name': ('Název produktu', 'Názov produktu', 'Product name'),
}
DIMENSIONS = ('width', 'depth', 'height')
DEFAULT_PRODUCT = dict(width=60, depth=60, height=85)
DEFAULT_LOCATION = dict(width=120, depth=80, height=200)
ALLOCATION_COLUMNS = ['type', 'location', 'quantity', 'free_before', 'capacity', 'reason']
MOVE_COLUMNS = ['sku', 'name', 'source', 'quantity', 'target', 'frees_source']


def resolve_columns(df):
    names = {str(c).strip().casefold(): c for c in df.columns}
    return {key: next((names[a.casefold()] for a in aliases if a.casefold() in names), None)
            for key, aliases in ALIASES.items()}


def normalize_key(value):
    if pd.isna(value):
        return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and float(value).is_integer():
            return str(int(value))
    return str(value).strip()


def exclude_unknown_locations(df_sku_aktual, df_location):
    """Drop stock outside the location catalogue before validation or calculations."""
    if df_sku_aktual.columns.duplicated().any() or df_location.columns.duplicated().any():
        return df_sku_aktual.copy(), []
    sc, lc = resolve_columns(df_sku_aktual), resolve_columns(df_location)
    if sc['location'] is None or lc['location'] is None:
        return df_sku_aktual.copy(), []
    keys = df_sku_aktual[sc['location']].map(normalize_key)
    known = set(df_location[lc['location']].map(normalize_key)) - {''}
    excluded = ~keys.isin(known)
    warnings = []
    if excluded.any():
        locations = sorted(set(keys[excluded]))
        labels = ', '.join(key or '(prázdna lokácia)' for key in locations[:8])
        warnings.append(f'Ignorované záznamy zásob: {int(excluded.sum())} riadkov na {len(locations)} neznámych lokáciách ({labels}). Nezapočítavajú sa do zásob, kapacity ani defragmentácie.')
    return df_sku_aktual.loc[~excluded].copy(), warnings


def validate_input_data(df_sku_aktual, df_location, df_produkty):
    """Return errors and warnings; callers must block planning on errors."""
    df_sku_aktual, warnings = exclude_unknown_locations(df_sku_aktual, df_location)
    errors = []
    frames = {'SKU aktuál': df_sku_aktual, 'Locations': df_location, 'Produkty': df_produkty}
    required = {'SKU aktuál': ('sku', 'location', 'quantity'), 'Locations': ('location',), 'Produkty': ('sku',)}
    columns = {name: resolve_columns(df) for name, df in frames.items()}
    for name, df in frames.items():
        cols = columns[name]
        if df.columns.duplicated().any():
            errors.append(f'{name}: duplicitné hlavičky stĺpcov.')
            continue
        for key in required[name]:
            col = cols[key]
            if col is None:
                errors.append(f'{name}: chýba povinný stĺpec {key}.')
            elif key != 'quantity' and df[col].map(normalize_key).eq('').any():
                errors.append(f'{name}: prázdny kľúč v stĺpci {col}.')
        for key in ('quantity', *DIMENSIONS, 'sales', 'stackability'):
            col = cols[key]
            if col is None:
                continue
            values = pd.to_numeric(df[col], errors='coerce')
            invalid = values.isna() | ~values.map(lambda v: math.isfinite(v) if pd.notna(v) else False)
            if key in ('sales', 'stackability'):
                invalid &= df[col].notna()
                if df[col].isna().any():
                    default = '0 predajov' if key == 'sales' else 'stohovanie 1'
                    warnings.append(f'{name}: prázdne {col}; použije sa {default}.')
            if invalid.any():
                errors.append(f'{name}: {col} obsahuje {int(invalid.sum())} nečíselných, prázdnych alebo nekonečných hodnôt.')
            if key == 'sales' and (values < 0).any():
                warnings.append(f'{name}: záporné predaje sa vyhodnotia ako 0.')
            elif key != 'stackability' and (values < 0).any():
                errors.append(f'{name}: {col} obsahuje záporné hodnoty.')
            if key in DIMENSIONS and (values == 0).any():
                errors.append(f'{name}: {col} musí mať kladné rozmery v cm.')
            if key in ('quantity', 'stackability') and ((values.dropna() % 1) != 0).any():
                errors.append(f'{name}: {col} musí obsahovať celé počty kusov.')
            if key == 'stackability' and (values < 1).any():
                warnings.append(f'{name}: stohovateľnosť pod 1 sa nahradí hodnotou 1.')
    if errors:
        return errors, warnings
    sc, lc, pc = (columns[n] for n in frames)
    stock_skus = df_sku_aktual[sc['sku']].map(normalize_key)
    product_keys = df_produkty[pc['sku']].map(normalize_key)
    location_keys = df_location[lc['location']].map(normalize_key)
    for label, missing in (('Produkty', set(stock_skus) - set(product_keys)),):
        if missing:
            errors.append(f"Chýbajúce kľúče v {label}: {', '.join(sorted(missing)[:8])} (celkom {len(missing)}).")
    if location_keys.duplicated().any():
        errors.append('Locations: duplicitné názvy lokácií po odstránení okrajových medzier.')
    if product_keys.duplicated().any():
        errors.append('Produkty: duplicitné produktové kľúče; produktové údaje by boli nejednoznačné.')
    if df_produkty.empty or df_location.empty:
        errors.append('Produkty a Locations musia obsahovať aspoň jeden riadok.')
    if df_sku_aktual.duplicated(subset=[sc['sku'], sc['location']]).any():
        warnings.append('SKU aktuál: opakované SKU/lokácie sa pri výpočte sčítajú.')
    for dim in DIMENSIONS:
        if not pc[dim] and not sc[dim]:
            warnings.append(f'Chýba rozmer produktu {dim}; použije sa {DEFAULT_PRODUCT[dim]} cm.')
        if not lc[dim]:
            warnings.append(f'Chýba rozmer lokácie {dim}; použije sa {DEFAULT_LOCATION[dim]} cm.')
    if not pc['sales']:
        warnings.append('Produkty: chýba mesačný predaj; všetky produkty budú v režime bez predaja.')
    if not pc['stackability']:
        warnings.append('Produkty: chýba stohovateľnosť; použije sa 1.')
    return errors, warnings


@dataclass(frozen=True)
class ProductInfo:
    sku: str
    name: str
    monthly_sales: float
    width: float
    depth: float
    height: float
    stackability: int
    warnings: tuple


def get_product_info(selected_product, df_produkty, df_sku_aktual):
    pc, sc = resolve_columns(df_produkty), resolve_columns(df_sku_aktual)
    sku = normalize_key(selected_product)
    rows = df_produkty[df_produkty[pc['sku']].map(normalize_key).eq(sku)]
    if len(rows) != 1:
        raise ValueError(f'Produkt {sku} musí mať práve jeden záznam v Produkty.')
    row = rows.iloc[0]
    stock = df_sku_aktual[df_sku_aktual[sc['sku']].map(normalize_key).eq(sku)]
    dimensions, warnings = {}, []
    for dim in DIMENSIONS:
        if pc[dim]:
            dimensions[dim] = float(row[pc[dim]])
        elif sc[dim] and not stock.empty:
            dimensions[dim] = float(pd.to_numeric(stock[sc[dim]]).max())
            if stock[sc[dim]].nunique() > 1:
                warnings.append(f'{sku}: rôzne hodnoty {dim} v zásobe; použitá najväčšia.')
        else:
            dimensions[dim] = DEFAULT_PRODUCT[dim]
            warnings.append(f'{sku}: chýba {dim}; použitý odhad {dimensions[dim]} cm.')
    sales = row[pc['sales']] if pc['sales'] else 0
    stack = row[pc['stackability']] if pc['stackability'] else 1
    return ProductInfo(sku, str(row[pc['name']]) if pc['name'] else sku,
                       0 if pd.isna(sales) else max(0, float(sales)), **dimensions,
                       stackability=1 if pd.isna(stack) else max(1, int(float(stack))), warnings=tuple(warnings))


def calculate_location_capacity(loc_w, loc_d, loc_h, prod_w, prod_d, prod_h, stackability):
    values = (loc_w, loc_d, loc_h, prod_w, prod_d, prod_h, stackability)
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in values):
        raise ValueError('Rozmery a stohovateľnosť musia byť kladné a konečné.')
    layers = min(int(stackability), int(loc_h // prod_h))
    floor = max(int(loc_w // prod_w) * int(loc_d // prod_d),
                int(loc_w // prod_d) * int(loc_d // prod_w))
    return floor * layers


def build_location_occupancy(df_sku_aktual):
    """Aggregate duplicate SKU/location records, ignoring zero stock."""
    cols = resolve_columns(df_sku_aktual)
    stock = pd.DataFrame({'sku': df_sku_aktual[cols['sku']].map(normalize_key),
                          'location': df_sku_aktual[cols['location']].map(normalize_key),
                          'quantity': pd.to_numeric(df_sku_aktual[cols['quantity']])})
    stock = stock.groupby(['sku', 'location'], as_index=False)['quantity'].sum()
    return stock[stock.quantity > 0].reset_index(drop=True)


class Warehouse:
    def __init__(self, stock, locations, products):
        errors, self.warnings = validate_input_data(stock, locations, products)
        if errors:
            raise ValueError('\n'.join(errors))
        stock, _ = exclude_unknown_locations(stock, locations)
        self.stock, self.products = stock, products
        self.columns = resolve_columns(locations)
        self.locations = {normalize_key(row[self.columns['location']]): row for _, row in locations.iterrows()}
        self.occupancy = {}
        for row in build_location_occupancy(stock).itertuples(index=False):
            self.occupancy.setdefault(row.location, {})[row.sku] = int(row.quantity)
        self.infos = {}

    def info(self, sku):
        if sku not in self.infos:
            self.infos[sku] = get_product_info(sku, self.products, self.stock)
        return self.infos[sku]

    def capacity(self, location, sku):
        row, info = self.locations[location], self.info(sku)
        dims = [float(row[self.columns[d]]) if self.columns[d] else DEFAULT_LOCATION[d] for d in DIMENSIONS]
        return calculate_location_capacity(*dims, info.width, info.depth, info.height, info.stackability)

    def free_capacity(self, location, sku, allow_mixed_sku=False):
        occupants = self.occupancy.get(location, {})
        others = {s: q for s, q in occupants.items() if s != sku and q > 0}
        cap = self.capacity(location, sku)
        if others and not allow_mixed_sku:
            return 0
        # Opt-in approximation using each SKU's homogeneous capacity. This is not
        # a physical mixed-item packing guarantee and must be verified by an operator.
        fraction = 0.0
        for other, quantity in others.items():
            other_cap = self.capacity(location, other)
            if other_cap == 0:
                return 0
            fraction += quantity / other_cap
        return max(0, math.floor(cap * (1 - fraction) + 1e-9) - occupants.get(sku, 0))


def plan_putaway(selected_product, total_qty_to_store, days_target,
                 df_sku_aktual, df_location, df_produkty, allow_mixed_sku=False):
    """Target stock triggers replenishment; each selected location fills to capacity.

    Once the target is met (including overshoot), no further location is used.
    Zero-sales products retain their one-primary-location rule.
    """
    if isinstance(total_qty_to_store, bool) or not math.isfinite(float(total_qty_to_store)) or total_qty_to_store < 1 or total_qty_to_store % 1:
        raise ValueError('Príjem musí byť kladný celý počet kusov.')
    if not math.isfinite(float(days_target)) or days_target <= 0:
        raise ValueError('Cieľ zásoby musí byť kladný počet dní.')
    warehouse = Warehouse(df_sku_aktual, df_location, df_produkty)
    sku = normalize_key(selected_product)
    info = warehouse.info(sku)
    current = sum(items.get(sku, 0) for items in warehouse.occupancy.values())
    existing = {loc for loc, items in warehouse.occupancy.items() if items.get(sku, 0) > 0}
    target = math.ceil(info.monthly_sales / 30 * days_target) if info.monthly_sales > 0 else None
    need = max(0, target - current) if target is not None else None
    candidates = []
    for location in warehouse.locations:
        items = warehouse.occupancy.get(location, {})
        group = 2 if set(items) - {sku} else (0 if sku in items else 1)
        free = warehouse.free_capacity(location, sku, allow_mixed_sku)
        if free > 0:
            candidates.append((group, -free, location, free))
    candidates.sort()
    remaining, remaining_target_need = int(total_qty_to_store), need
    allocations = []
    for group, _, location, free in candidates:
        if remaining == 0 or (remaining_target_need is not None and remaining_target_need <= 0):
            break
        if target is None and (len(existing) > 1 or (existing and location not in existing)):
            continue
        # Target need controls whether another location is used, never its quantity.
        qty_to_place = min(remaining, free)
        allocations.append(dict(type='PRIMARY', location=location, quantity=qty_to_place,
                                free_before=free, capacity=warehouse.capacity(location, sku),
                                reason='Doplnenie primárnej lokácie do kapacity – ' +
                                ('rovnaké SKU', 'prázdna lokácia', 'povolené miešanie SKU')[group]))
        remaining -= qty_to_place
        if target is None:
            break
        remaining_target_need -= qty_to_place
    if remaining:
        if target is None:
            reason = ('Zvyšok príjmu po naplnení jednej primárnej lokácie'
                      if allocations else 'Nie je dostupná vhodná kapacita v rámci limitu jednej primárnej lokácie')
        elif need == 0:
            reason = 'Cieľová zásoba bola pokrytá pred príjmom'
        elif remaining_target_need <= 0:
            reason = 'Zvyšok príjmu po naplnení primárnych lokácií; cieľová zásoba je pokrytá'
        else:
            reason = 'Nedostatok vhodnej primárnej kapacity'
        allocations.append(dict(type='SWAP', location='PALETOVÁ ZÓNA / SWAP', quantity=remaining,
                                free_before=None, capacity=None, reason=reason))
    warnings = list(warehouse.warnings) + list(info.warnings)
    if target is None and len(existing) > 1:
        warnings.append('Bezpredajné SKU už obsadzuje viac než jednu lokáciu. Príjem ide do SWAPu; najprv konsolidujte zásobu.')
    summary = dict(monthly_sales=info.monthly_sales, daily_sales=info.monthly_sales / 30,
                   current_stock=current,
                   target_stock_needed=target, needed_for_target=need, warnings=list(dict.fromkeys(warnings)))
    return pd.DataFrame(allocations, columns=ALLOCATION_COLUMNS), summary


def analyze_defragmentation(df_sku_aktual, df_location, df_produkty, allow_mixed_sku=False):
    warehouse = Warehouse(df_sku_aktual, df_location, df_produkty)
    stock = build_location_occupancy(warehouse.stock)
    fragmented = stock.groupby('sku').location.nunique()
    fragmented = fragmented[fragmented > 1]
    moves, freed = [], set()
    # Mutate virtual occupancy so proposals remain feasible when executed in order.
    for sku in sorted(fragmented.index):
        current = {loc: items[sku] for loc, items in warehouse.occupancy.items() if items.get(sku, 0) > 0}
        total = sum(current.values())
        targets = [loc for loc, qty in current.items()
                   if warehouse.free_capacity(loc, sku, allow_mixed_sku) >= total - qty
                   and any(set(warehouse.occupancy[src]) == {sku} for src in current if src != loc)]
        if not targets:
            continue
        target = sorted(targets, key=lambda loc: (-current[loc], loc))[0]
        # Only propose a consolidation when at least one source actually becomes empty.
        sources = [loc for loc in current if loc != target]
        if not any(set(warehouse.occupancy[loc]) == {sku} for loc in sources):
            continue
        for source in sorted(sources):
            quantity = current[source]
            del warehouse.occupancy[source][sku]
            is_freed = not warehouse.occupancy[source]
            if is_freed:
                freed.add(source)
            moves.append(dict(sku=sku, name=warehouse.info(sku).name, source=source,
                              quantity=quantity, target=target, frees_source=is_freed))
        warehouse.occupancy[target][sku] = total
    result = pd.DataFrame(moves, columns=MOVE_COLUMNS)
    result.attrs['warnings'] = list(dict.fromkeys(warehouse.warnings + [w for info in warehouse.infos.values() for w in info.warnings]))
    return result, len(freed), len(fragmented)
