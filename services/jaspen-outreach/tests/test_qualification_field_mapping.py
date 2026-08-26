"""The Add-a-new-row mapping decides which Function outputs survive into Dataverse.

The A15 verdict was computed, returned, and then silently discarded for a whole
batch because this mapping predated the field: the gate fired, routed a prospect
to hold, and left no record of why. These tests bind the committed contract to
QualificationResponse so a field the engine produces cannot quietly stop being
stored.

Documentation and tests only: nothing here contacts Dataverse or Power Automate.
"""
import json
import pathlib
import unittest

from packages.outreach.qualify.qualification_core import QualificationResponse

CONTRACT = (pathlib.Path(__file__).resolve().parents[1]
            / "contracts" / "qualification_field_mapping.json")


class QualificationFieldMappingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.mapping = cls.contract["map"]
        cls.unmapped = cls.contract["unmapped_by_design"]
        cls.critical = cls.contract["must_never_be_dropped"]

    def test_contract_is_well_formed(self):
        self.assertEqual(self.contract["action"], "Add_a_new_row")
        self.assertEqual(self.contract["entity"], "new_qualifications")
        self.assertTrue(self.mapping)

    def test_every_mapped_key_is_a_real_response_field(self):
        unknown = sorted(set(self.mapping) - set(QualificationResponse.model_fields))
        self.assertEqual(
            unknown, [],
            f"contract maps outputs the response model does not define: {unknown}")

    def test_every_response_field_is_mapped_or_explicitly_excused(self):
        accounted = set(self.mapping) | set(self.unmapped)
        missing = sorted(set(QualificationResponse.model_fields) - accounted)
        self.assertEqual(
            missing, [],
            f"response fields neither mapped nor listed as unmapped_by_design: {missing}. "
            "Either map them in the flow and the contract, or record why they are "
            "deliberately not stored.")

    def test_a15_verdict_is_mapped(self):
        # The regression this file exists for.
        self.assertIn(
            "a15_deliberate_decision", self.mapping,
            "the A15 verdict must be persisted: it is the only record of why a hard-gated "
            "prospect was routed to hold")

    def test_critical_fields_are_all_mapped(self):
        for field in self.critical:
            self.assertIn(field, self.mapping, f"critical output {field} is unmapped")
            self.assertIn(field, QualificationResponse.model_fields,
                          f"critical output {field} is not a response field")

    def test_no_dataverse_column_is_written_twice(self):
        columns = list(self.mapping.values())
        dupes = sorted({c for c in columns if columns.count(c) > 1})
        self.assertEqual(dupes, [], f"columns mapped from more than one output: {dupes}")

    def test_columns_use_the_publisher_prefix(self):
        for column in self.mapping.values():
            self.assertTrue(column.startswith("new_"), f"unexpected column name: {column}")


if __name__ == "__main__":
    unittest.main()
