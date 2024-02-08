import json
import os
import random
import time
from base64 import b64decode

from openai import OpenAI

from autonomous import AutoModel, log


class AutoAgent(AutoModel):
    attributes = {
        "model": "gpt-4-turbo-preview",
        "name": None,
        "instructions": "You are a highly skilled AI trained to assist with various tasks.",
        "description": "An AI agent trained to assist with various tasks.",
        "tools": {},
        "file_ids": [],
        "agent_id": None,
        "thread_id": None,
    }

    _default_function = {
        "type": "function",
        "function": {
            "name": "response",
            "description": "Generate some content based on the user prompt",
            "parameters": {
                "type": "object",
                "required": [
                    "result",
                ],
                "properties": {
                    "prompt": {"type": "string", "description": "User prompt"},
                    "result": {
                        "type": "string",
                        "description": "Assistant generated content",
                    },
                },
            },
        },
    }

    _instructions_addition = """
        IMPORTANT: always use the function 'response' tool to respond to the user with the requested JSON schema. Never add any other text to the response.
        """

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))
        self.tools["function"] = {
            "type": "function",
            "function": kwargs["function"]
            if "function" in kwargs
            else self._default_function,
        }

        # if self._instructions_addition.strip() not in self.instructions:
        #     self.instructions += self._instructions_addition

        if not self.agent_id:
            agent = self.client.beta.assistants.create(
                instructions=self.instructions,
                description=self.description,
                name=self.name,
                tools=list(self.tools.values()),
                model=self.model,
            )
            self.agent_id = agent.id
        else:
            self.client.beta.assistants.update(
                self.agent_id,
                instructions=self.instructions,
                description=self.description,
                name=self.name,
                tools=list(self.tools.values()),
                model=self.model,
            )

    def _process_messages(self, messages):
        self.create_thread()
        for msg in messages:
            if isinstance(msg, str):
                msg = {"role": "user", "content": msg}

            if isinstance(msg, dict):
                self.client.beta.threads.messages.create(
                    thread_id=self.thread_id,
                    role=msg["role"],
                    content=msg["content"],
                )
            else:
                raise Exception(
                    f"==== Invalid message: {msg} ====\nMust be a string or dict - {{'role': 'user' or 'assistant', 'content': message}}."
                )

    def create_thread(self):
        if self.thread_id is None:
            thread = self.client.beta.threads.create()
            self.thread_id = thread.id
            self.save()

    def clear_files(self):
        for file_id in self.file_ids:
            self.client.beta.assistants.files.delete(
                assistant_id=self.agent_id, file_id=self.file_id
            )
            self.client.files.delete(file_id=self.file_id)
        self.file_ids = []
        self.tools.pop("retrieval", None)
        self.save()

    def add_files(self, files):
        self.clear_files()
        self.tools["retrieval"] = {"type": "retrieval"}
        self.client.beta.assistants.update(
            self.agent_id,
            tools=list(self.tools.values()),
        )
        for file_contents in files:
            file = self.client.files.create(file=file_contents, purpose="assistants")
            self.client.beta.assistants.files.create(
                assistant_id=self.agent_id, file_id=file.id
            )
            self.file_ids.append(file.id)
        self.save()

    def run(self, messages, files=None):
        self._process_messages(messages)
        if files:
            self.add_files(files)

        run = self.client.beta.threads.runs.create(
            thread_id=self.thread_id,
            assistant_id=self.agent_id,
            additional_instructions=self._instructions_addition,
        )

        while run.status in ["queued", "in_progress"]:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=self.thread_id,
                run_id=run.id,
            )
            log(f"==== Job Status: {run.status} ====")
            time.sleep(0.5)

        if run.status in ["failed", "expired", "canceled"]:
            log(f"==== Error: {run.last_error} ====")
            return None

        if run.status == "completed":
            response = self.client.beta.threads.messages.list(thread_id=self.thread_id)
            return response.data[0].content[0].text.value
        elif run.status == "requires_action":
            results = run.required_action.submit_tool_outputs.tool_calls[
                0
            ].function.arguments
            results = results[results.find("{") : results.rfind("}") + 1]
            return results
        else:
            log(f"====Status: {run.status} Error: {run.last_error} ====")
            return None


class OAIAgent(AutoModel):
    client = None

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))
        self.agents = {}

    def generate_json(
        self,
        text,
        functions,
        name="json_agent",
        primer_text="",
        file_data=None,
        context=[],
        description="",
    ):
        messages = [{"role": "user", "content": text}] + context
        agent = self.agents.get(name)
        if not agent:
            agent = AutoAgent(
                name=name,
                instructions=primer_text,
                messages=messages,
                function=functions,
            )
            agent.save()
            self.agents[name] = agent
            self.save()
        if file_data:
            agent.add_files(file_data)
        result = agent.run(messages)
        json_result = json.loads(result)
        return json_result

    def generate_text(
        self,
        text,
        name="text_agent",
        primer_text="",
        file_data=None,
        context=[],
        description="",
    ):
        messages = context + [{"role": "user", "content": text}]
        agent = self.agents.get(name)
        if not agent:
            agent = AutoAgent(
                name=name,
                instructions=primer_text,
                messages=messages,
            )
            agent.save()
            self.agents[name] = agent
            self.save()
        if file_data:
            agent.add_files(file_data)
        result = agent.run(messages)
        return result

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

    def summarize_text(self, text, primer=""):
        message = [
            {
                "role": "system",
                "content": f"You are a highly skilled AI trained in language comprehension and summarization.{primer}",
            },
            {"role": "user", "content": text},
        ]
        response = self.client.chat.completions.create(
            model="gpt-4", temperature=0, messages=message
        )
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return None

        return result
