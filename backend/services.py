import json
from pathlib import Path
from backend.models import Product


class ProductService:

    def __init__(self):
        self.data_dir = Path(__file__).resolve().parent / "data"
        self.file_path = self.data_dir / "product.json"
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def get_products(self):
        with open(self.file_path, "r") as file:
            products = json.load(file)

        return [Product(**product) for product in products]

    def get_product_by_id(self, product_id):
        products = self.get_products()

        for product in products:
            if product.id == product_id:
                return product

        return None

    def search_products(self, keyword=None, category=None):
        products = self.get_products()

        if keyword:
            keyword = keyword.lower()
            products = [
                product for product in products
                if keyword in product.name.lower()
            ]

        if category:
            products = [
                product for product in products
                if product.category.lower() == category.lower()
            ]

        return products

    def has_duplicate(self, name, category, exclude_id=None):
        normalized_name = name.strip().casefold()
        normalized_category = category.strip().casefold()
        return any(
            product.id != exclude_id
            and product.name.strip().casefold() == normalized_name
            and product.category.strip().casefold() == normalized_category
            for product in self.get_products()
        )

    def add_product(self, product):
        products = self.get_products()
        product.id = self._next_product_id(products)
        products.append(product)
        self._save_products(products)

        return product

    def update_product(self, product_id, name, category, price, stock, image=None):
        products = self.get_products()
        for product in products:
            if product.id == product_id:
                old_image = product.image
                product.name = name
                product.category = category
                product.price = price
                product.stock = stock
                if image is not None:
                    product.image = image
                self._save_products(products)
                if image is not None:
                    self._remove_local_image_if_unreferenced(old_image, products)
                return product
        return None

    def delete_product(self, product_id):
        products = self.get_products()
        remaining = [product for product in products if product.id != product_id]
        if len(remaining) == len(products):
            return None
        deleted_product = next(
            product for product in products if product.id == product_id
        )
        self._save_products(remaining)
        self._remove_local_image_if_unreferenced(deleted_product.image, remaining)
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

    @staticmethod
    def _next_product_id(products):
        used_ids = {product.id for product in products}
        next_id = 1

        while next_id in used_ids:
            next_id += 1

        return next_id

    def _save_products(self, products):
        with self.file_path.open("w") as file:
            json.dump(
                [product.__dict__ for product in products],
                file,
                indent=4
            )