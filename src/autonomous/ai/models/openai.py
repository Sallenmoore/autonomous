import io
import json
import os
import random
import time
from base64 import b64decode

import openai
from openai import NotFoundError as openai_NotFoundError
from openai import OpenAI

from autonomous import log
from autonomous.model.autoattr import DictAttr, ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class OpenAIModel(AutoModel):
    _client = None
    _text_model = "o3-mini"
    _image_model = "dall-e-3"
    _json_model = "gpt-4o"
    agent_id = StringAttr()
    messages = ListAttr(StringAttr(default=[]))
    tools = DictAttr()
    vector_store = StringAttr()
    name = StringAttr(default="agent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with various tasks."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with various tasks."
    )

    @property
    def client(self):
        if not self._client:
            self._client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))
        return self._client

    def delete(self):
        self.clear_files()
        if self.agent_id:
            try:
                self.client.beta.assistants.delete(self.agent_id)
            except openai_NotFoundError:
                log(f"==== Agent with ID: {self.agent_id} not found ====")
        return super().delete()

    def clear_agent(self):
        if self.agent_id:
            self.client.beta.assistants.delete(self.agent_id)
            self.agent_id = ""
            self.save()

    def clear_agents(self):
        assistants = self.client.beta.assistants.list().data
        if assistants:
            log(assistants)
            for assistant in assistants:
                log(f"==== Deleting Agent with ID: {assistant.id} ====")
                try:
                    self.client.beta.assistants.delete(assistant.id)
                except openai_NotFoundError:
                    log(f"==== Agent with ID: {assistant.id} not found ====")
            self.agent_id = ""
            self.save()

    def _get_agent_id(self):
        try:
            self.client.beta.assistants.retrieve(self.agent_id)
        except (ValueError, openai.NotFoundError) as e:
            log(f"{e} -- no agent found, creating a new one")
            agent = self.client.beta.assistants.create(
                instructions=self.instructions,
                description=self.description,
                name=self.name,
                model=self._json_model,
            )
            self.agent_id = agent.id
            log(f"==== Creating Agent with ID: {self.agent_id} ====")
            self.save()
        return self.agent_id

    def clear_files(self, file_id=None):
        if not file_id:
            for vs in self.client.vector_stores.list().data:
                try:
                    self.client.vector_stores.delete(vs.id)
                except openai_NotFoundError:
                    log(f"==== Vector Store {vs.id} not found ====")
            for sf in self.client.files.list().data:
                self.client.files.delete(file_id=sf.id)
        else:
            self.client.files.delete(file_id=file_id)
        self.tools.pop("file_search", None)
        self.save()
        return self.client.files.list()

    def attach_file(self, file_contents, filename="dbdata.json"):
        # Upload the user provided file to OpenAI
        self.tools["file_search"] = {"type": "file_search"}
        # Create a vector store
        try:
            if vs := self.client.vector_stores.list().data:
                self.vector_store = self.client.vector_stores.retrieve(
                    vector_store_id=vs[0].id
                ).id
            else:
                for sf in self.client.files.list().data:
                    self.client.files.delete(file_id=sf.id)
                raise FileNotFoundError("No vector store found")
        except FileNotFoundError:
            self.vector_store = self.client.vector_stores.create(
                name="World Reference",
                expires_after={"anchor": "last_active_at", "days": 14},
            ).id
        log(f"==== Vector Store ID: {self.vector_store}====", _print=True)
        # Attach File
        file_obj = self.client.files.create(
            file=(filename, file_contents), purpose="assistants"
        )
        log(f"==== FileStore ID: {file_obj.id}====", _print=True)
        self.client.vector_stores.files.create(
            vector_store_id=self.vector_store,
            file_id=file_obj.id,
        )
        self.client.beta.assistants.update(
            self._get_agent_id(),
            tools=list(self.tools.values()),
            tool_resources={"file_search": {"vector_store_ids": [self.vector_store]}},
        )
        self.save()
        return file_obj.id

    def _add_function(self, user_function):
        user_function["strict"] = True
        user_function["parameters"]["additionalProperties"] = False
        if not user_function["parameters"].get("required"):
            user_function["parameters"]["required"] = list(
                user_function["parameters"]["properties"].keys()
            )

        self.tools["function"] = {"type": "function", "function": user_function}
        self.client.beta.assistants.update(
            self._get_agent_id(), tools=list(self.tools.values())
        )
        return """
IMPORTANT: Always use the function 'response' tool to respond to the user with only the requested JSON schema. DO NOT add any text to the response outside of the JSON schema.

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

    def generate_json(self, messages, function, additional_instructions=""):
        # _instructions_addition = self._add_function(function)
        function["strict"] = True
        function["parameters"]["additionalProperties"] = False
        function["parameters"]["required"] = list(
            function["parameters"]["properties"].keys()
        )

        formatted_messages = self._format_messages(messages)
        thread = self.client.beta.threads.create(messages=formatted_messages)
        # log(function, _print=True)
        running_job = True
        while running_job:
            try:
                run = self.client.beta.threads.runs.create_and_poll(
                    thread_id=thread.id,
                    assistant_id=self._get_agent_id(),
                    additional_instructions=additional_instructions,
                    parallel_tool_calls=False,
                    tools=[
                        {"type": "file_search"},
                        {"type": "function", "function": function},
                    ],
                    tool_choice={
                        "type": "function",
                        "function": {"name": function["name"]},
                    },
                )
                log(f"==== Job Status: {run.status} ====", _print=True)
                if run.status in [
                    "failed",
                    "expired",
                    "canceled",
                    "completed",
                    "incomplete",
                    "requires_action",
                ]:
                    running_job = False

            except openai.BadRequestError as err:
                # Handle specific bad request errors
                log(f"==== Error: {err} ====", _print=True)
                if "already has an active run" in str(err):
                    log("Previous run is still active. Waiting...", _print=True)
                    time.sleep(2)  # wait before retrying or checking run status
                else:
                    raise err

        # while run.status in ["queued", "in_progress"]:
        #     run = self.client.beta.threads.runs.retrieve(
        #         thread_id=thread.id,
        #         run_id=run.id,
        #     )
        #     time.sleep(0.5)
        if run.status in ["failed", "expired", "canceled"]:
            log(f"==== !!! ERROR !!!: {run.last_error} ====", _print=True)
            return None
        log("=================== RUN COMPLETED ===================", _print=True)
        # log(run.status, _print=True)
        if run.status == "completed":
            response = self.client.beta.threads.messages.list(thread_id=thread.id)
            results = response.data[0].content[0].text.value
        elif run.status == "requires_action":
            results = run.required_action.submit_tool_outputs.tool_calls[
                0
            ].function.arguments
        else:
            log(f"====Status: {run.status} Error: {run.last_error} ====", _print=True)
            return None

        results = results[results.find("{") : results.rfind("}") + 1]
        try:
            results = json.loads(results, strict=False)
        except Exception:
            log(f"==== Invalid JSON:\n{results}", _print=True)
            return {}
        else:
            # log(f"==== Results: {results}", _print=True)
            # log("=================== END REPORT ===================", _print=True)
            return results

    def generate_text(self, messages, additional_instructions=""):
        self._get_agent_id()
        formatted_messages = self._format_messages(messages)
        thread = self.client.beta.threads.create(messages=formatted_messages)

        run = self.client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self._get_agent_id(),
            additional_instructions=additional_instructions,
            parallel_tool_calls=False,
        )

        while run.status in ["queued", "in_progress"]:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )
            time.sleep(0.5)
            log(f"==== Job Status: {run.status} ====", _print=True)

        if run.status in ["failed", "expired", "canceled"]:
            log(f"==== Error: {run.last_error} ====", _print=True)
            return None
        # log("=================== RUN COMPLETED ===================", _print=True)
        # log(run.status, _print=True)
        if run.status == "completed":
            response = self.client.beta.threads.messages.list(thread_id=thread.id)
            results = response.data[0].content[0].text.value
        else:
            log(f"====Status: {run.status} Error: {run.last_error} ====", _print=True)
            return None

        # log(results, _print=True)
        # log("=================== END REPORT ===================", _print=True)
        return results

    def generate_audio(self, prompt, **kwargs):
        voice = kwargs.get("voice") or random.choice(
            [
                "alloy",
                "ash",
                "ballad",
                "coral",
                "echo",
                "fable",
                "onyx",
                "nova",
                "sage",
                "shimmer",
            ]
        )
        response = self.client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=prompt,
        )
        # log(response, _print=True)
        return response.read()

    def generate_audio_text(self, audio_file, **kwargs):
        response = self.client.audio.transcriptions.create(
            model="gpt-4o-transcribe", file=audio_file, language="en", **kwargs
        )
        log(response, _print=True)
        return response.text

    def generate_image(self, prompt, **kwargs):
        image = None
        try:
            response = self.client.images.generate(
                model=self._image_model,
                prompt=prompt,
                response_format="b64_json",
                **kwargs,
            )
            image_dict = response.data[0]
        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}", _print=True)
            raise e
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
            model=self._text_model, messages=message
        )
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return None

        return result
