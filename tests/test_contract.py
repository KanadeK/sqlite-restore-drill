"""Requirements-derived tests for the public contract boundary."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from sqlite_restore_drill.core import ContractError, load_contract, validate_contract


class ContractValidationTests(unittest.TestCase):
    def test_default_is_a_versioned_contract(self):
        default = validate_contract(None)
        self.assertIsInstance(default, dict)
        self.assertEqual(default["version"], 1)

    def test_valid_contract_keeps_all_declared_requirements(self):
        contract = {
            "version": 1,
            "user_version": 7,
            "tables": {
                '库存 "items"': {
                    "min_rows": 0,
                    "max_rows": 10,
                    "required_columns": ["id", '列"名'],
                }
            },
        }
        original = copy.deepcopy(contract)
        validated = validate_contract(contract)
        self.assertEqual(validated["user_version"], 7)
        self.assertEqual(validated["tables"], contract["tables"])
        self.assertEqual(contract, original, "Validation must not rewrite caller data")

    def test_explicit_version_only_contract_is_valid(self):
        self.assertEqual(validate_contract({"version": 1})["version"], 1)

    def test_invalid_contracts_are_rejected_at_the_boundary(self):
        invalid = [
            {},
            [],
            "not an object",
            True,
            {"version": True},
            {"version": 1.0},
            {"version": 2},
            {"version": "1"},
            {"version": 1, "unknown": False},
            {"version": 1, "user_version": True},
            {"version": 1, "user_version": "7"},
            {"version": 1, "user_version": 7.0},
            {"version": 1, "tables": []},
            {"version": 1, "tables": None},
            {"version": 1, "tables": {"items": []}},
            {"version": 1, "tables": {"items": {"sql": "SELECT 1"}}},
            {"version": 1, "tables": {"items": {"min_rows": True}}},
            {"version": 1, "tables": {"items": {"max_rows": False}}},
            {"version": 1, "tables": {"items": {"min_rows": -1}}},
            {"version": 1, "tables": {"items": {"max_rows": -1}}},
            {"version": 1, "tables": {"items": {"min_rows": 1.5}}},
            {"version": 1, "tables": {"items": {"max_rows": "3"}}},
            {"version": 1, "tables": {"items": {"min_rows": 3, "max_rows": 2}}},
            {"version": 1, "tables": {"items": {"required_columns": "id"}}},
            {"version": 1, "tables": {"items": {"required_columns": ["id", "id"]}}},
            {"version": 1, "tables": {"items": {"required_columns": [1]}}},
            {"version": 1, "tables": {"items": {"required_columns": [True]}}},
            {"version": 1, "tables": {"items\x00other": {}}},
            {"version": 1, "tables": {"items": {"required_columns": ["id\x00x"]}}},
            {"version": 1, "tables": {1: {}}},
        ]
        for index, contract in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaises(ContractError):
                    validate_contract(contract)

    def test_type_error_does_not_disclose_rejected_values(self):
        secret = "PRIVATE_CONTRACT_VALUE_4a7cc09a"
        with self.assertRaises(ContractError) as caught:
            validate_contract({"version": 1, "tables": {"items": {"min_rows": secret}}})
        self.assertNotIn(secret, str(caught.exception))


class ContractFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "contract.json"

    def test_loads_utf8_contract_from_a_path(self):
        document = {
            "version": 1,
            "tables": {"库存": {"required_columns": ["编号"], "min_rows": 0}},
        }
        self.path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        loaded = load_contract(self.path)
        self.assertEqual(loaded["tables"], document["tables"])

    def test_duplicate_json_keys_are_never_silently_overridden(self):
        documents = [
            '{"version":1,"version":1}',
            '{"version":1,"tables":{"items":{},"items":{"min_rows":9}}}',
            '{"version":1,"tables":{"items":{"min_rows":0,"min_rows":2}}}',
        ]
        for index, document in enumerate(documents):
            with self.subTest(case=index):
                self.path.write_text(document, encoding="utf-8")
                with self.assertRaises(ContractError):
                    load_contract(self.path)

    def test_invalid_json_encoding_and_nonfinite_numbers_are_rejected(self):
        documents = [
            b"null",
            b"[]",
            b"true",
            b'{"version":1,',
            b'{"version":1,"user_version":NaN}',
            b'{"version":1,"user_version":Infinity}',
            b'{"version":1,"user_version":-Infinity}',
            b'{"version":1,"tables":{"\xff":{}}}',
            b'{"version":1} trailing bytes',
        ]
        for index, document in enumerate(documents):
            with self.subTest(case=index):
                self.path.write_bytes(document)
                with self.assertRaises(ContractError):
                    load_contract(self.path)

    def test_malformed_json_diagnostics_do_not_include_document_excerpt(self):
        secret = "PRIVATE_JSON_EXCERPT_a217ced4"
        self.path.write_text('{"version":1,"tables":' + secret, encoding="utf-8")
        with self.assertRaises(ContractError) as caught:
            load_contract(self.path)
        self.assertNotIn(secret, str(caught.exception))

    def test_oversized_numeric_token_is_a_contract_error(self):
        # Python versions with a JSON integer digit limit raise ValueError;
        # callers must still receive the documented contract error category.
        self.path.write_text('{"version":1,"user_version":' + "1" * 5000 + "}", encoding="utf-8")
        with self.assertRaises(ContractError):
            load_contract(self.path)


if __name__ == "__main__":
    unittest.main()
