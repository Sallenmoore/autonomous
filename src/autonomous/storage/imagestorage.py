import io
import os
import shutil
import uuid

from PIL import Image

from autonomous import log


class ImageStorage:
    _sizes = {"thumbnail": 100, "small": 300, "medium": 600, "large": 1000}

    def __init__(self, path="static/images"):
        self.base_path = path

    @classmethod
    def _create_key(cls, folder="", image_type="webp"):
        if folder:
            return f"{folder.replace('/', '.')}.{uuid.uuid4()}.{image_type}"
        else:
            return f"{uuid.uuid4()}.{image_type}"

    def _resize_image(self, asset_id, max_size):
        img_type = self.get_img_type(asset_id)
        file_path = f"{self.get_path(asset_id)}/orig.{img_type}"
        with Image.open(file_path) as img:
            max_size = self._sizes.get(max_size) or int(max_size)
            resized_img = img.copy()
            resized_img.thumbnail((max_size, max_size))
            img_byte_arr = io.BytesIO()
            resized_img.save(img_byte_arr, format="WEBP")
            return img_byte_arr.getvalue()

    def save(self, file, image_type="webp", folder=""):
        asset_id = self._create_key(folder, image_type)
        os.makedirs(self.get_path(asset_id), exist_ok=True)
        file_path = f"{self.get_path(asset_id)}/orig.{image_type}"
        with open(file_path, "wb") as asset:
            asset.write(file)
        return asset_id

    def get_url(self, asset_id, size="orig", full_url=False):
        original_path = f"{self.get_path(asset_id)}/orig.{self.get_img_type(asset_id)}"
        if not os.path.exists(original_path):
            log(f"Original image not found: {original_path}")
            return ""

        file_path = f"{self.get_path(asset_id)}/{size}.{self.get_img_type(asset_id)}"
        if not os.path.exists(file_path):
            # If the file doesn't exist, create it
            result = self._resize_image(asset_id, size)
            with open(file_path, "wb") as asset:
                asset.write(result)

        return (
            f"/{file_path}"
            if not full_url
            else f"{os.environ.get('APP_BASE_URL', '')}/{file_path}"
        )

    def get_path(self, asset_id):
        img_path, _ = asset_id.rsplit(".", maxsplit=1)
        asset_path = img_path.replace(".", "/")
        return os.path.join(self.base_path, asset_path)

    def get_img_type(self, asset_id):
        return asset_id.rsplit(".", maxsplit=1)[-1]

    def search(self, folder=None, **kwargs):
        imgs = []
        if folder:
            for f in os.listdir(f"{self.base_path}/{folder}"):
                imgs.append(self._create_key(f"{folder}/{f}"))
        return imgs

    def remove(self, asset_id):
        file_path = self.get_path(asset_id)
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
            return True
        return False
