import pytest
import os
from autonomous.storage.localstorage import LocalStorage
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous.storage.s3storage import S3Storage
from autonomous import log


class TestStorage:
    def test_cloudinary(self):
        storage = CloudinaryStorage()

        asset_id_1 = storage.save("tests/assets/testimg.jpg")
        log(asset_id_1)
        assert asset_id_1

        filedata = open("tests/assets/testimg.jpg", "rb")
        asset_id_2 = storage.save(filedata)
        log(asset_id_2)
        assert asset_id_2

        filedata = open("tests/assets/testimg.jpg", "rb")
        asset_id_3 = storage.save(filedata, folder="test/subtest")
        log(asset_id_3)
        assert asset_id_3

        url = storage.geturl(asset_id_1)
        log(url)
        assert "res.cloudinary.com/" in url
        url = storage.geturl(asset_id_2)
        log(url)
        assert "res.cloudinary.com/" in url
        url = storage.geturl(asset_id_3)
        log(url)
        assert "res.cloudinary.com/" in url

        storage.remove(asset_id_1)
        storage.remove(asset_id_2)
        storage.remove(asset_id_3)
