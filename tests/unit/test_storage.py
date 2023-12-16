import copy
import uuid
from urllib.parse import urlparse

import pytest
from autonomous import log
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous.storage.localstorage import LocalStorage
from autonomous.storage.markdown import MarkdownParser, Page


def is_url(s):
    try:
        result = urlparse(s)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


class TestCloudinaryStorage:
    def test_cloudinary_basic(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_2 = storage.save(filedata)
        log(asset_id_2)
        assert asset_id_2
        assert asset_id_2["asset_id"]
        assert asset_id_2["url"]

    def test_cloudinary_folders(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_3 = storage.save(filedata, folder="test/subtest")
        log(asset_id_3)
        assert asset_id_3
        assert asset_id_3["asset_id"]
        assert asset_id_3["url"]

    def test_cloudinary_options(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset_id_3 = storage.save(filedata)
        log(asset_id_3)
        assert asset_id_3
        assert asset_id_3["asset_id"]
        assert asset_id_3["url"]

    def test_cloudinary_read(self):
        storage = CloudinaryStorage()
        asset_id_1 = storage.save("tests/assets/testimg.png", display_name="testimg")
        url = storage.geturl(asset_id_1["asset_id"])
        log(url)
        assert "res.cloudinary.com/" in url

    def test_cloudinary_search(self):
        storage = CloudinaryStorage()
        storage.save("tests/assets/testimg.png", display_name="testimg")
        results = storage.search(folder="test", display_name="testimg")
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

    def test_cloudinary_move(self):
        storage = CloudinaryStorage()
        filedata = open("tests/assets/testimg.png", "rb")
        asset = storage.save(filedata, folder="test/subtest")
        asset = storage.move(asset["asset_id"], folder="test/subtest2")
        print(asset)
        assert "test/subtest2" in asset["url"]


class TestLocalStorage:
    def test_localstorage_basic(self):
        storage = LocalStorage()
        filedata = open("tests/assets/testimg.png", "rb").read()
        asset_id_2 = storage.save(
            filedata,
            file_type="png",
        )
        log(asset_id_2)
        assert asset_id_2
        assert asset_id_2["asset_id"]
        assert asset_id_2["url"]

    def test_localstorage_folders(self):
        storage = LocalStorage()
        filedata = open("tests/assets/testimg.png", "rb").read()
        asset_id_3 = storage.save(filedata, file_type="png", folder="test/subtest")
        log(asset_id_3)
        assert asset_id_3
        assert asset_id_3["asset_id"]
        assert asset_id_3["url"]

    def test_localstorage_read(self):
        storage = LocalStorage()
        filedata = open("tests/assets/testimg.png", "rb").read()
        asset_id_1 = storage.save(filedata, file_type="png", folder="tests/assets")
        url = storage.geturl(asset_id_1["asset_id"])
        log(asset_id_1, url)
        assert all([urlparse(url).scheme, urlparse(url).netloc])

    def test_localstorage_search(self):
        storage = LocalStorage()
        filedata = open("tests/assets/testimg.png", "rb").read()
        storage.save(filedata, file_type="png", folder="tests/assets")
        results = storage.search(folder="tests/assets")
        log(results)
        assert results

    def test_localstorage_delete(self):
        storage = LocalStorage()
        filedata = open("tests/assets/testimg.png", "rb").read()
        asset = storage.save(filedata, file_type="png", folder="tests/assets")
        storage.remove(asset_id=asset["asset_id"])
        assert not storage.get(asset["asset_id"])

    def test_localstorage_move(self):
        storage = LocalStorage()
        filedata = open("tests/assets/testimg.png", "rb").read()
        asset = storage.save(filedata, file_type="png", folder="test/subtest")
        asset = storage.move(asset["asset_id"], folder="test/subtest2")
        print(asset)
        assert "test/subtest2" in asset["url"]


class ObjMD:
    model = {
        "title": "test",
        "description": "test",
        "listitems": ["test"],
        "nesteditems": ["test", [1, 2, 3]],
        "content": {"test": "test"},
        "nested": {
            "test": {
                "test": [
                    "test",
                    "test",
                    {"test": "test", "test2": "test"},
                    [1, 2, 3, {"test": "test"}],
                ]
            }
        },
    }

    def serialize(self):
        return copy.deepcopy(self.model)


# @pytest.mark.skip(reason="Takes too long")
class TestPage:
    """
    Creates a Page object that can be converted to amrkdown and pushed to a wiki
    Object must be:
        - a dict
        - a class with a __dict__ attribute
        - a class with a serialize() method
    The default wiki is the built in WIkiJS container. Overwrite with your own wiki API by setting the `wiki_api` class attribute.
    Inherit from autonomous.wiki.Wiki abstract class for the required interface.
    """

    model = ObjMD()

    def test_parse(self):
        result = MarkdownParser(self.model.serialize()).parse()
        log(result)
        assert "##" in result
        assert "-" in result

    def test_convert(self):
        """
        Converts the object to markdown
        """
        record = self.model.serialize()
        assert Page.convert(record)

    def test_push(self):
        obj = ObjMD()
        pid = uuid.uuid4()
        result = Page.push(
            obj,
            title=f"test{pid}",
            path=f"test/test{pid}",
            description="test description",
            tags=["test"],
        )
        log(result)
        assert result.id
        obj.model["title"] = "testupdate"
        result = Page.push(obj, obj.model["title"], id=result.id)
        log(result)
        assert result.id

        result = Page.push(
            obj,
            title=f"test{pid}",
            path=f"test/test{pid}",
            description="test description",
            tags=["test"],
        )
        log(result)
        assert result.id
