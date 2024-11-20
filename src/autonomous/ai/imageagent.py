from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class ImageAgent(BaseAgent):
    name = StringAttr(default="imageagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating images."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating images."
    )

    def generate(self, prompt, **kwargs):
        return self.get_client().generate_image(prompt, **kwargs)
