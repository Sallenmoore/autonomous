import os
import uuid
import pytest

from autonomous import log
from autonomous.apis.wikijs import WikiJS


class TestWikiJS:
    def _get_page_data(self):
        return {
            "title": "test",
            "description": "this is a test page",
            "content": "this is a test page",
            "path": f"test/test-{uuid.uuid4()}",
            "tags": ["devtest"],
        }

    def test_pull_tagged(self):
        results = WikiJS.pull_tagged(["fishing"])
        log(results)
        for r in results:
            assert "fishing" in r.tags

        results = WikiJS.pull_tagged(["nothingtoseehere"])
        log(results)
        assert not results

    def test_get_page(self):
        results = WikiJS.pull_tagged(["garden"])
        for result in results:
            page = WikiJS.get_page(result.id)
            log(page)
            assert page

    def test_find_by_path(self):
        result = WikiJS.find_by_path("test/test")
        log(result)
        assert result

        result = WikiJS.find_by_path("test/sdagffssfsrgha")
        log(result)
        assert not result

    def test_create_page(self):
        markdown = """
        # Test
        this is a test page

        ## Subheading

        - let's make sure everything works
        """

        result = WikiJS.create_page(**self._get_page_data())
        log(result)
        assert result

    def test_update_page(self):
        page = WikiJS.create_page(**self._get_page_data())
        result = WikiJS.update_page(
            id=page.id,
            content=f"{page.content}\n-third",
            tags=["devtest", "devtest2"],
        )
        log(result)
        assert result

    def test_remove_page(self):
        self.test_create_page()
        for p in WikiJS.pull_tagged(["devtest"]):
            WikiJS.remove_page(p.id)
        assert not WikiJS.pull_tagged(["devtest"])
