import io
import json
import os
import random
import time
from base64 import b64decode

import openai
from ollama import ChatResponse, chat

from autonomous import log
from autonomous.model.autoattr import DictAttr, ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class LocalAIModel(AutoModel):
    _client = None
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with various tasks."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with various tasks."
    )

    @property
    def client(self):
        if not self._client:
            self._client = "deepseek-r1"  # OpenAI(api_key=os.environ.get("OPENAI_KEY"))
        return self._client

    def clear_agent(self):
        pass

    def clear_agents(self):
        pass

        # def _get_agent_id(self):
        #     pass

        # def _add_function(self, user_function):
        pass

    def _format_messages(self, messages):
        pass

    def clear_files(self, file_id=None):
        pass

    def attach_file(self, file_contents, filename="dbdata.json"):
        pass

    def generate_json(self, messages, function, additional_instructions=""):
        message = messages + additional_instructions
        message += f"""
IMPORTANT: Respond in JSON FORMAT using the SCHEMA below. DO NOT add any text to the response outside of the supplied JSON schema:
{function}
"""
        response: ChatResponse = chat(
            model=self.client,
            messages=[
                {
                    "role": "user",
                    "content": message,
                },
            ],
        )
        return response.message.content

    def generate_text(self, messages, additional_instructions=""):
        message = messages + additional_instructions
        response: ChatResponse = chat(
            model=self.client,
            messages=[
                {
                    "role": "user",
                    "content": message,
                },
            ],
        )
        return response.message.content

    def generate_audio(self, prompt, **kwargs):
        raise NotImplementedError

    def generate_image(self, prompt, **kwargs):
        raise NotImplementedError

    def summarize_text(self, text, primer=""):
        response: ChatResponse = chat(
            model=self.client,
            messages=[
                {
                    "role": "system",
                    "content": f"You are a highly skilled AI trained in language comprehension and summarization.{primer}",
                },
                {"role": "user", "content": text},
            ],
        )
        return response.message.content
