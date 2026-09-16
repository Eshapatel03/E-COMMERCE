from services import ProductService

service = ProductService()

products = service.get_products()

print(products)
