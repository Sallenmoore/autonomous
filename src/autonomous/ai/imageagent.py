import os

from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class ImageAgent(BaseAgent):
    name = StringAttr(default="imageagent")

    provider = StringAttr(default="local")

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating images."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating images."
    )

    def generate(
        self,
        prompt,
        files=None,
        aspect_ratio="2KPortrait",
        style=None,
    ):
        # self.add_to_job_meta("prompt", prompt)
        return self.get_client(
            os.environ.get("IMAGE_AI_AGENT", self.provider)
        ).generate_image(
            prompt,
            aspect_ratio=aspect_ratio,
            files=files,
            style=style,
        )

    def upscale(
        self,
        prompt,
        image_content=None,
        aspect_ratio="2KPortrait",
        style=None,
    ):
        # self.add_to_job_meta("prompt", prompt)
        return self.get_client(
            os.environ.get("IMAGE_AI_AGENT", self.provider)
        ).upscale_image(
            prompt,
            image_content=image_content,
            aspect_ratio=aspect_ratio,
            style=style,
        )
