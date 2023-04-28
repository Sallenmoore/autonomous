import pytest

from autonomous.apis import OpenDnD


class TestOpenDnD:
    def test_init(self):
        odnd = OpenDnD()
        print(odnd)

    def test_has_image(self):
        odnd = OpenDnD()
        assert (
            odnd.has_image("logo", path="tests/unit/imgs/")
            == "tests/unit/imgs/logo.png"
        )

        assert not odnd.has_image("not found", path="tests/unit/imgs/")

    def test_get_image(self):
        odnd = OpenDnD()
        assert (
            odnd.get_image("logo", path="tests/unit/imgs/")
            == "tests/unit/imgs/logo.png"
        )

        assert odnd.get_image("delete", path="tests/unit/imgs/")

    def test_search(self):
        odnd = OpenDnD()
        prompt = odnd.search("dragon", imgpath="tests/unit/imgs/")
        print(prompt)
        assert prompt
        prompt = odnd.search("sword", imgpath="tests/unit/imgs/")
        print(prompt)
        assert prompt
        prompt = odnd.search("fireball", imgpath="tests/unit/imgs/")
        print(prompt)
        assert prompt
        prompt = odnd.search("shield", imgpath="tests/unit/imgs/")
        print(prompt)
        assert prompt
