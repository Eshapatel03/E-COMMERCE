import json
from decimal import Decimal
from pathlib import Path

from backend.database import get_connection, initialize_database


def import_json_data():
    data_dir = Path(__file__).resolve().parent / "data"
    with (data_dir / "product.json").open(encoding="utf-8") as file:
        products = json.load(file, parse_float=Decimal)
    with (data_dir / "users.json").open(encoding="utf-8") as file:
        users = json.load(file)

    initialize_database()
    with get_connection() as connection:
        for product in products:
            connection.execute(
                """
                INSERT INTO products (id, name, category, price, stock, image)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    product["id"],
                    product["name"],
                    product["category"],
                    product["price"],
                    product["stock"],
                    product["image"],
                ),
            )
        for user in users:
            connection.execute(
                """
                INSERT INTO users (id, name, email, password, role)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    user["id"],
                    user["name"],
                    user["email"],
                    user["password"],
                    user["role"],
                ),
            )
        for table in ("products", "users"):
            connection.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE(MAX(id), 1),
                    COUNT(*) > 0
                ) FROM {table}
                """
            )

    print(f"Imported {len(products)} products and {len(users)} users.")


if __name__ == "__main__":
    import_json_data()