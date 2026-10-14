# VB · Riadenie skladu

Streamlit aplikácia navrhuje zaskladnenie príjmu do primáru/SWAPu a presuny,
ktoré konsolidujú SKU do jednej existujúcej lokácie a uvoľnia zdrojové lokácie.
Zdrojový Excel sa nemení. Plány možno exportovať do CSV.

Dashboard používa jednotnú tmavomodrú tému (`.streamlit/config.toml`) a CSS
v `inject_custom_css()`. Hore je krátky súhrn a KPI produktov, lokácií,
upozornení a zdroja. Podrobnosti dát sú dostupné cez checkbox **Zobraziť
diagnostiku dát** a zbaliteľné panely; po výpočte sa diagnostika automaticky
skryje. Chyby blokujúce výpočet zostávajú viditeľné.

Výsledky príjmu obsahujú KPI, donut graf primár/SWAP a tabuľku. Defragmentácia
obsahuje KPI a stĺpcový graf. Grafy využívajú Vega-Lite podporu v Streamlite,
takže netreba ďalšiu závislosť. Výsledky zostávajú dostupné pri prepnutí
diagnostiky; zmena vstupov zneplatní príslušný plán, aby sa neexportovali
zastarané odporúčania.

Pravidlá z `warehouse.py` sa načítajú podľa odtlačku aktuálneho zdrojového
súboru. Po zmene pravidiel sa obnoví importovaný modul a staré uložené plány
sa zneplatnia. Tým sa predchádza použitiu starého plánovača po aktualizácii
`app.py`. Pri nasadení nahraďte oba súbory a reštartujte bežiacu aplikáciu
(na Streamlit Cloud: Manage app → Reboot app).

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
záporné/neceločíselné množstvá, neznáme produktové kľúče a duplicitné kľúče lokácií alebo
produktov blokujú plán. Duplicitné SKU/lokácie v zásobe sa sčítajú.

Záznamy zásob s lokáciou, ktorá chýba v Locations, sa ignorujú ešte pred
validáciou ostatných údajov. Zobrazí sa upozornenie s počtom vynechaných riadkov
a zoznamom lokácií. Tieto riadky neovplyvnia aktuálnu zásobu, rozmery produktu,
kapacitu, cieľ primáru ani defragmentáciu; nezobrazia sa v náhľade použitej zásoby.
Pôvodný Excel sa nemení. Ak chýba samotný stĺpec lokácie, ide stále o chybu.

## Pravidlá a obmedzenia

- Cieľ predajného SKU je `ceil(mesačný predaj / 30 × dni)`. Cieľová zásoba
  spúšťa dopĺňanie primáru, neurčuje horný limit alokácie do vybranej lokácie.
  Ak je cieľ už pokrytý pred príjmom, celý príjem ide do SWAPu. Inak sa každá
  vybraná lokácia plní do voľnej kapacity alebo do zostatku príjmu. Po pokrytí
  cieľa sa ďalšia lokácia nepoužije, aj keď posledná alokácia cieľ prekročí.
  Príklad: zásoba 5 ks, cieľ 19 ks, príjem 70 ks a prázdna lokácia 60 ks
  znamená primár 60 ks a SWAP 10 ks. Pri doplnení existujúcej lokácie s 5 ks
  a kapacitou 60 ks je primárny príjem 55 ks a SWAP 15 ks.
  Zvyšok ide do SWAPu, aj keď nie je
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
