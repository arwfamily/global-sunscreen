#!/usr/bin/env python3
"""
tests/test_ca_fetch_failure.py — a failed LNHPD read must never erase a product.

Regression for 2026-09-13: LNHPD did not answer during the rotation, the
failed calls came back as empty lists, 64 real sunscreens were stored with
zero actives, dropped by rescope_ca.py and published as "delisted".

Run:  python tests/test_ca_fetch_failure.py   (stdlib only, no network)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import collect_ca_lnhpd as ca  # noqa: E402

STORED = {"id": "CA:NPN-80093451", "actives": [{"name": "zinc oxide", "quantity": 22.5}]}


class FakeAPI:
    """Replaces ca.get. answers: {table: response or None (= failed call)}."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, path, tries=4):
        table = path.split("/")[0]
        self.calls.append(table)
        return self.answers.get(table), 0.0


class FetchFailure(unittest.TestCase):
    def setUp(self):
        self._get = ca.get

    def tearDown(self):
        ca.get = self._get

    def test_server_down_returns_none_not_empty(self):
        ca.get = FakeAPI({})  # every call fails, like 2026-09-13
        self.assertIsNone(ca.fetch_product(123))

    def test_one_failed_table_fails_the_whole_product(self):
        ca.get = FakeAPI({"medicinalingredient": [{"ingredient_name": "zinc oxide"}],
                          "nonmedicinalingredient": None,          # this one fails
                          "productroute": [], "productdose": []})
        self.assertIsNone(ca.fetch_product(123))

    def test_both_response_shapes_still_parse(self):
        ca.get = FakeAPI({"medicinalingredient": {"data": [{"ingredient_name": "zinc oxide"}]},
                          "nonmedicinalingredient": [{"ingredient_name": "water"}],
                          "productroute": {"data": []}, "productdose": []})
        med, non, rou, dos = ca.fetch_product(123)
        self.assertEqual(len(med), 1)
        self.assertEqual(len(non), 1)

    def test_empty_but_successful_answer_is_not_a_failure(self):
        ca.get = FakeAPI({"medicinalingredient": {"data": []},
                          "nonmedicinalingredient": [], "productroute": [], "productdose": []})
        self.assertEqual(ca.fetch_product(123), ([], [], [], []))


class NeverEraseActives(unittest.TestCase):
    def test_zero_actives_does_not_replace_a_stored_product(self):
        self.assertFalse(ca.safe_to_replace(STORED, {"id": STORED["id"], "actives": []}))

    def test_real_change_is_still_accepted(self):
        new = {"id": STORED["id"], "actives": [{"name": "zinc oxide", "quantity": 20.0}]}
        self.assertTrue(ca.safe_to_replace(STORED, new))

    def test_new_product_without_actives_is_accepted(self):
        # nothing stored to protect; rescope_ca keeps it and flags it
        self.assertTrue(ca.safe_to_replace(None, {"id": "CA:NPN-1", "actives": []}))


if __name__ == "__main__":
    unittest.main(verbosity=1)
