import tempfile
import unittest
from pathlib import Path

from app import server


class FinanceServerTests(unittest.TestCase):
    def test_parse_single_expense(self):
        parsed = server.parse_command("刚刚停车112元，帮我记一下")
        self.assertEqual(parsed["transactions"][0]["amount"], 112)
        self.assertEqual(parsed["transactions"][0]["type"], "expense")
        self.assertEqual(parsed["transactions"][0]["category"], "交通")

    def test_demo_agent_keeps_provider_boundary(self):
        parsed = server.FINANCE_AGENT.parse("停车112元")
        self.assertTrue(server.FINANCE_AGENT.provider)
        self.assertEqual(parsed["transactions"][0]["category"], "交通")

    def test_parse_multiple_records_and_ledger(self):
        parsed = server.parse_command("创建2026账本，把停车费112元记录进去，再把4月份销冠奖金500元放进去")
        self.assertEqual(parsed["ledger"]["name"], "2026 账本")
        self.assertEqual(len(parsed["transactions"]), 2)
        self.assertEqual(parsed["transactions"][0]["category"], "交通")
        self.assertEqual(parsed["transactions"][1]["type"], "income")
        self.assertEqual(parsed["transactions"][1]["category"], "奖金")

    def test_dashboard_and_insight_are_data_driven(self):
        state = {
            "ledgers": [{"id": "ledger-1", "name": "2026 账本"}],
            "receipts": [],
            "transactions": [
                {"id": "a", "ledgerId": "ledger-1", "amount": 100, "type": "expense", "category": "餐饮", "note": "外卖", "date": "2026-06-02", "source": "manual"},
                {"id": "b", "ledgerId": "ledger-1", "amount": 220, "type": "expense", "category": "餐饮", "note": "外卖", "date": "2026-07-02", "source": "manual"},
                {"id": "c", "ledgerId": "ledger-1", "amount": 500, "type": "income", "category": "奖金", "note": "奖金", "date": "2026-07-03", "source": "manual"},
            ],
        }
        data = server.dashboard(state)
        self.assertEqual(data["spend"], 220)
        self.assertEqual(data["income"], 500)
        self.assertEqual(data["categories"]["餐饮"], 220)
        self.assertEqual(data["increase"], 120)
        answer = server.insights_answer(state, "为什么这个月花这么多？")
        self.assertEqual(answer["reasons"][0]["category"], "餐饮")
        self.assertIn("增加", answer["answer"])

    def test_empty_dashboard_can_answer_without_transactions(self):
        answer = server.insights_answer({"ledgers": [], "transactions": [], "receipts": []}, "为什么这个月花这么多？")
        self.assertEqual(answer["data"]["increase"], 0)
        self.assertIn("没有高于过去平均", answer["answer"])

    def test_json_persistence_and_receipt_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = (server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE)
            try:
                server.DATA_DIR = Path(temp_dir)
                server.UPLOADS_DIR = Path(temp_dir) / "uploads"
                server.STATE_FILE = Path(temp_dir) / "state.json"
                parsed = server.parse_command("停车112元")
                added = server.add_transactions(parsed)
                receipt = server.create_receipt({"filename": "小票.png", "data": "aGVsbG8=", "hint": "盒马268元"})
                state = server._read_state()
                self.assertEqual(len(added), 1)
                self.assertTrue(server.STATE_FILE.exists())
                self.assertTrue((server.UPLOADS_DIR / Path(receipt["url"]).name).exists())
                self.assertGreaterEqual(len(state["transactions"]), 10)
                self.assertEqual(state["receipts"][-1]["amount"], 268)
                updated = server.update_receipt(receipt["id"], {"merchant": "盒马鲜生", "amount": 269, "category": "购物", "date": "2026-07-27"})
                self.assertEqual(updated["amount"], 269)
                self.assertEqual(updated["merchant"], "盒马鲜生")
            finally:
                server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE = previous

    def test_existing_demo_state_materializes_linked_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = (server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE)
            try:
                server.DATA_DIR = Path(temp_dir)
                server.UPLOADS_DIR = Path(temp_dir) / "uploads"
                server.STATE_FILE = Path(temp_dir) / "state.json"
                state = server._seed_state()
                receipt = state["receipts"][0]
                receipt["filename"] = "盒马小票.png"
                receipt["url"] = ""
                receipt.pop("transactionId")
                server._write_state(state)

                migrated = server._read_state()
                migrated_receipt = migrated["receipts"][0]
                asset_path = server.UPLOADS_DIR / server.DEMO_RECEIPT_FILENAME

                self.assertEqual(migrated_receipt["url"], server.DEMO_RECEIPT_URL)
                self.assertEqual(migrated_receipt["transactionId"], "tx-seed-1")
                self.assertTrue(asset_path.exists())
                self.assertIn("演示凭证", asset_path.read_text(encoding="utf-8"))

                self.assertTrue(server.delete_transaction("tx-seed-1"))
                self.assertNotIn("transactionId", server._read_state()["receipts"][0])
            finally:
                server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE = previous

    def test_receipt_application_is_linked_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = (server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE)
            try:
                server.DATA_DIR = Path(temp_dir)
                server.UPLOADS_DIR = Path(temp_dir) / "uploads"
                server.STATE_FILE = Path(temp_dir) / "state.json"
                receipt = server.create_receipt({"filename": "盒马268元.png", "data": "aGVsbG8=", "hint": "盒马268元"})

                transaction, created = server.apply_receipt(receipt["id"])
                repeated, repeated_created = server.apply_receipt(receipt["id"])
                state = server._read_state()
                linked_receipt = next(item for item in state["receipts"] if item["id"] == receipt["id"])

                self.assertTrue(created)
                self.assertFalse(repeated_created)
                self.assertEqual(transaction["id"], repeated["id"])
                self.assertEqual(linked_receipt["transactionId"], transaction["id"])
                self.assertEqual(sum(item.get("receiptId") == receipt["id"] for item in state["transactions"]), 1)

                self.assertTrue(server.delete_transaction(transaction["id"]))
                refreshed_receipt = next(item for item in server._read_state()["receipts"] if item["id"] == receipt["id"])
                self.assertNotIn("transactionId", refreshed_receipt)
            finally:
                server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE = previous

    def test_transaction_edit_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = (server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE)
            try:
                server.DATA_DIR = Path(temp_dir)
                server.UPLOADS_DIR = Path(temp_dir) / "uploads"
                server.STATE_FILE = Path(temp_dir) / "state.json"
                added = server.add_transactions(server.parse_command("停车112元"))
                updated = server.update_transaction(added[0]["id"], {"amount": 118, "note": "新停车费"})
                self.assertEqual(updated["amount"], 118)
                self.assertEqual(updated["note"], "新停车费")
                self.assertIsNone(server.update_transaction("missing", {"note": "不存在"}))
                self.assertTrue(server.delete_transaction(updated["id"]))
                self.assertFalse(any(tx["id"] == updated["id"] for tx in server._read_state()["transactions"]))
                self.assertFalse(server.delete_transaction("missing"))
            finally:
                server.DATA_DIR, server.UPLOADS_DIR, server.STATE_FILE = previous


if __name__ == "__main__":
    unittest.main()
