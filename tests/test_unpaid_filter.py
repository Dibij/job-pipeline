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
        """Paid roles whose JDs mention equity/benefits must not be flagged unpaid."""
        # Use live rows instead of hard-coded UUIDs so this regression test survives
        # a database rebuild; skip only if the sources are absent.
        queries = [
            ("ElevenLabs", "%Full-Stack Engineer%"),
            ("ElevenLabs", "%Infrastructure%"),
            ("Supabase", "%Engineer%"),
        ]
        rows = []
        for company, title in queries:
            found = execute_query(
                "SELECT title, description_text FROM jobs "
                "WHERE company_name ILIKE %s AND title ILIKE %s LIMIT 1;",
                (company, title),
            )
            if found:
                rows.append(found[0])
        if not rows:
            self.skipTest("No ElevenLabs/Supabase rows present in this database.")

        for row in rows:
            res = _check_unpaid(row["title"], row["description_text"])
            self.assertTrue(
                res.passed,
                f"Paid role incorrectly flagged: {row['title']} ({res.detail})",
            )

if __name__ == "__main__":
    unittest.main()
