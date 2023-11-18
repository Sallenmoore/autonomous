import os

import cloudinary.api
import cloudinary.uploader

from autonomous import log


class CloudinaryStorage:
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

    def search(self, **kwargs):
        query = ""
        if name := kwargs.get("name"):
            query = f"{name}"
        if folder := kwargs.get("folder"):
            query += f" AND folder:{folder}" if query else f"folder:{folder}"
        return cloudinary.Search().expression(query).execute()

    def update(self, key, **kwargs):
        metadata = self.get_metadata(key)
        return cloudinary.api.update(metadata["public_id"], **kwargs)

    def geturl(self, key):
        response = self.get_metadata(key)
        return response.get("url")

    def save(self, file, **kwargs):
        if folder := kwargs.get("folder"):
            try:
                cloudinary.api.subfolders(f"{folder}")
            except cloudinary.exceptions.NotFound as e:
                # log(f"{e} -- Creating folder {folder}")
                cloudinary.api.create_folder(folder)
            finally:
                kwargs["asset_folder"] = folder

        try:
            response = cloudinary.uploader.upload(file, **kwargs)
        except Exception as e:
            log("Cloudinary Storage upload error")
            raise e
        #log(response)
        return {"asset_id": response["asset_id"], "url": response["url"]}

    def remove(self, asset_id, **kwargs):
        response = self.get_metadata(asset_id)
        cloudinary.uploader.destroy(response["public_id"], **kwargs)
