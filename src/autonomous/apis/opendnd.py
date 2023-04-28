import os
import random
from datetime import datetime
from urllib.parse import urlencode

import requests

from autonomous.logger import log

from ..apis import OpenAI

NUM_IMAGES = 1


class OpenDnD:
    """
    _summary_

    Returns:
        _type_: _description_
    """

    API_URL = "https://api.open5e.com/"

    @classmethod
    def _request(cls, url):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        response = requests.get(url)
        return response.json().get("results")

    @classmethod
    def get_count(cls, resource):
        """
        _summary_

        Returns:
            _type_: _description_
        """

    @classmethod
    def search(cls, key, imgpath="static/images/dnd", limit=0):
        results = []
        url = f"{cls.API_URL}search/?name={key}"
        res = cls._request(url)
        if not limit:
            limit = NUM_IMAGES
        for i, r in enumerate(res):
            print(r)
            r["image"] = cls.get_image(r["name"], path=imgpath)
            results.append(r)
            if i >= limit:
                break
        return results

    @classmethod
    def has_image(cls, fname, path="static/images/dnd"):
        items = os.listdir(path)
        random.shuffle(items)
        for i in items:
            if fname in i:
                return f"{path}{i}"

    @classmethod
    def get_image(
        cls,
        name,
        description="preparing for battle",
        setting="ancient arena",
        path="static/images/dnd",
    ):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        name = name.replace(" ", "").lower()
        img_file = cls.has_image(name, path)
        print(img_file)
        if not img_file:
            prompt = f"A 3d animated style portrait of a {name} from Dungeons and Dragons Fifth Edition in a {setting} setting {description}"
            try:
                resp = OpenAI().generate_image(
                    prompt,
                    path=f"{path}{name}-{datetime.now().toordinal()}.png",
                )
                img_file = resp[0]
            except Exception as e:
                log(e)
        return img_file

        # @classmethod

    # def get_monsters(cls, **kwargs):
    #     results = []
    #     url = f"{cls.API_URL}/monsters"
    #     cr_range = range(int(kwargs.get("crmin", 0)), int(kwargs.get("crmax", 20)) + 1)
    #     crs = ",".join([str(i) for i in cr_range])
    #     mob_list = cls._request(url + f"?challenge_rating={crs}")["results"]
    #     number = kwargs.get("number", 1)
    #     for _ in range(int(number)):
    #         mob = random.choice(mob_list)["index"]
    #         res = cls._request(f"{url}/{mob}")
    #         res["image"] = cls.get_image(res["name"])
    #         results.append(res)
    #     return results

    # @classmethod
    # def get_items(cls, number=1, **kwargs):
    #     results = []
    #     urls = [
    #         f"{cls.API_URL}/magicitems",
    #         f"{cls.API_URL}/weapons",
    #         f"{cls.API_URL}/armor",
    #     ]
    #     for _ in range(int(number)):
    #         mob = random.choice(mob_list)["index"]
    #         res = cls._request(f"{url}/{mob}")
    #         res["image"] = cls.get_image(res["name"])
    #         results.append(res)
    #     return results

    # @classmethod
    # def get_spells(cls, number=1, **kwargs):
    #     results = []
    #     url = f"{cls.API_URL}/monsters"
    #     cr_range = range(int(kwargs.get("crmin", 0)), int(kwargs.get("crmax", 20)) + 1)
    #     crs = ",".join([str(i) for i in cr_range])
    #     mob_list = cls._request(url + f"?challenge_rating={crs}")["results"]
    #     for _ in range(int(number)):
    #         mob = random.choice(mob_list)["index"]
    #         res = cls._request(f"{url}/{mob}")
    #         res["image"] = cls.get_image(res["name"])
    #         results.append(res)
    #     return results
