"""Refusals for hostile or oversized tables. Not a claim of a sandbox."""

from __future__ import annotations

import pytest

from flightlog.import_csv import inspect_csv
from flightlog.session import FormError


def test_null_byte_is_refused():
    with pytest.raises(FormError, match="null byte"):
        inspect_csv("time_s,altitude_m\n0,1\n1,\0")


def test_too_many_columns_are_refused():
    header = ",".join(f"c{i}" for i in range(129))
    row = ",".join("1" for _ in range(129))
    with pytest.raises(FormError, match="128"):
        inspect_csv(header + "\n" + row + "\n" + row + "\n")


def test_a_formula_is_not_evaluated_as_a_number():
    from flightlog.session import import_mapped_csv

    text = "t_s,alt_m\n0,=1+1\n1,2\n2,3\n"
    with pytest.raises(FormError, match="not a finite number"):
        import_mapped_csv(
            text,
            {
                "delimiter": "comma",
                "header": "present",
                "provenance": "imported",
                "time_basis": "keep",
                "time": {"index": 0, "unit": "s"},
                "altitude": {"index": 1, "unit": "m", "reference": "agl"},
            },
        )
