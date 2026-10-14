# VB · Riadenie skladu

Streamlit aplikácia navrhuje zaskladnenie príjmu do primáru/SWAPu a presuny,
ktoré konsolidujú SKU do jednej existujúcej lokácie a uvoľnia zdrojové lokácie.
Zdrojový Excel sa nemení. Plány možno exportovať do CSV.

## Spustenie

```sh
python -m pip install -r requirements.txt
streamlit run app.py
python -m unittest discover -s tests -v
```

`app.py` obsahuje rozhranie a načítanie Excelu. `warehouse.py` obsahuje čisté
funkcie `resolve_columns`, `validate_input_data`, `get_product_info`,
`calculate_location_capacity`, `build_location_occupancy`, `plan_putaway`
a `analyze_defragmentation`. Import modulu nespúšťa Streamlit.

## Dáta

Povinné hárky: **SKU aktuál**, **Locations** alebo **Location**, **Produkty**.
Povinné stĺpce: produkt/lokácia/množstvo v zásobe, lokácia v Locations,
produkt v Produkty. Podporované české, slovenské a anglické názvy sú v `ALIASES`.
Identifikátory sa porovnávajú ako text bez okrajových medzier; číselné 123.0
sa normalizuje na 123. Textové kódy s úvodnými nulami sa zachovajú.

Rozmery v cm sa berú pre každú os najprv z Produkty, potom zo SKU aktuál.
Pri nejednotných rozmeroch zásoby sa použije najväčší rozmer každej osi.
Chýbajúce rozmery majú explicitný odhad s upozornením: produkt 60 × 60 × 85 cm,
lokácia 120 × 80 × 200 cm. Neplatné existujúce rozmery sa nenahrádzajú odhadom:
výpočet sa zastaví. Rozmer GeoSize sa neinterpretuje ako fyzický rozmer.

Záporné alebo prázdne predaje znamenajú 0 predajov, stohovateľnosť pod 1 alebo
prázdna znamená 1; zobrazí sa varovanie. Nečíselné údaje, nekladné rozmery,
záporné/neceločíselné množstvá, neznáme kľúče a duplicitné kľúče lokácií alebo
produktov blokujú plán. Duplicitné SKU/lokácie v zásobe sa sčítajú.

## Pravidlá a obmedzenia

- Cieľ predajného SKU je `ceil(mesačný predaj / 30 × dni)`. Príjem do primáru
  nikdy neprekročí chýbajúcu cieľovú zásobu. Zvyšok ide do SWAPu, aj keď nie je
  dostatok vhodnej kapacity; dôvod je uvedený v pláne.
- Bezpredajné SKU dopĺňa jednu existujúcu lokáciu alebo otvorí jednu novú.
  Ak má už viac lokácií, nový príjem ide do SWAPu do konsolidácie.
- Predvolene sa používajú iba čisté lokácie rovnakého SKU a prázdne lokácie,
  v tomto poradí. Lokácia s rovnakým aj iným SKU je zmiešaná a je vylúčená.
- `allow_mixed_sku=True` povoľuje zmiešané lokácie až za čistými kandidátmi.
  Voľná kapacita sa odhaduje podielmi `množstvo / kapacita` každého iného SKU.
  Tento model nezaručuje fyzické uloženie rôznych rozmerov: vyžaduje overenie.
- Defragmentácia pracuje s virtuálnou obsadenosťou, takže kombinované návrhy
  neprekročia vypočítanú kapacitu. Presuny sa vykonávajú v poradí výstupu.
  Počítajú sa len skutočne prázdne zdrojové lokácie, nie odobrané SKU zo zmiešanej
  lokácie. Návrh musí uvoľniť aspoň jednu lokáciu.
- Všetka zásoba v SKU aktuál sa počíta ako primárna. Excel nemá explicitné
  rozdelenie primár/SWAP; aplikácia ho neodvodzuje z názvu lokácie.
- Kapacita je geometrický odhad s otočením pôdorysu o 90° a limitom stohovania.
  Nevyhodnocuje nosnosť, manipulačné medzery, typ regálu ani kapacitu SWAP zóny.

Po vykonaní pohybov načítajte aktualizované dáta zo skladového systému.
