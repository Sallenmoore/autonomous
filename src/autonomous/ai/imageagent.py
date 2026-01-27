import os

from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class ImageAgent(BaseAgent):
    name = StringAttr(default="imageagent")

    # Force this agent to use Gemini
    provider = StringAttr(default="gemini")

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating images."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating images."
    )

    def generate(
        self,
        prompt,
        negative_prompt="",
        aspect_ratio="Portrait",
        files=None,
    ):
        return self.get_client(
            os.environ.get("IMAGE_AI_AGENT", self.provider)
        ).generate_image(
            prompt,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt,
            files=files,
        )
