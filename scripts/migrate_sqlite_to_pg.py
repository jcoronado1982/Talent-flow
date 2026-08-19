#!/usr/bin/env python3
"""Migración de skill_demand y companies de SQLite a PostgreSQL.
Requiere:
  - psycopg2-binary (`pip install psycopg2-binary`)
  - acceso al archivo talentflow.db
"""
import sqlite3
import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_values

# ---------- Configuración ----------
SQLITE_PATH = Path(__file__).resolve().parents[1] / "talentflow.db"  # Ajusta si cambias la ubicación
POSTGRES_DSN = "host=localhost dbname=center_data user=admin password=admin123 port=5432"
# -----------------------------------

if not SQLITE_PATH.is_file():
    sys.stderr.write(f"❌ SQLite DB no encontrada en {SQLITE_PATH}\n")
    sys.exit(1)

# Conectar a SQLite
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()

# Conectar a PostgreSQL
pg_conn = psycopg2.connect(POSTGRES_DSN)
pg_cur = pg_conn.cursor()

# 1️⃣ Crear esquema en PostgreSQL (solo si no existe)
schema_sql = """
CREATE TABLE IF NOT EXISTS companies (
    name TEXT PRIMARY KEY,
    job_count INTEGER DEFAULT 1,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_demand (
    skill TEXT PRIMARY KEY,
    count INTEGER DEFAULT 0,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
pg_cur.execute(schema_sql)
pg_conn.commit()
print("✅ Esquema creado en PostgreSQL")

# 2️⃣ Migrar companies
sqlite_cur.execute("SELECT name, job_count, last_seen, created_at FROM companies")
companies = sqlite_cur.fetchall()
if companies:
    records = [(
        row["name"],
        row["job_count"] if row["job_count"] is not None else 1,
        row["last_seen"],
        row["created_at"]
    ) for row in companies]
    execute_values(
        pg_cur,
        "INSERT INTO companies (name, job_count, last_seen, created_at) VALUES %s ON CONFLICT (name) DO UPDATE SET job_count = EXCLUDED.job_count, last_seen = EXCLUDED.last_seen, created_at = EXCLUDED.created_at",
        records,
    )
    pg_conn.commit()
    print(f"✅ Migradas {len(records)} filas a companies")
else:
    print("⚠️ No se encontraron filas en companies")

# 3️⃣ Migrar skill_demand
sqlite_cur.execute("SELECT skill, count, last_seen FROM skill_demand")
skills = sqlite_cur.fetchall()
if skills:
    records = [(
        row["skill"],
        row["count"] if row["count"] is not None else 0,
        row["last_seen"]
    ) for row in skills]
    execute_values(
        pg_cur,
        "INSERT INTO skill_demand (skill, count, last_seen) VALUES %s ON CONFLICT (skill) DO UPDATE SET count = EXCLUDED.count, last_seen = EXCLUDED.last_seen",
        records,
    )
    pg_conn.commit()
    print(f"✅ Migradas {len(records)} filas a skill_demand")
else:
    print("⚠️ No se encontraron filas en skill_demand")

# Cerrar conexiones
sqlite_conn.close()
pg_cur.close()
pg_conn.close()
print("✅ Migración completada")
