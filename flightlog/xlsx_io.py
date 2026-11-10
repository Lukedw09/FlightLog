"""Read one worksheet into CSV text. Sheet choice is explicit."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO

from openpyxl import load_workbook

from flightlog.session import FormError


def sheet_names(data: bytes) -> list[str]:
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def sheet_to_csv(data: bytes, sheet: str) -> str:
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet not in workbook.sheetnames:
            names = ", ".join(workbook.sheetnames)
            raise FormError(f"No sheet named {sheet!r}. Sheets in this workbook: {names}.", "sheet")
        worksheet = workbook[sheet]
        buffer = StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        for row in worksheet.iter_rows(values_only=True):
            if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            writer.writerow(["" if cell is None else cell for cell in row])
        text = buffer.getvalue()
    finally:
        workbook.close()
    if not text.strip():
        raise FormError(f"Sheet {sheet!r} has no cells.", "sheet")
    return text
