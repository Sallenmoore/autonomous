# import os
# import uuid
# import pytest

# from autonomous import log
# from autonomous.storage.wikijs import WikiJS


# # class ObjMD:
# #     model = {
# #         "title": "test",
# #         "description": "test",
# #         "listitems": ["test"],
# #         "nesteditems": ["test", [1, 2, 3]],
# #         "content": {"test": "test"},
# #         "nested": {
# #             "test": {
# #                 "test": [
# #                     "test",
# #                     "test",
# #                     {"test": "test", "test2": "test"},
# #                     [1, 2, 3, {"test": "test"}],
# #                 ]
# #             }
# #         },
# #     }

# #     def serialize(self):
# #         return copy.deepcopy(self.model)


# # # @pytest.mark.skip(reason="Takes too long")
# # class TestPage:
# #     """
# #     Creates a Page object that can be converted to amrkdown and pushed to a wiki
# #     Object must be:
# #         - a dict
# #         - a class with a __dict__ attribute
# #         - a class with a serialize() method
# #     The default wiki is the built in WIkiJS container. Overwrite with your own wiki API by setting the `wiki_api` class attribute.
# #     Inherit from autonomous.wiki.Wiki abstract class for the required interface.
# #     """

# #     model = ObjMD()

# #     def test_parse(self):
# #         result = MarkdownParser(self.model.serialize()).parse()
# #         log(result)
# #         assert "##" in result
# #         assert "-" in result

# #     def test_convert(self):
# #         """
# #         Converts the object to markdown
# #         """
# #         record = self.model.serialize()
# #         assert Page.convert(record)

# #     def test_push(self):
# #         obj = ObjMD()
# #         pid = uuid.uuid4()
# #         result = Page.push(
# #             obj,
# #             title=f"test{pid}",
# #             path=f"test/test{pid}",
# #             description="test description",
# #             tags=["test"],
# #         )
# #         log(result)
# #         assert result.id
# #         obj.model["title"] = "testupdate"
# #         result = Page.push(obj, obj.model["title"], id=result.id)
# #         log(result)
# #         assert result.id

# #         result = Page.push(
# #             obj,
# #             title=f"test{pid}",
# #             path=f"test/test{pid}",
# #             description="test description",
# #             tags=["test"],
# #         )
# #         log(result)
# #         assert result.id


# @pytest.mark.skip(reason="Wiki module needs work")
# class TestWikiJS:
#     def _get_page_data(self):
#         return {
#             "title": "test",
#             "description": "this is a test page",
#             "content": "this is a test page",
#             "path": f"test/test-{uuid.uuid4()}",
#             "tags": ["devtest"],
#         }

#     def test_create_page(self):
#         result = WikiJS.create_page(**self._get_page_data())
#         log(result)
#         assert result

#     def test_pull_tagged(self):
#         results = WikiJS.pull_tagged(["fishing"])
#         log(results)
#         for r in results:
#             assert "fishing" in r.tags

#         results = WikiJS.pull_tagged(["nothingtoseehere"])
#         log(results)
#         assert not results

#     def test_get_page(self):
#         results = WikiJS.pull_tagged(["garden"])
#         for result in results:
#             page = WikiJS.get_page(result.id)
#             log(page)
#             assert page

#     def test_find_by_path(self):
#         data = self._get_page_data()
#         WikiJS.create_page(**data)
#         result = WikiJS.find_by_path(data["path"])
#         log(result)
#         assert result

#         result = WikiJS.find_by_path("test/sdagffssfsrgha")
#         log(result)
#         assert not result

#     def test_update_page(self):
#         page = WikiJS.create_page(**self._get_page_data())
#         result = WikiJS.update_page(
#             id=page.id,
#             content=f"{page.content}\n-third",
#             tags=["devtest", "devtest2"],
#         )
#         log(result)
#         assert result

#     def test_remove_page(self):
#         self.test_create_page()
#         for p in WikiJS.pull_tagged(["devtest"]):
#             WikiJS.remove_page(p.id)
#         assert not WikiJS.pull_tagged(["devtest"])
