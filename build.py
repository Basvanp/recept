#!/usr/bin/env python3
"""Leest 'Marthe - FITFORTY2 .ods' en injecteert de data als JSON in index.html.

Gebruik:  python3 build.py
Draai dit opnieuw wanneer de .ods is bijgewerkt.
"""
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ODS_FILE = "Marthe - FITFORTY2 .ods"
HTML_FILE = "index.html"

T = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
TX = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
O = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"


def read_sheets(path):
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read("content.xml"))
    sheets = {}
    for t in root.findall(f".//{{{T}}}table"):
        name = t.get(f"{{{T}}}name")
        rows = []
        for row in t.findall(f"{{{T}}}table-row"):
            rrep = int(row.get(f"{{{T}}}number-rows-repeated", "1"))
            cells = []
            for cell in row:
                if not (cell.tag.endswith("}table-cell") or cell.tag.endswith("}covered-table-cell")):
                    continue
                crep = int(cell.get(f"{{{T}}}number-columns-repeated", "1"))
                txt = "\n".join("".join(p.itertext()) for p in cell.findall(f"{{{TX}}}p"))
                val = cell.get(f"{{{O}}}value")
                out = val if (val is not None and txt == "") else txt
                if crep > 500:
                    crep = 1
                cells.extend([out] * crep)
            while cells and cells[-1] == "":
                cells.pop()
            if rrep > 100:
                rrep = 1
            rows.extend([list(cells)] * rrep)
        while rows and not rows[-1]:
            rows.pop()
        sheets[name] = rows
    return sheets


def cell(row, i):
    return row[i].strip() if i < len(row) else ""


def num(s):
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    try:
        f = float(s)
        return int(f) if f == int(f) else round(f, 2)
    except ValueError:
        return None


def parse_voeding(rows, label):
    plan = {"name": label, "kcal": None, "macros": [], "meals": []}
    header_idx = None
    cols = {}
    for idx, row in enumerate(rows):
        c1 = cell(row, 1)
        if c1 == "Kcal":
            nums = [num(c) for c in row[2:] if num(c) is not None]
            plan["kcal"] = nums[0] if nums else None
        elif c1 in ("Koolhydraten", "Eiwitten", "Vetten"):
            vals = [c.strip() for c in row[2:] if c.strip()]
            pct = vals[0] if vals else ""
            nums = [num(v) for v in vals[1:] if num(v) is not None]
            plan["macros"].append({
                "name": c1, "pct": pct,
                "kcal": nums[0] if len(nums) > 0 else None,
                "gram": nums[1] if len(nums) > 1 else None,
            })
        elif c1 == "Maaltijd #":
            header_idx = idx
            for j, c in enumerate(row):
                cols[c.strip()] = j
            break
    if header_idx is None:
        return plan

    ci = {
        "num": cols.get("Maaltijd #", 1), "product": cols.get("Product", 3),
        "qty": cols.get("Hoeveelheid", 6), "unit": cols.get("Eenheid", 7),
        "kcal": cols.get("kcal", 8), "e": cols.get("e", 9),
        "k": cols.get("k", 10), "v": cols.get("v", 11),
    }
    meal = None
    for row in rows[header_idx + 1:]:
        qty_c = cell(row, ci["qty"]).lower()
        prod = cell(row, ci["product"])
        note = " ".join(cell(row, j) for j in range(ci["product"] + 1, ci["qty"]) if cell(row, j)).strip()
        label_c = cell(row, ci["num"])

        if qty_c in ("totaal", "energie %"):
            if meal is None:
                continue
            vals = {k: num(cell(row, ci[k])) for k in ("kcal", "e", "k", "v")}
            if qty_c == "totaal":
                meal["total"] = vals
            else:
                meal["energyPct"] = {k: cell(row, ci[k]) for k in ("e", "k", "v")}
                if meal["total"] and meal["total"]["kcal"]:
                    plan["meals"].append(meal)
                meal = None
            continue

        n = num(label_c)
        if n is not None and meal is None:
            meal = {"num": int(n), "title": [], "items": [], "total": None, "energyPct": None}
        if meal is None:
            continue
        if label_c and num(label_c) is None:
            meal["title"].append(label_c)
        # kolommen tussen num en product kunnen ook titeltekst bevatten (bv. 'Tussendoor')
        for j in range(ci["num"] + 1, ci["product"]):
            extra = cell(row, j)
            if extra and extra not in meal["title"]:
                meal["title"].append(extra)

        name = prod or note
        if name:
            meal["items"].append({
                "product": prod or note,
                "note": note if prod else "",
                "qty": num(cell(row, ci["qty"])),
                "unit": cell(row, ci["unit"]).replace("-", "").strip() or None,
                "kcal": num(cell(row, ci["kcal"])) or 0,
                "e": num(cell(row, ci["e"])) or 0,
                "k": num(cell(row, ci["k"])) or 0,
                "v": num(cell(row, ci["v"])) or 0,
            })
    for m in plan["meals"]:
        # ruis wegfilteren: verwijzingen naar websites en delen die een eerder deel herhalen
        parts = []
        for t in m["title"]:
            t = re.sub(r"\s*kijk op.*$", "", t, flags=re.I).strip()
            if not t:
                continue
            if any(t.lower().startswith(p.lower()) for p in parts):
                continue
            parts.append(t)
        m["title"] = " · ".join(parts)
    # Header-kcal in de sheet is onderhoud (2451), niet wat ze eet.
    # Dagtotaal = som van de maaltijden (~1900).
    meal_kcal = [m["total"]["kcal"] for m in plan["meals"] if m.get("total") and m["total"].get("kcal")]
    if meal_kcal:
        plan["kcal"] = int(round(sum(meal_kcal)))
    return plan


def parse_calorie_table(rows):
    items = []
    for row in rows:
        if len(row) < 4:
            continue
        prod = cell(row, 0)
        kcal = num(cell(row, 3))
        if not prod or kcal is None or prod.lower() in ("product", "producten"):
            continue
        items.append({
            "product": prod, "qty": num(cell(row, 1)), "unit": cell(row, 2),
            "kcal": kcal, "e": num(cell(row, 4)) or 0, "k": num(cell(row, 5)) or 0, "v": num(cell(row, 6)) or 0,
        })
    items.sort(key=lambda x: x["product"].lower())
    return items


def main():
    base = Path(__file__).parent
    sheets = read_sheets(base / ODS_FILE)
    data = {
        "voeding": [
            parse_voeding(sheets.get(f"VOEDING {i}", []), f"Schema {i}") for i in (1, 2, 3)
        ],
        "calorieTable": parse_calorie_table(sheets.get("Calorietabel", [])),
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    html_path = base / HTML_FILE
    html = html_path.read_text(encoding="utf-8")
    new_html, n = re.subn(
        r'(<script id="fitdata" type="application/json">).*?(</script>)',
        lambda m: m.group(1) + payload + m.group(2),
        html,
        flags=re.S,
    )
    if n != 1:
        sys.exit("Kon het fitdata-blok niet vinden in index.html")
    html_path.write_text(new_html, encoding="utf-8")
    print(f"OK: {sum(len(v['meals']) for v in data['voeding'])} maaltijden, "
          f"{len(data['calorieTable'])} producten -> {HTML_FILE}")


if __name__ == "__main__":
    main()
