from pathlib import Path


class LocalImageStorage:
    def __init__(self, images_dir):
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def save(self, filename, content):
        if Path(filename).name != filename:
            raise ValueError("Image filename must not contain a path")
        image_path = self.images_dir / filename
        image_path.write_bytes(content)
        return f"data/images/{filename}"

    def delete(self, image):
        prefix = "data/images/"
        if not image or not image.startswith(prefix):
            return
        image_path = self.images_dir / Path(image).name
        if image_path.is_file():
            image_path.unlink()