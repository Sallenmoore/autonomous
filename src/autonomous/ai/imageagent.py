from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.ai.baseagent import BaseAgent
from .models.openai import OpenAIModel


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
