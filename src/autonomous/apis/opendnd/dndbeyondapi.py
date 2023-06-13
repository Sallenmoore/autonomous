from autonomous.model.automodel import AutoModel
from autonomous import log
import requests
from enum import Enum


class DnDBeyondAPI:
    api_url = "https://character-service.dndbeyond.com/character/v5/character"

    class ArmorType(Enum):
        ARMOR_TYPE_LIGHT = 1
        ARMOR_TYPE_MEDIUM = 2
        ARMOR_TYPE_HEAVY = 3
        ARMOR_TYPE_SHIELD = 4

    class StatType(Enum):
        STR = 1
        DEX = 2
        CON = 3
        INT = 4
        WIS = 5
        CHA = 6

    @classmethod
    def getcharacter(cls, dnd_id):
        url = f"{cls.api_url}/{dnd_id}"
        r = requests.get(url)
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            log(f"Error getting character {dnd_id}")
            character = None
        else:
            data = r.json()["data"]
            character = cls._parseinfo(**data)
            character["dnd_id"] = dnd_id
            # log(character["image"])
        return character

    @classmethod
    def _parseinfo(cls, **kwargs):
        character = {}
        character["name"] = kwargs.get("name")
        character["age"] = kwargs.get("age") or 0

        # breakpoint()
        character["image"] = {
            "asset_id": None,
            "url": "",
            "raw": None,
        }
        if img := kwargs.get("decorations"):
            character["image"]["url"] = img.get("avatarUrl") or ""

        if kwargs.get("race"):
            character["race"] = kwargs.get("race")["fullName"]

        if kwargs.get("notes"):
            character["desc"] = kwargs["notes"].get("backstory") or ""

        character["wealth"] = kwargs.get("currencies")

        if kwargs.get("classes"):
            character["class_name"] = ",".join(
                [c["definition"]["name"] for c in kwargs["classes"]]
            )

        # Ability Scores
        character["str"] = cls.getstat(DnDBeyondAPI.StatType.STR.value, **kwargs)
        character["dex"] = cls.getstat(DnDBeyondAPI.StatType.DEX.value, **kwargs)
        character["con"] = cls.getstat(DnDBeyondAPI.StatType.CON.value, **kwargs)
        character["wis"] = cls.getstat(DnDBeyondAPI.StatType.WIS.value, **kwargs)
        character["int"] = cls.getstat(DnDBeyondAPI.StatType.INT.value, **kwargs)
        character["cha"] = cls.getstat(DnDBeyondAPI.StatType.CHA.value, **kwargs)

        character["inventory"] = cls.getinventory(kwargs.get("inventory"))
        character["speed"] = kwargs["race"]["weightSpeeds"]["normal"]
        character["hp"] = cls.gethp(**kwargs)
        character["features"] = cls.getfeatures(**kwargs)
        character["ac"] = cls.getac(**kwargs)
        character["resistances"] = cls.getresistances(**kwargs)
        character["spells"] = cls.getspells(**kwargs)
        return character

    @staticmethod
    def getmodifier(score: int) -> int:
        """
        Calculate modifier from score
        """
        return (score - 10) // 2

    @classmethod
    def getinventory(cls, inventory):
        if not inventory:
            return []
        ch_inventory = []
        for item in inventory:
            ch_inventory.append(
                {
                    "name": item["definition"]["name"],
                    "description": item["definition"]["description"],
                }
            )
        return ch_inventory

    @classmethod
    def gethp(cls, **kwargs):
        hp = kwargs.get("baseHitPoints", 0) + (
            9 * (cls.getstat(DnDBeyondAPI.StatType.CON.value, **kwargs))
        )
        hp += kwargs.get("bonusHitPoints") or 0
        hp -= kwargs.get("removedHitPoints", 0)
        hp += kwargs.get("temporaryHitPoints", 0)
        return hp

    @classmethod
    def getfeatures(cls, **kwargs):
        features = {}
        for v in kwargs.get("actions", {}).values():
            # log(v)
            if v:
                for option in v:
                    features[option["name"]] = option.get("snippet") or option.get(
                        "description"
                    )

        for k, v in kwargs.get("options", {}).items():
            if v:
                for o in v:
                    # log(o)
                    o = o["definition"]
                    features[o["name"]] = o.get("snippet") or o.get("description")

        return features

    @classmethod
    def getspells(cls, **kwargs):
        spells = {}
        for v in kwargs.get("spells", {}).values():
            if v:
                for o in v:
                    o = o["definition"]
                    spells[o["name"]] = o.get("snippet") or o.get("description")

        for v in kwargs.get("classSpells", []):
            for sp in v.get("spells", []):
                o = sp["definition"]
                spells[o["name"]] = o.get("snippet") or o.get("description")

        return spells

    @classmethod
    def getstat(cls, stat: int, **kwargs) -> int:
        """
        Calculate maximum hitpoints using hit dice (HD), level and constitution modifier
        """
        score = 0
        stats = kwargs.get("stats", [])
        for s in stats:
            # log(f"{self.name} - Stats: {s}, {stat}")
            if s["id"] == stat:
                # log(f"{self.name} - Stats: {s}")
                score += s["value"]
        stats = kwargs.get("bonusStats", [])
        for s in stats:
            if s["id"] == stat:
                # log(f"{self.name} - Stats: {score}, s: {s}")
                score += s["value"] or 0
                # log(f"{self.name} - Stats: {score}, s: {s}")

        stats = kwargs.get("modifiers", {})
        for category in stats.values():
            # log(f"Modifiers: {s}")
            for s in category:
                if (
                    s.get("entityId") == stat
                    and s.get("type") == "bonus"
                    and "score" in s.get("subType", "")
                ):
                    score += s["value"] or 0
        return score

    @classmethod
    def getac(cls, **kwargs):
        character_ac = 10 + DnDBeyondAPI.getmodifier(
            cls.getstat(DnDBeyondAPI.StatType.DEX.value, **kwargs)
        )
        # log(f"{self.name} - AC: {character_ac}")
        armor_ac = 0
        shield_ac = 0
        total_ac = 0

        for i in kwargs.get("inventory", []):
            if i["equipped"] and i["definition"].get("armorTypeId"):
                if (
                    DnDBeyondAPI.ArmorType.ARMOR_TYPE_SHIELD.value
                    == i["definition"]["armorTypeId"]
                ):
                    shield_ac += i["definition"]["armorClass"]
                if (
                    DnDBeyondAPI.ArmorType.ARMOR_TYPE_SHIELD.value
                    != i["definition"]["armorTypeId"]
                ):
                    armor_ac += i["definition"]["armorClass"]

        # log(f"{self.name} - Armor AC: {armor_ac + shield_ac}")
        if shield_ac or armor_ac:
            total_ac = max(
                character_ac,
                armor_ac
                + shield_ac
                + DnDBeyondAPI.getmodifier(
                    cls.getstat(DnDBeyondAPI.StatType.DEX.value, **kwargs)
                ),
            )
        else:
            if kwargs.get("classes"):
                classes = [
                    c["definition"]["name"].lower()
                    for c in kwargs["classes"]
                    if c["definition"]["name"].lower() in ["barbarian", "monk"]
                ]
                if classes:
                    total_ac += DnDBeyondAPI.getmodifier(
                        cls.getstat(DnDBeyondAPI.StatType.CON.value, **kwargs)
                    )

                if "monk" in classes:
                    total_ac += DnDBeyondAPI.getmodifier(
                        cls.getstat(DnDBeyondAPI.StatType.WIS.value, **kwargs)
                    )

        modifiers = kwargs.get("modifiers", {})
        for category in modifiers.values():
            for s in category:
                if s.get("type") == "bonus" and s.get("subType") == "armor-class":
                    total_ac += s["fixedValue"]
        return total_ac

    @classmethod
    def getresistances(cls, **kwargs):
        modifiers = kwargs.get("modifiers", {})

        resistance = []
        for category in modifiers.values():
            for s in category:
                if s.get("type") == "resistance":
                    resistance.append(s["subType"])
        return resistance
