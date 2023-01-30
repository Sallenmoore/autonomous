import json
import os
import random
import shutil
from base64 import b64decode

import openai
import replicate
import requests
from utils import log


class Story:
    def __init__(self, prompt=None, characters=None):
        openai.api_key = os.environ.get("OPENAI_KEY")

        self.characters = characters or [
            "Nym Lenore: A Tall Dark Elf Monk Male who is clumsy, but good hearted",
            "Retta: A Young red-skinned Tiefling Female who is inexperienced, fierce, and devious",
            "Moose: A Muscular Green Half-Orc Barbarian Male with anger issues and fierce loyalty",
            "Zen: A Slim Half-Elf Ranger Male who is a bit of a mysterious loner, but kind and faithful",
            "Szardan: A Draugr Male who uses stealth and is greedy",
            "Emis: A small Druid who is a know-it-all and not a team player",
        ]
        self.party_image()

        self.prompt = (
            prompt
            or f"""
        Using this ragtag party of adventurers:
        {self.characters}
        In less than 150 words, write the first 2 paragraphs for a of an 80000 word D&D style fantasy novel with a secret villan that won't be revealed until the end.
        """
        )

        # Defaults
        self.update = ""
        self._summary = ""
        self.temp = 0.9

    def next_chapter(self, update="", token=500):
        self.update = update
        if update:
            self.prompt = f"""
                    Write the next 100 to 150 words, ending on a cliffhanger, of an 80000 word novel that advances the story for a D&D style novel with a villan that won't be revealed until much later. The current word count is {random.randrange(1000, 60000, 500)} and the story summary is:
                    {self.summary + update}
            """

        response = openai.Completion.create(
            model="text-davinci-003",
            prompt=self.prompt,
            temperature=self.temp,
            max_tokens=token,
        )
        self.prompt = response.get("choices")[0].get("text")
        self.generate_image(prompt=self.prompt, filename="current.png")

    @property
    def summary(self):
        if self.update and not self._summary:
            self.prompt = f"""{self.prompt}

            tl;dr
            """
            response = openai.Completion.create(
                model="text-curie-001",
                prompt=self.prompt,
                temperature=0.1,
                max_tokens=500,
            )
            self._summary = response.get("choices")[0].get("text")
        return self._summary

    def generate_image(
        self, prompt, size="256x256", base_image=None, filename="temp.png"
    ):

        model = replicate.models.get("stability-ai/stable-diffusion")
        version = model.versions.get(
            "f178fa7a1ae43a9a9af01b833b9d2ecf97b1bcb0acfd2dc5dd04895e042863f1"
        )
        urls = version.predict(prompt=prompt)
        log(urls)
        for i, url in enumerate(urls):
            response = requests.get(url, stream=True)
            with open(f"static/images/{filename}", "wb") as out_file:
                shutil.copyfileobj(response.raw, out_file)
            del response
        # try:
        #     if base_image:
        #         params["image"] = open(f"static/images/{base_image}", "rb")
        #         response = openai.Image.create_variation(**params)
        #     else:
        #         response = openai.Image.create(**params)
        # except Exception as e:
        #     log(f"Image Generation Failed: {e}")
        # else:
        #     for index, image_dict in enumerate(response["data"]):
        #         image_data = b64decode(image_dict["b64_json"])
        #         image_name = filename or f"ai_image{time.time()}.png"
        #         with open(f"static/images/{image_name}", mode="wb") as png:
        #             png.write(image_data)

    def party_image(self):

        prompt = "A portrait of a Dungeons and Dragon's fantasy adventuring group with the following characters:"

        for character in self.characters:
            prompt += f"""
                {character}
            """
        try:
            self.generate_image(prompt, filename="party.png")
        except Exception as e:
            log(f"Image Generation Failed: {e}")
