"""The Power Automate Select mapping is production config that lives in Dataverse.

It is not reachable from the test suite, and when it silently omitted five fields
every readiness score in the CAL and PR batches was computed at the unknown-
confidence multiplier while the model was told nothing about sources. These tests
bind the committed contract to the Evidence model so the same class of omission
fails locally instead of invisibly in production.

Documentation and tests only: nothing here contacts Dataverse or Power Automate.
"""
import json
import pathlib
import unittest

from packages.outreach.qualify.qualification_core import Evidence

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts" / "evidence_field_mapping.json"


class EvidenceFieldMappingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.mapping = cls.contract["map"]

    def test_contract_file_is_present_and_well_formed(self):
        for key in ("flow", "action", "from", "map"):
            self.assertIn(key, self.contract)
        self.assertEqual(self.contract["action"], "Select")
        self.assertTrue(self.mapping)

    def test_every_mapped_key_is_a_real_evidence_field(self):
        unknown = sorted(set(self.mapping) - set(Evidence.model_fields))
        self.assertEqual(
            unknown, [],
            f"contract maps fields the Evidence model does not define: {unknown}")

    def test_every_evidence_field_is_represented(self):
        # The omission that caused the defect was a field the Function could accept
        # but the flow never sent, so full coverage is the assertion that matters.
        missing = sorted(set(Evidence.model_fields) - set(self.mapping))
        self.assertEqual(
            missing, [],
            f"Evidence fields absent from the Select mapping: {missing}. "
            "Add them to the flow and to the contract, or the Function will "
            "silently receive nothing for them.")

    def test_required_evidence_fields_are_mapped(self):
        required = sorted(
            name for name, f in Evidence.model_fields.items() if f.is_required())
        for name in required:
            self.assertIn(name, self.mapping, f"required Evidence field {name} is unmapped")

    def test_dataverse_columns_are_distinct_and_plausible(self):
        columns = list(self.mapping.values())
        self.assertEqual(len(columns), len(set(columns)), "a Dataverse column is mapped twice")
        for column in columns:
            self.assertTrue(column.startswith("new_"), f"unexpected column name: {column}")


if __name__ == "__main__":
    unittest.main()
