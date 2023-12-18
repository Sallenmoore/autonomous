import os
import shutil
import uuid


class LocalStorage:
    def __init__(self, path="static"):
        self.base_path = path
        self.base_url = f"{os.getenv('APP_BASE_URL')}/{self.base_path}"

    def get(self, asset_id):
        if os.path.isfile(self.get_path(asset_id)):
            return {"asset_id": asset_id, "url": self.geturl(asset_id)}
        return None

    def _get_key(self, folder="", ext="", filename=None):
        if filename:
            return f"{folder}{'/' if folder else ''}{filename}"
        else:
            return f"{folder}{'/' if folder else ''}{uuid.uuid4()}.{ext.strip('.')}"

    def geturl(self, asset_id):
        return f"{self.base_url}/{asset_id}"

    def get_path(self, asset_id):
        return os.path.join(self.base_path, asset_id)

    def search(self, **kwargs):
        files = []
        if folder := kwargs.get("folder"):
            for f in os.listdir(f"{self.base_path}/{folder}"):
                if os.path.isfile(os.path.join(f"{self.base_path}/{folder}", f)):
                    asset_id = self._get_key(folder=folder, filename=f)
                    files.append(self.get(asset_id))
        elif asset_id := kwargs.get("asset_id"):
            if os.path.isfile(self.get_path(asset_id)):
                files.append(self.get(asset_id))
        return files

    def save(self, file, file_type, folder=""):
        os.makedirs(f"{self.base_path}{'/' if folder else ''}{folder}", exist_ok=True)
        asset_id = self._get_key(folder, file_type)

        with open(self.get_path(asset_id), "wb") as asset:
            asset.write(file)
        return {"asset_id": asset_id, "url": self.geturl(asset_id)}

    def move(self, asset_id, folder):
        new_asset_id = self._get_key(folder, asset_id.split(".")[-1])
        old_path = self.get_path(asset_id)
        new_path = os.path.join(self.base_path, new_asset_id)
        if os.path.isfile(old_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
            return self.get(new_asset_id)
        return False

    def remove(self, asset_id):
        file_path = self.get_path(asset_id)
        if os.path.isfile(file_path):
            os.remove(file_path)
            return True
        return False
