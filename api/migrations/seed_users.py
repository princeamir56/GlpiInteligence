"""Seed one API user per role for testing.

Creates (idempotently, via upsert) three users with bcrypt-hashed passwords. The
default passwords are DEV-ONLY and documented in the README — change them in prod.

Run (from the GlpiInteligence/ dir, with POSTGRES_URL set):
    python -m api.migrations.seed_users
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from api.database import dispose_engine, get_sessionmaker
from api.security import hash_password

# (username, plaintext password, role) — DEV DEFAULTS ONLY.
SEED_USERS = [
    ("dsi@sartex", "dsi-dev-password", "DSI"),
    ("manager@sartex", "manager-dev-password", "MANAGER"),
    ("direction@sartex", "direction-dev-password", "DIRECTION"),
]


async def seed() -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        for username, password, role in SEED_USERS:
            await session.execute(
                text(
                    "INSERT INTO api_users (username, password_hash, role) "
                    "VALUES (:u, :p, :r) "
                    "ON CONFLICT (username) DO UPDATE SET "
                    "password_hash = EXCLUDED.password_hash, role = EXCLUDED.role"
                ),
                {"u": username, "p": hash_password(password), "r": role},
            )
        await session.commit()
    await dispose_engine()
    print(f"Seeded {len(SEED_USERS)} users: " + ", ".join(u for u, _, _ in SEED_USERS))


if __name__ == "__main__":
    asyncio.run(seed())
