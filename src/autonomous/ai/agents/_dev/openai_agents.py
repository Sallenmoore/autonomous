import os
import random
import time
from base64 import b64decode

from openai import OpenAI

from autonomous import log


class OpenAIAgent:
    client = None

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))
        self.agents = {}

    def agent(self, name, instructions, messages=[], function=[], file=None):
        if self.agents.get(name):
            return self.agents[name]

        options = {
            "model": "gpt-4-turbo-preview",
            "name": name,
            "instructions": instructions,
            "messages": messages,
        }

        if function:
            options["tools"] = [
                {"type": "retrieval"},
                {"type": "function", "function": function},
            ]
            options["response_format"] = {"type": "json_object"}

        if file:
            file = self.client.files.create(file=open(file, "rb"), purpose="assistants")
            options["file_ids"] = [file.id]

        agent = self.client.beta.assistants.create(**options)
        thread = self.client.beta.threads.create(
            assistant_id=agent.id, messages=messages
        )

        run = self.client.beta.threads.runs.retrieve(thread_id=self.thread.id)
        while run.status != "completed":
            time.sleep(1)
            run = self.client.beta.threads.runs.retrieve(thread_id=self.thread.id)

        messages = self.client.beta.threads.messages.list(thread_id=thread.id)
        return messages[-1]

    def generate_audio(self, prompt, file_path, **kwargs):
        voice = kwargs.get("voice") or random.choice(
            ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        )
        response = self.client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=prompt,
        )

        response.stream_to_file(file_path)

    def generate_image(self, prompt, **kwargs):
        image = None
        try:
            response = self.client.images.generate(
                model="dall-e-3", prompt=prompt, response_format="b64_json", **kwargs
            )
            image_dict = response.data[0]
        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}")
        else:
            image = b64decode(image_dict.b64_json)
        return image

    def generate_json(self, text, functions, primer_text="", file=None, context=[]):
        messages = []
        for msg in context:
            message = {"role": "assistant", "content": msg}
            messages.append(message)

        agent = self.agent(
            "json",
            "Create a JSON object from the following text.",
            instructions=primer_text,
            messages=messages,
            function=functions,
            file=file,
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview", **json_data
            )
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = self.client.chat.completions.create(model="gpt-4", **json_data)
        try:
            result = response.choices[0].message.function_call.arguments
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None

        return result

    def generate_text(self, text, primer_text=""):
        json_data = {
            "messages": [
                {
                    "role": "system",
                    "content": primer_text,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ]
        }

        try:
            response = self.client.chat.completions.create(model="gpt-4", **json_data)
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo", **json_data
            )
        # breakpoint()
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None

        return result

    def summarize_text(self, text, primer=""):
        message = [
            {
                "role": "system",
                "content": f"You are a highly skilled AI trained in language comprehension and summarization.{primer}",
            },
            {"role": "user", "content": text},
        ]
        try:
            response = self.client.chat.completions.create(
                model="gpt-4", temperature=0, messages=message
            )
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = self.client.chat.completions.create(
                model="gpt-4", temperature=1, messages=message
            )
        # breakpoint()

        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return e

        return result
