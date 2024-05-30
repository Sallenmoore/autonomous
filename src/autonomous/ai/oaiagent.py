import io
import json
import os
import random
import time
from base64 import b64decode

from openai import OpenAI

from autonomous import AutoModel, log


class OAIAgent(AutoModel):
    client = None
    attributes = {
        "model": "gpt-4o",
        "_agent_id": None,
        "messages": [],
        "tools": {},
        "vector_store": None,
        "name": "agent",
        "instructions": "You are highly skilled AI trained to assist with various tasks.",
        "description": "A helpful AI assistant trained to assist with various tasks.",
    }

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

    @property
    def agent_id(self):
        if not self._agent_id or not self.client.beta.assistants.retrieve(
            self._agent_id
        ):
            agent = self.client.beta.assistants.create(
                instructions=self.instructions,
                description=self.description,
                name=self.name,
                model=self.model,
            )
            self._agent_id = agent.id
            log(f"==== Creating Agent with ID: {self._agent_id} ====")
            self.save()
        return self._agent_id

    @agent_id.setter
    def agent_id(self, value):
        self._agent_id = value

    def clear_agent(self):
        self.client.beta.assistants.delete(self.agent_id)
        self.agent_id = ""

    def get_agent(self):
        return self.client.beta.assistants.retrieve(self.agent_id)

    def clear_files(self, file_id=None):
        if self.vector_store:
            if not file_id:
                vector_store_files = self.client.beta.vector_stores.files.list(
                    vector_store_id=self.vector_store
                ).data
                for vsf in vector_store_files:
                    self.client.files.delete(file_id=vsf["id"])
            else:
                self.client.files.delete(file_id=file_id)
            self.tools.pop("file_search", None)
            self.save()
        return self.client.files.list()

    def attach_file(self, file_contents, filename="dbdata.json"):
        # Upload the user provided file to OpenAI
        self.tools["file_search"] = {"type": "file_search"}
        # Create a vector store
        if not self.vector_store:
            vs = self.client.beta.vector_stores.list().data
            if vs:
                self.vector_store = vs[0].id
            else:
                self.vector_store = self.client.beta.vector_stores.create(
                    name="Data Reference"
                ).id

        file_obj = self.client.files.create(
            file=(filename, file_contents), purpose="assistants"
        )

        self.client.beta.vector_stores.files.create(
            vector_store_id=self.vector_store, file_id=file_obj.id
        )
        self.client.beta.assistants.update(
            self.agent_id,
            tools=list(self.tools.values()),
            tool_resources={"file_search": {"vector_store_ids": [self.vector_store]}},
        )
        self.save()
        return file_obj.id

    def _add_function(self, user_function):
        self.tools["function"] = {"type": "function", "function": user_function}
        self.client.beta.assistants.update(
            self.agent_id, tools=list(self.tools.values())
        )
        return """
        IMPORTANT: always use the function 'response' tool to respond to the user with the requested JSON schema. Never add any other text to the response.
        """

    def _format_messages(self, messages):
        message_list = []
        if isinstance(messages, str):
            message_list.insert(0, {"role": "user", "content": messages})
        else:
            for message in messages:
                if isinstance(message, str):
                    message_list.insert(0, {"role": "user", "content": message})
                else:
                    raise Exception(
                        f"==== Invalid message: {message} ====\nMust be a string "
                    )
        return message_list

    def generate(self, messages, function=None, additional_instructions=""):
        _instructions_addition = (
            self._add_function(function) if function else additional_instructions
        )

        formatted_messages = self._format_messages(messages)
        thread = self.client.beta.threads.create(messages=formatted_messages)

        run = self.client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self.agent_id,
            additional_instructions=_instructions_addition,
        )

        while run.status in ["queued", "in_progress"]:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )
            time.sleep(0.5)
            log(f"==== Job Status: {run.status} ====")

        if run.status in ["failed", "expired", "canceled"]:
            log(f"==== Error: {run.last_error} ====")
            return None

        if run.status == "completed":
            response = self.client.beta.threads.messages.list(thread_id=thread.id)
            result = response.data[0].content[0].text.value
        elif run.status == "requires_action":
            results = run.required_action.submit_tool_outputs.tool_calls[
                0
            ].function.arguments
            result = results[results.find("{") : results.rfind("}") + 1]
            try:
                result = json.loads(result, strict=False)
            except Exception:
                log(f"==== Invalid JSON:\n{result}")
        else:
            log(f"====Status: {run.status} Error: {run.last_error} ====")
            return None
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

        return response.stream_to_file(file_path)

    def generate_image(self, prompt, **kwargs):
        image = None
        try:
            response = self.client.images.generate(
                model="dall-e-3", prompt=prompt, response_format="b64_json", **kwargs
            )
            image_dict = response.data[0]
        except Exception as e:
            print(f"==== Error: Unable to create image ====\n\n{e}")
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
        response = self.client.chat.completions.create(model="gpt-4o", messages=message)
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return None

        return result
