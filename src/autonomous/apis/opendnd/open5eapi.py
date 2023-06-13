import requests


class Open5e:
    api_url = "https://api.open5e.com/"


class DnDMonster(Open5e):
    @classmethod
    def _build(cls, data):
        obj = {}
        obj["name"] = data["name"]
        obj["type"] = data["type"]
        obj["image"] = {"url": data.get("img_main"), "asset_id": 0, "raw": None}

        obj["size"] = data.get("size")
        obj["subtype"] = data.get("subtype")
        obj["alignment"] = data.get("alignment")
        obj["armor_class"] = data.get("armor_class")
        obj["armor_desc"] = data.get("armor_desc")
        obj["hit_points"] = data.get("hit_points")
        obj["hit_dice"] = data.get("hit_dice")
        obj["speed"] = data.get("speed")
        obj["strength"] = data.get("strength")
        obj["dexterity"] = data.get("dexterity")
        obj["constitution"] = data.get("constitution")
        obj["intelligence"] = data.get("intelligence")
        obj["wisdom"] = data.get("wisdom")
        obj["charisma"] = data.get("charisma")
        obj["strength_save"] = data.get("strength_save")
        obj["dexterity_save"] = data.get("dexterity_save")
        obj["constitution_save"] = data.get("constitution_save")
        obj["intelligence_save"] = data.get("intelligence_save")
        obj["wisdom_save"] = data.get("wisdom_save")
        obj["charisma_save"] = data.get("charisma_save")
        obj["perception"] = data.get("perception")

        obj["skills"] = data.get("skills")
        obj["vulnerabilities"] = data.get("damage_vulnerabilities")
        obj["resistances"] = data.get("damage_resistances")
        obj[
            "immunities"
        ] = f"{data.get('damage_immunities', '')}; {data.get('condition_immunities', '')}"

        obj["senses"] = data.get("senses")
        obj["languages"] = data.get("languages")
        obj["challenge_rating"] = data.get("cr", 0)

        obj["actions"] = data.get("actions")
        obj["reactions"] = data.get("reactions")

        obj["special_abilities"] = data.get("special_abilities")

        if data.get("spell_list"):
            obj["spell_list"] = {}
            for a in data["spell_list"]:
                spell = DnDSpell.get(url=a)
                obj["spell_list"][spell["name"]] = spell
        return obj

    @classmethod
    def all(cls):
        response = requests.get(f"{cls.api_url}monsters/").json()
        results = response["results"]
        while response.get("next"):
            response = requests.get(response["next"]).json()
            results += response["results"]
        return [cls._build(r) for r in results]

    @classmethod
    def search(cls, term):
        response = requests.get(f"{cls.api_url}monsters/?search={term}").json()
        return [cls._build(r) for r in response["results"]]

    @classmethod
    def get(cls, url=None):
        if url:
            results = requests.get(url).json()
            return cls._build(results)


class DnDSpell(Open5e):
    @classmethod
    def _build(cls, data):
        obj = {}
        obj["name"] = data["name"]
        obj["school"] = data["school"]
        obj["desc"] = data["desc"]
        obj["variations"] = data.get("higher_level")
        obj["image"] = {"url": "", "asset_id": 0, "raw": None}

        if data.get("range"):
            obj["range"] = data["range"]
        if data.get("ritual") and data.get("ritual") != "no":
            obj["ritual"] = data["ritual"]
        if data.get("duration"):
            obj["duration"] = data["duration"]
        if data.get("concentration") and data.get("concentration") != "no":
            obj["concentration"] = data["concentration"]
        if data.get("casting_time"):
            obj["casting_time"] = data["casting_time"]
        if data.get("level_int"):
            obj["level"] = data["level_int"]
        if data.get("archetype"):
            obj["archetype"] = data["archetype"]
        if data.get("circles"):
            obj["circles"] = data["circles"]
        return obj

    @classmethod
    def all(cls):
        response = requests.get(f"{cls.api_url}spells/").json()
        results = response["results"]
        while response.get("next"):
            response = requests.get(response["next"]).json()
            results += response["results"]
        return [cls._build(r) for r in results]

    @classmethod
    def search(cls, term):
        response = requests.get(f"{cls.api_url}spells/?search={term}").json()
        return [cls._build(r) for r in response["results"]]

    @classmethod
    def get(cls, url=None):
        if url:
            results = requests.get(url).json()
            return cls._build(results)


class DnDItem(Open5e):
    @classmethod
    def _build(cls, data):
        obj = {}
        obj["name"] = data["name"]
        obj["type"] = data.get("category", data.get("type"))
        obj["image"] = {"url": data.get("img_main"), "asset_id": 0, "raw": None}
        obj["rarity"] = data.get("rarity")
        obj["cost"] = data.get("cost")
        obj["category"] = data.get("category")
        obj["attunement"] = data.get("requires_attunement")
        obj["damage_dice"] = data.get("damage_dice")
        obj["damage_type"] = data.get("damage_type")
        obj["weight"] = data.get("weight")
        obj["ac_string"] = data.get("ac_string")
        obj["strength_requirement"] = data.get("strength_requirement")
        obj["stealth_disadvantage"] = data.get("stealth_disadvantage")
        obj["properties"] = data.get("properties")
        obj["desc"] = data.get("desc")
        return obj

    @classmethod
    def all(cls):
        response = requests.get(f"{cls.api_url}magicitems/").json()
        results = response["results"]
        while response.get("next"):
            response = requests.get(response["next"]).json()
            results += response["results"]

        response = requests.get(f"{cls.api_url}weapons/").json()
        results += response["results"]
        while response.get("next"):
            response = requests.get(response["next"]).json()
            results += response["results"]

        response = requests.get(f"{cls.api_url}armor/").json()
        results += response["results"]
        while response.get("next"):
            response = requests.get(response["next"]).json()
            results += response["results"]

        return [cls._build(r) for r in results]

    @classmethod
    def search(cls, term):
        response = requests.get(f"{cls.api_url}magicitems/?search={term}").json()[
            "results"
        ]
        response += requests.get(f"{cls.api_url}weapons/?search={term}").json()[
            "results"
        ]
        response += requests.get(f"{cls.api_url}armor/?search={term}").json()["results"]
        return [cls._build(r) for r in response]

    @classmethod
    def get(cls, url=None):
        if url:
            results = requests.get(url).json()
            return cls._build(results)
