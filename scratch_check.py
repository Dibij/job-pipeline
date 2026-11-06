import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from src.db.docker_control import ensure_docker_and_postgres
ensure_docker_and_postgres()
import psycopg

db_url = f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ.get('POSTGRES_HOST','localhost')}:{os.environ.get('POSTGRES_PORT','5432')}/{os.environ['POSTGRES_DB']}"
conn = psycopg.connect(db_url)
with conn.cursor() as cur:
    # All guideline versions
    cur.execute("SELECT label_guideline_version, label, COUNT(DISTINCT job_id) FROM laya_labels GROUP BY label_guideline_version, label ORDER BY label_guideline_version, label")
    print("Labels by guideline_version:")
    for r in cur.fetchall(): print(f"  version={r[0]!r:30} label={r[1]:15} distinct_jobs={r[2]}")

    # Gold: v2_role_fit_only
    cur.execute("SELECT label, COUNT(DISTINCT job_id) FROM laya_labels WHERE label_guideline_version='v2_role_fit_only' GROUP BY label ORDER BY label")
    print("\nv2_role_fit_only gold:")
    for r in cur.fetchall(): print(f"  {r[0]}: {r[1]} distinct jobs")

    cur.execute("SELECT COUNT(DISTINCT job_id) FROM laya_labels WHERE label_guideline_version='v2_role_fit_only'")
    total = cur.fetchone()[0]
    print(f"\nTotal distinct gold jobs: {total}")
    print(f"Gate status: {total}/150 labels, check good_fit separately")

conn.close()
