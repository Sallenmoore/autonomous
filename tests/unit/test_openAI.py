import pytest

from autonomous.apis import OpenAI


@pytest.mark.skip(reason="costs money")
class TestOpenAI:
    def test_init(self):
        oai = OpenAI()
        assert oai

    def test_generate_image(self):
        oai = OpenAI()
        prompt = "The prettiest girl in the world named Natasha"
        oai.generate_image(prompt, size="256x256", path="tests/unit/imgs/", n=1)
