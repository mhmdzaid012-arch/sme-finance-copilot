"""
Download the UCI "Online Retail II" dataset and turn it into daily sales.

    python scripts/uci_download.py

Source   https://archive.ics.uci.edu/dataset/502/online+retail+ii
Citation Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning
         Repository. https://doi.org/10.24432/C5CG6D
Licence  Creative Commons Attribution 4.0 International (CC BY 4.0)

A UK online gift-ware retailer, 1 December 2009 to 9 December 2011, about
1.07 million invoice lines. It is used for one purpose only: to test the SALES
part of the forecaster on data this team did not generate. It contains no
payouts, fees or bank balances, so it says nothing about the payout model.

The raw file is NOT committed. It is downloaded into data/external/ (which is
git-ignored) and only the cleaned daily series is written next to it.

Cleaning rules
--------------
  * drop cancellations (invoice number starts with "C")
  * drop lines with a quantity or a price of zero or less
  * drop non-product codes (postage, manual adjustments, bank charges, fees,
    samples, test rows): a product code is five digits, optionally followed by
    letters, e.g. 85123A
  * add up quantity x price per calendar day, and keep days with no sales as
    zero (the retailer is closed on Saturdays)

Standard library only: the .xlsx is read as the zip of XML files that it is,
so no extra dependency is needed.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "external"
URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
ZIP_PATH = OUT_DIR / "online_retail_ii.zip"
DAILY_PATH = OUT_DIR / "uci_online_retail_ii_daily.csv"
SUMMARY_PATH = OUT_DIR / "uci_online_retail_ii_cleaning.json"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]*$")
EXCEL_EPOCH = datetime(1899, 12, 30)


def download() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size > 1_000_000:
        print(f"already downloaded: {ZIP_PATH.name} ({ZIP_PATH.stat().st_size:,} bytes)")
        return
    print(f"downloading {URL}")
    request = urllib.request.Request(URL, headers={"User-Agent": "python-urllib"})
    with urllib.request.urlopen(request, timeout=120) as resp, ZIP_PATH.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    print(f"saved {ZIP_PATH.name} ({ZIP_PATH.stat().st_size:,} bytes)")


def _col(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def _rows(xlsx: zipfile.ZipFile):
    """Yield each data row of every sheet as {column letter: value}."""
    shared = []
    with xlsx.open("xl/sharedStrings.xml") as fh:
        for _, el in ET.iterparse(fh):
            if el.tag == NS + "si":
                shared.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    sheets = sorted(n for n in xlsx.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    for name in sheets:
        with xlsx.open(name) as fh:
            for _, el in ET.iterparse(fh):
                if el.tag != NS + "row":
                    continue
                row = {}
                for c in el.iter(NS + "c"):
                    v = c.find(NS + "v")
                    if v is None or v.text is None:
                        continue
                    row[_col(c.get("r"))] = shared[int(v.text)] if c.get("t") == "s" else v.text
                el.clear()
                yield row


def clean() -> dict:
    with zipfile.ZipFile(ZIP_PATH) as outer:
        inner_name = next(n for n in outer.namelist() if n.lower().endswith(".xlsx"))
        xlsx = zipfile.ZipFile(io.BytesIO(outer.read(inner_name)))

    counts = {"rows": 0, "header_rows": 0, "cancellations": 0, "non_positive_quantity": 0,
              "non_positive_price": 0, "non_product_code": 0, "unreadable": 0, "kept": 0}
    daily: dict[date, float] = {}
    # Columns: A Invoice, B StockCode, C Description, D Quantity, E InvoiceDate,
    #          F Price, G Customer ID, H Country
    for row in _rows(xlsx):
        counts["rows"] += 1
        invoice = str(row.get("A", ""))
        if invoice == "Invoice":
            counts["header_rows"] += 1
            continue
        try:
            qty, price = float(row["D"]), float(row["F"])
            day = (EXCEL_EPOCH + timedelta(days=float(row["E"]))).date()
        except (KeyError, ValueError):
            counts["unreadable"] += 1
            continue
        if invoice.upper().startswith("C"):
            counts["cancellations"] += 1
        elif qty <= 0:
            counts["non_positive_quantity"] += 1
        elif price <= 0:
            counts["non_positive_price"] += 1
        elif not PRODUCT_CODE.match(str(row.get("B", "")).strip()):
            counts["non_product_code"] += 1
        else:
            counts["kept"] += 1
            daily[day] = daily.get(day, 0.0) + qty * price

    first, last = min(daily), max(daily)
    days = [(first + timedelta(days=i)) for i in range((last - first).days + 1)]
    with DAILY_PATH.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "sales_gbp"])
        for d in days:
            w.writerow([d.isoformat(), f"{daily.get(d, 0.0):.2f}"])

    summary = {
        "source": URL, "licence": "CC BY 4.0", "doi": "10.24432/C5CG6D",
        "first_day": first.isoformat(), "last_day": last.isoformat(),
        "calendar_days": len(days),
        "days_with_no_sales": sum(1 for d in days if daily.get(d, 0.0) == 0.0),
        "total_sales_gbp": round(sum(daily.values()), 2),
        "line_counts": counts,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    download()
    print(json.dumps(clean(), indent=2))
    print(f"wrote {DAILY_PATH.relative_to(ROOT)}")
