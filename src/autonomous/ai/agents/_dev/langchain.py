import os
from base64 import b64decode

from autonomous import log
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, PromptTemplate
from langchain.schema import HumanMessage, SystemMessage
from openai import OpenAI


class LangChainAgent:
    client = None
    # msg_types = {"human": HumanMessage, "system": "system", "agent": "agent"}

    def __init__(self, **kwargs):
        self.client = ChatOpenAI(api_key=os.environ.get("OPENAI_KEY"))
        self.messages = []
        self.agents = []

    def add_message(self, content, msg_type="human"):
        msg = self.msg_types.get(msg_type, HumanMessage)(content=content)
        self.messages.append(msg)
        return msg

    def add_agent(self, agent):
        self.client = agent

    # ************************************************************#
    # *  Generation Methods                                      *#
    # ************************************************************#

    def generate_image(self, prompt="", **kwargs):
        if prompt:
            self.add_message(prompt)

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

    def generate_json(self, text, functions, primer_text=""):
        json_data = {
            # "response_format":{ "type": "json_object" },
            "messages": [
                {
                    "role": "system",
                    "content": f"{primer_text}. Your output must be a JSON object.",
                },
                {
                    "role": "user",
                    "content": text,
                },
            ]
        }

        if isinstance(functions, (list, tuple)):
            json_data.update({"functions": functions})
        elif functions is not None:
            json_data.update({"function_call": {"name": functions["name"]}})
            json_data.update({"functions": [functions]})

        # try:
        response = self.client.chat.completions.create(model="gpt-4", **json_data)
        # except Exception as e:
        #     log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
        #     response = self.client.chat.completions.create(
        #         model="gpt-3.5-turbo", **json_data
        #     )
        # breakpoint()
        try:
            result = response.choices[0].message.function_call.arguments
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None

        return result

    def generate_text(self, prompt="", primer_text=""):
        if prompt:
            self.add_message(prompt)
        json_data = {
            "messages": [
                {
                    "role": "system",
                    "content": primer_text,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        }

        try:
            response = self.client.predict_messages(self.messages)
            self.messages = []
            result = response.content
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None
        else:
            self.messages = []
        return result

    def summarize_text(self, text):
        prompt = [
            SystemMessage(
                content="You are a highly skilled AI trained in language comprehension and summarization. You will summarize text ensuring that you maintain the key elements of the otiginal and as well as any important context.",
                additional_kwargs={},
            ),
            HumanMessage(
                content=f"Summarize the following text: {text}", example=False
            ),
        ]

        try:
            response = self.client.predict_messages(prompt)
            result = response.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return e
        else:
            self.messages = []

        return result
