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
        img = oai.generate_image(prompt, size="256x256", n=1)
        assert isinstance(img, bytes)
        test_file = "tests/assets/testimg.png"
        test_file.write(img)
