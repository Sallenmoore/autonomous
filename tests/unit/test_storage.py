from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous import log


class TestStorage:
    def test_cloudinary(self):
        storage = CloudinaryStorage()

        asset_id_1 = storage.save("tests/assets/testimg.png")
        log(asset_id_1)
        assert asset_id_1["asset_id"]
        assert asset_id_1["url"]
        assert not asset_id_1["raw"]

        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_2 = storage.save(filedata)
        log(asset_id_2)
        assert asset_id_2
        assert asset_id_2["asset_id"]
        assert asset_id_2["url"]
        assert not asset_id_2["raw"]

        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_3 = storage.save(filedata, folder="test/subtest")
        log(asset_id_3)
        assert asset_id_3
        assert asset_id_3["asset_id"]
        assert asset_id_3["url"]
        assert not asset_id_3["raw"]

        url = storage.geturl(asset_id_1["asset_id"])
        log(url)
        assert "res.cloudinary.com/" in url
        url = storage.geturl(asset_id_2["asset_id"])
        log(url)
        assert "res.cloudinary.com/" in url
        url = storage.geturl(asset_id_3["asset_id"])
        log(url)
        assert "res.cloudinary.com/" in url

        storage.remove(asset_id_1["asset_id"])
        storage.remove(asset_id_2["asset_id"])
        storage.remove(asset_id_3["asset_id"])
