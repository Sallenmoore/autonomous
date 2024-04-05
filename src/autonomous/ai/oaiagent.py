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
        "model": "gpt-4-turbo-preview",
        "_agent_id": None,
        "messages": [],
        "tools": {},
        "name": "agent",
        "instructions": "You are highly skilled AI trained to assist with various tasks.",
        "description": "A helpful AI assistant trained to assist with various tasks.",
    }

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

    @property
    def agent_id(self):
        if not self._agent_id:
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

    def clear_files(self, file_id=None):
        assistant_files = self.client.beta.assistants.files.list(
            assistant_id=self.agent_id
        )
        log(f"==== Files: {assistant_files.data}")
        if file_ids := [o.id for o in assistant_files.data]:
            if file_id and file_id in file_ids:
                file_ids = [file_id]
            for file_id in file_ids:
                self.client.beta.assistants.files.delete(
                    assistant_id=self.agent_id, file_id=file_id
                )
                self.client.files.delete(file_id=file_id)
            self.tools.pop("retrieval", None)
            self.save()
        return self.client.files.list()

    def attach_file(self, file_contents, filename="dbdata.json"):
        self.tools["retrieval"] = {"type": "retrieval"}
        self.client.beta.assistants.update(
            self.agent_id,
            tools=list(self.tools.values()),
        )
        # file_contents = io.BytesIO(file_contents)
        file_obj = self.client.files.create(
            file=(filename, file_contents), purpose="assistants"
        )

        self.client.beta.assistants.files.create(
            assistant_id=self.agent_id, file_id=file_obj.id
        )
        self.save()
        return file_obj.id

    def _add_function(self, user_function):
        self.tools["function"] = {"type": "function", "function": user_function}
        self.client.beta.assistants.update(
            self.agent_id,
            tools=list(self.tools.values()),
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

    def generate(self, messages, function=None):
        _instructions_addition = self._add_function(function) if function else ""

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

        result = None
        if run.status == "completed":
            response = self.client.beta.threads.messages.list(thread_id=thread.id)
            result = response.data[0].content[0].text.value
        elif run.status == "requires_action":
            results = run.required_action.submit_tool_outputs.tool_calls[
                0
            ].function.arguments
            result = results[results.find("{") : results.rfind("}") + 1]
            log(f"====result: {result} ====")
            try:
                result = json.loads(result, strict=False)
            except Exception:
                if result:
                    result = (
                        f"Rewrite the following response as valid JSON: \n\n {result}"
                    )
                    response = self.client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a helpful AI assistant trained to take unstructured data strings and make them valid structured JSON data. While you try to minimized data loss, valid JSON is more important than data integrity.",
                            },
                            {"role": "user", "content": result},
                        ],
                    )
                    result = json.loads(result, strict=False)
        else:
            log(f"====Status: {run.status} Error: {run.last_error} ====")
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
        response = self.client.chat.completions.create(model="gpt-4", messages=message)
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return None

        return result
