from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous import log
import pytest


# @pytest.mark.skip(reason="OpenAI API is not free")
class TestStorage:
    def test_cloudinary_basic(self):
        storage = CloudinaryStorage()
        asset_id_1 = storage.save(
            "tests/assets/testimg.png",
        )
        log(asset_id_1)
        assert asset_id_1["asset_id"]
        assert asset_id_1["url"]
        assert not asset_id_1["raw"]

    def test_cloudinary_bytemode(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_2 = storage.save(filedata)
        log(asset_id_2)
        assert asset_id_2
        assert asset_id_2["asset_id"]
        assert asset_id_2["url"]
        assert not asset_id_2["raw"]

    def test_cloudinary_folders(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_3 = storage.save(filedata, folder="test/subtest")
        log(asset_id_3)
        assert asset_id_3
        assert asset_id_3["asset_id"]
        assert asset_id_3["url"]
        assert not asset_id_3["raw"]

    def test_cloudinary_options(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_3 = storage.save(filedata)
        log(asset_id_3)
        assert asset_id_3
        assert asset_id_3["asset_id"]
        assert asset_id_3["url"]
        assert not asset_id_3["raw"]

    def test_cloudinary_read(self):
        storage = CloudinaryStorage()
        asset_id_1 = storage.save("tests/assets/testimg.png", display_name="testimg")
        url = storage.geturl(asset_id_1["asset_id"])
        log(url)
        assert "res.cloudinary.com/" in url

    def test_cloudinary_search(self):
        storage = CloudinaryStorage()
        storage.save("tests/assets/testimg.png", display_name="testimg")
        results = storage.search("testimg", display_name="testimg")
        log(results)
        assert results

    def test_cloudinary_updatename(self):
        storage = CloudinaryStorage()
        asset_id_1 = storage.save("tests/assets/testimg.png")
        result = storage.update(asset_id_1["asset_id"], display_name="testupdate")
        log(result)
        assert result

    def test_cloudinary_delete(self):
        storage = CloudinaryStorage()
        asset_id_1 = storage.save("tests/assets/testimg.png")
        storage.remove(asset_id=asset_id_1["asset_id"])

        # Doesn't work for some reason
        # results = storage.search("testimg", display_name="testimg")
        # for r in results:
        #     storage.remove(r["asset_id"])

        # results = storage.search("testupdate", display_name="testupdate")
        # for r in results:
        #     storage.remove(r["asset_id"])
