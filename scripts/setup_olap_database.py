import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import os
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("OLAP_POSTGRES_SERVER", "localhost")
user = os.getenv("OLAP_POSTGRES_USER", "postgres")
password = os.getenv("OLAP_POSTGRES_PASSWORD", "postgres")
port = int(os.getenv("OLAP_POSTGRES_PORT", "5432"))
target_db = os.getenv("OLAP_POSTGRES_DB", "aerolinea_olap")

print(f"Connecting to OLAP RDS postgres database on {host}...")
conn = psycopg2.connect(
    host=host,
    port=port,
    user=user,
    password=password,
    dbname="postgres",
    connect_timeout=15
)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
if not cur.fetchone():
    print(f"Creating database {target_db} on OLAP RDS...")
    cur.execute(f'CREATE DATABASE "{target_db}";')
    print(f"Database {target_db} created successfully!")
else:
    print(f"Database {target_db} already exists.")
cur.close()
conn.close()

# Conectar a la base de datos analítica y aplicar el DDL
print(f"Connecting to {target_db} and applying star schema DDL...")
conn_olap = psycopg2.connect(
    host=host,
    port=port,
    user=user,
    password=password,
    dbname=target_db,
    connect_timeout=15
)
cur_olap = conn_olap.cursor()
with open("scripts/olap_star_schema.sql", "r", encoding="utf-8") as f:
    sql = f.read()

cur_olap.execute(sql)
conn_olap.commit()
print("Star schema DDL applied successfully!")

cur_olap.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
tables = [r[0] for r in cur_olap.fetchall()]
print("OLAP Tables in database:", tables)

for t in tables:
    cur_olap.execute(f'SELECT count(*) FROM "{t}";')
    print(f"  {t}: {cur_olap.fetchone()[0]} rows")

cur_olap.close()
conn_olap.close()
