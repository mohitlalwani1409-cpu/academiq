#!/usr/bin/env python3
"""
AcademiQ — Standalone CLI Admin Account Provisioning
Must be executed locally on the host machine.
Usage:
    python create_admin.py [username] [password]
    or interactively:
    python create_admin.py
"""

import sys
import getpass
import psycopg2
import bcrypt

PG_HOST = "127.0.0.1"
PG_PORT = 5433
PG_DB   = "academiq"
PG_USER = "postgres"
PG_PASS = "postgres"

def main():
    print("=== AcademiQ Admin Account Provisioning (Local CLI Only) ===")
    if len(sys.argv) >= 3:
        username = sys.argv[1].strip()
        password = sys.argv[2].strip()
    else:
        username = input("Enter admin username: ").strip()
        if not username:
            print("Error: Username cannot be empty.")
            sys.exit(1)
        password = getpass.getpass("Enter admin password: ").strip()
        confirm = getpass.getpass("Confirm admin password: ").strip()
        if password != confirm:
            print("Error: Passwords do not match.")
            sys.exit(1)

    if len(password) < 6:
        print("Error: Password must be at least 6 characters.")
        sys.exit(1)

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS
        )
    except Exception as e:
        print(f"Error connecting to PostgreSQL database: {e}")
        sys.exit(1)

    with conn.cursor() as cur:
        # 1. Ensure users table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role          VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 2. Ensure groups and group_members tables exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(100) UNIQUE NOT NULL,
                is_system   BOOLEAN NOT NULL DEFAULT FALSE,
                created_by  INT REFERENCES users(id) ON DELETE SET NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                id          SERIAL PRIMARY KEY,
                group_id    INT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                joined_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                CONSTRAINT uq_group_user UNIQUE (group_id, user_id)
            );
        """)

        # 3. Create or update admin user
        cur.execute("""
            INSERT INTO users (username, password_hash, role)
            VALUES (%s, %s, 'admin')
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                role = 'admin'
            RETURNING id;
        """, (username, hashed))
        user_id = cur.fetchone()[0]

        # 4. Ensure system 'Everyone' group exists and admin is a member
        cur.execute("""
            INSERT INTO groups (name, is_system, created_by)
            VALUES ('Everyone', TRUE, %s)
            ON CONFLICT (name) DO UPDATE SET is_system = TRUE
            RETURNING id;
        """, (user_id,))
        everyone_row = cur.fetchone()
        if everyone_row:
            everyone_group_id = everyone_row[0]
        else:
            cur.execute("SELECT id FROM groups WHERE name = 'Everyone';")
            everyone_group_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO group_members (group_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT (group_id, user_id) DO NOTHING;
        """, (everyone_group_id, user_id))

    conn.commit()
    conn.close()
    print(f"[OK] Admin user '{username}' (ID: {user_id}) successfully provisioned and enrolled in 'Everyone'.")

if __name__ == "__main__":
    main()
