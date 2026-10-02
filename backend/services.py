from pathlib import Path

from backend.database import get_connection
from backend.models import Product


class ProductService:

    def __init__(self):
        self.data_dir = Path(__file__).resolve().parent / "data"
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def get_products(self):
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name, category, price, stock, image "
                "FROM products ORDER BY id"
            ).fetchall()
        return [Product(**row) for row in rows]

    def get_categories(self):
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT category FROM products"
            ).fetchall()
        return sorted(row["category"] for row in rows)

    def get_product_by_id(self, product_id):
        with get_connection() as connection:
            row = connection.execute(
                "SELECT id, name, category, price, stock, image "
                "FROM products WHERE id = %s",
                (product_id,),
            ).fetchone()
        return Product(**row) if row is not None else None

    def search_products(self, keyword=None, category=None, page=1, page_size=8):
        filters = []
        parameters = []
        if keyword:
            filters.append("POSITION(LOWER(%s) IN LOWER(name)) > 0")
            parameters.append(keyword)
        if category:
            filters.append("LOWER(category) = LOWER(%s)")
            parameters.append(category)
        where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
        offset = (page - 1) * page_size

        with get_connection() as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS total FROM products" + where_clause,
                parameters,
            ).fetchone()["total"]
            rows = connection.execute(
                "SELECT id, name, category, price, stock, image FROM products"
                + where_clause
                + " ORDER BY id LIMIT %s OFFSET %s",
                (*parameters, page_size, offset),
            ).fetchall()
        return [Product(**row) for row in rows], total

    def has_duplicate(self, name, category, exclude_id=None):
        query = (
            "SELECT EXISTS (SELECT 1 FROM products "
            "WHERE LOWER(BTRIM(name)) = LOWER(BTRIM(%s)) "
            "AND LOWER(BTRIM(category)) = LOWER(BTRIM(%s))"
        )
        parameters = [name, category]
        if exclude_id is not None:
            query += " AND id <> %s"
            parameters.append(exclude_id)
        query += ") AS duplicate"
        with get_connection() as connection:
            row = connection.execute(query, parameters).fetchone()
        return row["duplicate"]

    def add_product(self, product):
        with get_connection() as connection:
            row = connection.execute(
                """
                INSERT INTO products (name, category, price, stock, image)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, category, price, stock, image
                """,
                (product.name, product.category, product.price, product.stock, product.image),
            ).fetchone()
        return Product(**row)

    def update_product(self, product_id, name, category, price, stock, image=None):
        with get_connection() as connection:
            current = connection.execute(
                "SELECT image FROM products WHERE id = %s", (product_id,)
            ).fetchone()
            if current is None:
                return None
            row = connection.execute(
                """
                UPDATE products
                SET name = %s, category = %s, price = %s, stock = %s,
                    image = COALESCE(%s, image)
                WHERE id = %s
                RETURNING id, name, category, price, stock, image
                """,
                (name, category, price, stock, image, product_id),
            ).fetchone()
            if row is None:
                return None
            remaining = connection.execute(
                "SELECT id, name, category, price, stock, image FROM products"
            ).fetchall()
        if image is not None:
            self._remove_local_image_if_unreferenced(
                current["image"],
                [Product(**item) for item in remaining],
            )
        return Product(**row)

    def delete_product(self, product_id):
        with get_connection() as connection:
            deleted_product = connection.execute(
                "DELETE FROM products WHERE id = %s "
                "RETURNING id, name, category, price, stock, image",
                (product_id,),
            ).fetchone()
            if deleted_product is None:
                return None
            remaining = connection.execute(
                "SELECT id, name, category, price, stock, image FROM products"
            ).fetchall()
        self._remove_local_image_if_unreferenced(
            deleted_product["image"], [Product(**item) for item in remaining]
        )
        return True

    def save_product_image(self, filename, content):
        image_path = self.images_dir / filename
        image_path.write_bytes(content)
        return f"data/images/{filename}"

    def _remove_local_image_if_unreferenced(self, image, products):
        prefix = "data/images/"
        if not image or not image.startswith(prefix):
            return
        if any(product.image == image for product in products):
            return
        image_path = self.images_dir / Path(image).name
        if image_path.is_file():
            image_path.unlink()
