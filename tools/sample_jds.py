"""Sample raw JD text from the database to inform section extractor design."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.connection import execute_query

rows = execute_query("""
    SELECT j.title, j.description_text
    FROM jobs j
    WHERE j.nepal_accessible = true
      AND j.detected_language = 'english'
      AND LENGTH(j.description_text) > 300
    ORDER BY j.id
    LIMIT 5;
""")

for i, r in enumerate(rows, 1):
    title = r["title"]
    desc = (r["description_text"] or "")[:2000]
    print(f"\n{'='*70}")
    print(f"[{i}] {title}")
    print(f"{'='*70}")
    print(desc.encode("ascii", "replace").decode("ascii"))
    print()
