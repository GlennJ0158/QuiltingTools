import tempfile
import unittest
from pathlib import Path

from quilting.database import Database
from quilting.model import FieldError
from tests.test_blocks import block, part
from tests.test_inventory import fabric


class QuiltPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "quilt.db")
        self.block_id = self.db.add_block(block())
        self.db.save_block_part(self.block_id, 1, part())
        placements = self.db.block_placements(self.block_id)
        self.db.save_block_placement(self.block_id, 2, placements[1]["ID"], 5_000_000, 0, 0, False)
        self.db.approve_block(self.block_id, 3)
        self.quilt_id = self.db.add_quilt("Test quilt")
        self.db.set_quilt_use(self.quilt_id, 1, self.block_id, 2)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_multiple_parts_share_small_source_and_inventory_is_unchanged(self):
        small = self.db.save_piece(fabric(FabricName="Small", Color="Red", UsableWidth="12", UsableLength="22"))
        large = self.db.save_piece(fabric(FabricName="Large", Color="Red", UsableWidth="100", UsableLength="100"))
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        before = self.db.pieces()
        plan_id = self.db.create_quilt_plan(self.quilt_id, 3)
        plan = self.db.get_quilt_plan(plan_id)["PlanData"]
        self.assertEqual(plan["part_count"], 4)
        self.assertEqual(plan["missing"], [])
        self.assertEqual([entry["source"]["ID"] for entry in plan["sources"]], [small])
        self.assertEqual(len(plan["sources"][0]["cuts"]), 4)
        self.assertEqual(self.db.pieces(), before)
        self.assertEqual(self.db.get_piece(large)["Revision"], 1)
        cuts = plan["sources"][0]["cuts"]
        for i, cut in enumerate(cuts):
            for other in cuts[:i]:
                overlap = (cut["x"] < other["x"] + other["source_width"]
                           and other["x"] < cut["x"] + cut["source_width"]
                           and cut["y"] < other["y"] + other["source_length"]
                           and other["y"] < cut["y"] + cut["source_length"])
                self.assertFalse(overlap)

    def test_unmapped_and_insufficient_fabric_produce_saved_partial_plan(self):
        self.db.save_piece(fabric(Color="Red", UsableWidth="6", UsableLength="11"))
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 2))["PlanData"]
        self.assertEqual(plan["missing"][0]["count"], 4)
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 3))["PlanData"]
        self.assertEqual(len(plan["sources"][0]["cuts"]), 1)
        self.assertEqual(plan["missing"][0]["count"], 3)

    def test_quilts_share_approved_version_and_conflicts_are_rejected(self):
        second = self.db.add_quilt("Another")
        self.db.set_quilt_use(second, 1, self.block_id, 1)
        self.assertEqual(self.db.quilt_uses(second)[0]["ID"], self.block_id)
        with self.assertRaises(FieldError):
            self.db.set_quilt_use(self.quilt_id, 1, self.block_id, 3)
        draft = self.db.copy_block(self.block_id)
        with self.assertRaises(FieldError):
            self.db.set_quilt_use(second, 2, draft, 1)
        with self.assertRaises(FieldError):
            self.db.add_quilt_mapping(second, 2, "Red", "not in inventory")
