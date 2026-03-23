import psycopg2
import os
import re

SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI")


def _mask_uri(uri):
    """Replace the password in a DB URI with ***."""
    if not uri:
        return "(not set)"
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", uri)


def can_we_connect_to_postgres():
    try:
        connection = psycopg2.connect(SQLALCHEMY_DATABASE_URI)
        connection.close()
        return True
    except Exception as e:
        # Print error without leaking the full URI
        print(f"[ERROR] {type(e).__name__}: {str(e)[:200]}")
        return False


print(f"[INFO] Checking database connection: {_mask_uri(SQLALCHEMY_DATABASE_URI)}")
if not can_we_connect_to_postgres():
    print("[ERROR] Unable to connect to the database server")
    exit(1)
print("[INFO] Successfully connected to the database server")
exit(0)
