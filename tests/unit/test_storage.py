import copy
import uuid

import pytest

from autonomous import log
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous.storage.markdown import MarkdownParser, Page


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


class ObjMD:
    model = {
        "title": "test",
        "description": "test",
        "tags": ["test"],
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


class TestMarkdownParser:
    """
    Parses a record into Markdown
    """

    model = ObjMD()

    def test_parse(self):
        result = MarkdownParser(self.model.serialize()).parse()
        log(result)
        assert "##" in result
        assert "-" in result


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

    def test_convert(self):
        """
        Converts the object to markdown
        """
        record = self.model.serialize()
        page = record.pop("title")
        assert Page.convert(record, page)

    def test_push(self):
        obj = ObjMD()
        pid = uuid.uuid4()
        result = Page.push(
            obj,
            title=f"test{pid}",
            path=f"test/test{pid}",
            descrption="test",
            tags=["test"],
        )
        log(result)
        assert result.id
        obj.model["title"] = "testupdate"
        result = Page.push(obj, obj.model["title"], id=result.id)
        log(result)
        assert result.id
