from autonomous import log
from .basestorage import Storage
import cloudinary.uploader
import cloudinary.api
import os


class CloudinaryStorage(Storage):
    cloud_name = os.getenv("CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_KEY")
    api_secret = os.getenv("CLOUDINARY_SECRET")
    secure = True

    def __init__(self):
        cloudinary.config(
            cloud_name=self.cloud_name,
            api_key=self.api_key,
            api_secret=self.api_secret,
            secure=True,
        )

    @classmethod
    def get_metadata(cls, asset_id):
        # log(cls.api_secret, cls.api_key, cls.cloud_name)
        return cloudinary.api.resource_by_asset_id(asset_id)

    def geturl(self, key):
        response = self.get_metadata(key)
        return response.get("url")

    def save(self, file, **kwargs):
        if folder := kwargs.get("folder"):
            try:
                cloudinary.api.subfolders(f"{folder}")
            except cloudinary.exceptions.NotFound as e:
                log(f"{e} -- Creating folder {folder}")
                cloudinary.api.create_folder(folder)
            finally:
                kwargs["asset_folder"] = folder

        try:
            response = cloudinary.uploader.upload(file, **kwargs)
        except Exception as e:
            log(f"Cloudinary Storage upload error: {e}")
            return {"asset_id": None, "url": None, "raw": file}

        return {"asset_id": response["asset_id"], "url": response["url"], "raw": None}

    def remove(self, key):
        response = self.get_metadata(key)
        cloudinary.uploader.destroy(response["public_id"])
