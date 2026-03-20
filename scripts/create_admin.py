"""CLI script — create an admin user in the database.

Usage:
    JWT_SECRET=dev-secret uv run python scripts/create_admin.py --username admin --password secret

The script hashes the password with bcrypt (via auth_service) and inserts a row into
admin_users. It exits with a non-zero status code if the username already exists.
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal, engine
from app.models.admin import AdminUser
from app.services.auth_service import hash_password


def create_admin(username: str, password: str) -> AdminUser:
    """Create an admin user with a bcrypt-hashed password.

    Uses ``SessionLocal`` directly — no FastAPI dependency injection required.

    Args:
        username: The admin account username (must be unique).
        password: The plaintext password; stored as a bcrypt hash.

    Returns:
        The newly created ``AdminUser`` ORM instance (flushed, with id assigned).

    Raises:
        ValueError: If a user with *username* already exists.
    """
    # Ensure all tables exist (safe no-op if already present).
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
        )
        db.add(admin)
        db.flush()
        db.commit()
        db.refresh(admin)
        return admin
    except IntegrityError:
        db.rollback()
        raise ValueError(f"Admin user '{username}' already exists") from None
    finally:
        db.close()


def main() -> None:
    """Parse CLI arguments and create an admin user."""
    parser = argparse.ArgumentParser(description="Create a Lone Wolf admin user.")
    parser.add_argument("--username", required=True, help="Admin account username")
    parser.add_argument("--password", required=True, help="Admin account password")
    args = parser.parse_args()

    try:
        admin = create_admin(username=args.username, password=args.password)
        print(f"Admin user created: id={admin.id}, username={admin.username!r}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
