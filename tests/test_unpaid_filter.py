import re
import unittest
from src.matching.hard_filter import _check_unpaid, _UNPAID_PATTERNS
from src.db.connection import execute_query

class TestUnpaidRule(unittest.TestCase):
    def test_unpaid_real_cases(self):
        # Must detect true unpaid cases
        res = _check_unpaid("(Unpaid) Mandatory Internship : Software Test", "Occibo is a SaaS platform...")
        self.assertFalse(res.passed)
        self.assertEqual(res.reason.value, "UNPAID")

        res = _check_unpaid("Inside Sales Contractor", "This is an unpaid internship position with commission only")
        self.assertFalse(res.passed)

        res = _check_unpaid("Software Engineer", "No compensation offered, equity only position.")
        self.assertFalse(res.passed)

        res = _check_unpaid("Frontend Dev", "Volunteer developer position with no salary")
        self.assertFalse(res.passed)

    def test_elevenlabs_paid_roles_never_flagged(self):
        # 1. Full-Stack Engineer (Backend Leaning) @ ElevenLabs (e76bb606-27f1-4231-88ff-9e6ebf6be84f)
        el1 = execute_query("SELECT title, description_text FROM jobs WHERE id = 'e76bb606-27f1-4231-88ff-9e6ebf6be84f'")[0]
        res1 = _check_unpaid(el1["title"], el1["description_text"])
        self.assertTrue(res1.passed, f"ElevenLabs backend role failed: {res1.detail}")

        # 2. Full-Stack Engineer - Productions @ ElevenLabs (2ac83bc9-3ce8-4f94-bf06-e50a9f755db3)
        el2 = execute_query("SELECT title, description_text FROM jobs WHERE id = '2ac83bc9-3ce8-4f94-bf06-e50a9f755db3'")[0]
        res2 = _check_unpaid(el2["title"], el2["description_text"])
        self.assertTrue(res2.passed, f"ElevenLabs productions role failed: {res2.detail}")

        # 3. Sticker Mule software engineer (ed1eb89e-7e80-4390-ac26-c762e563c10f)
        sm = execute_query("SELECT title, description_text FROM jobs WHERE id = 'ed1eb89e-7e80-4390-ac26-c762e563c10f'")[0]
        res_sm = _check_unpaid(sm["title"], sm["description_text"])
        self.assertTrue(res_sm.passed, f"Sticker Mule role failed: {res_sm.detail}")

if __name__ == "__main__":
    unittest.main()
