import os
import shutil
import random
import sys
from slugify import slugify
from datetime import datetime
from autonomous.logger import log
from .. import OpenAI
from .dndobject import DnDMonster, DnDItem, DnDSpell

NUM_IMAGES = 1


class OpenDnD:
    """
    _summary_

    Returns:
        _type_: _description_
    """

    imgpath = f"{os.path.dirname(sys.modules[__name__].__file__)}/imgs"

    @classmethod
    def has_image(cls, fname):
        items = os.listdir(cls.imgpath)
        random.shuffle(items)
        for i in items:
            if fname in i:
                return f"{cls.imgpath}/{i}"

    @classmethod
    def get_image(cls, name, description="A portrait"):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        name = slugify(name)
        img_file = cls.has_image(name)
        if not img_file:
            prompt = f"Illustration of {name} from Dungeons and Dragons 5e - {random.choice(description)}"
            try:
                resp = OpenAI().generate_image(
                    prompt,
                    path=f"{cls.imgpath}/{name}-{datetime.now().toordinal()}.png",
                )
                img_file = resp[0]
            except Exception as e:
                log(e)

        static_directory = "static/images/dnd"
        if not os.path.exists(static_directory):
            os.makedirs(static_directory)
        if not os.path.exists(f"{static_directory}/{os.path.basename(img_file)}"):
            shutil.copy(img_file, f"{static_directory}/{os.path.basename(img_file)}")

        return f"/{static_directory}/{os.path.basename(img_file)}"

    @classmethod
    def _process_results(cls, results, limit=0):
        new_results = []
        for i, r in enumerate(results):
            if not results[i].image:
                results[i].image = cls.get_image(results[i].name)
            new_results.append(results[i])
            if i >= limit:
                return new_results
        return new_results

    @classmethod
    def _process_search_terms(cls, **terms):
        if terms.get("name"):
            terms["slug"] = slugify(terms["name"])
        return terms

    @classmethod
    def monsters(cls, **kwargs):
        return DnDMonster.all()

    @classmethod
    def items(cls, **kwargs):
        return DnDItem.all()

    @classmethod
    def spells(cls, **kwargs):
        return DnDSpell.all()

    @classmethod
    def searchmonsters(cls, name=None, LIMIT=1, **key):
        if name:
            key["name"] = name

        key = cls._process_search_terms(**key)
        results = DnDMonster.search(**key)
        return cls._process_results(results, limit=LIMIT)

    @classmethod
    def searchitems(cls, name=None, LIMIT=1, **key):
        if name:
            key["name"] = name

        key = cls._process_search_terms(**key)
        results = DnDItem.search(**key)
        return cls._process_results(results, limit=LIMIT)

    @classmethod
    def searchspells(cls, name=None, LIMIT=1, **key):
        if name:
            key["name"] = name

        key = cls._process_search_terms(**key)
        results = DnDSpell.search(**key)
        return cls._process_results(results, limit=LIMIT)

    @classmethod
    def updatedb(cls):
        DnDMonster.update_db()
        DnDSpell.update_db()
        DnDItem.update_db()
