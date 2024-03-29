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
    def _get_key(cls, folder="", pkey=None):
        if folder and not folder.endswith("/"):
            folder = f"{folder}/"
        folder = f"{folder.replace('/', '.')}{pkey or uuid.uuid4()}"
        return f"{folder}"

    def _resize_image(self, asset_id, max_size=1024):
        # log("Resizing image", asset_id, max_size)
        file_path = f"{self.get_path(asset_id)}/orig.webp"
        with Image.open(file_path) as img:
            resized_img = img.copy()
            max_size = self._sizes.get(max_size) or int(max_size)
            resized_img.thumbnail((max_size, max_size))
            img_byte_arr = io.BytesIO()
            resized_img.save(img_byte_arr, format="WEBP")
            return img_byte_arr.getvalue()

    def _convert_image(self, raw, crop=False):
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
            width, height = img.size
            if crop and width != height:
                max_size = min(width, height)
                img.crop(
                    (
                        (width - max_size) / 2,
                        (height - max_size) / 2,
                        (width + max_size) / 2,
                        (height + max_size) / 2,
                    )
                )
            img = img.copy()
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="WEBP")
            return img_byte_arr.getvalue()

    def save(self, file, folder="", crop=False):
        asset_id = self._get_key(folder)
        os.makedirs(self.get_path(asset_id), exist_ok=True)
        file_path = f"{self.get_path(asset_id)}/orig.webp"
        with open(file_path, "wb") as asset:
            file = self._convert_image(file, crop=crop)
            asset.write(file)
        return asset_id

    def get_url(self, asset_id, size="orig", full_url=False):
        # log(f"Getting image: {asset_id}.{size}")
        if not asset_id:
            return ""
        original_path = f"{self.get_path(asset_id)}"
        # log(f"Getting image: {asset_id}.{size}", original_path)
        if not os.path.exists(original_path):
            # log(f"Original image not found: {original_path}")
            return ""
        file_path = f"{original_path}/{size}.webp"
        # log(file_path)
        if (
            size != "orig"
            and os.path.exists(original_path)
            and not os.path.exists(file_path)
        ):
            # If the file doesn't exist, create it
            result = self._resize_image(asset_id, size)
            with open(file_path, "wb") as asset:
                asset.write(result)
        result_url = (
            f"/{file_path}"
            if not full_url
            else f"{os.environ.get('APP_BASE_URL', '')}/{file_path}"
        )
        # log(f"Returning image url: {result_url}")
        return result_url

    def get_path(self, asset_id):
        if asset_id:
            asset_path = asset_id.replace(".", "/")
            if asset_path.endswith("/"):
                asset_path = asset_path[:-1]
            return os.path.join(self.base_path, f"{asset_path}")
        else:
            return self.base_path

    def search(self, folder="", **kwargs):
        imgs = []
        # log(f"{self.base_path}")
        for f in os.listdir(f"{self.base_path}/{folder}"):
            # log(f"{self.base_path}/{folder}/{f}")
            for img in os.listdir(f"{self.base_path}/{folder}/{f}"):
                img_key = self._get_key(
                    f"{folder}",
                    pkey=f,
                )
                imgs.append(img_key)
        # log(imgs)
        return imgs

    def remove(self, asset_id):
        file_path = self.get_path(asset_id)
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
            return True
        return False
