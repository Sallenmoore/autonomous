import pytest
from autonomous.apis.opendnd import dndobject
from autonomous.apis.opendnd import open5eapi
from autonomous.apis import OpenDnD


@pytest.fixture
def sample_data():
    return {
        "monster": {
            "name": "Goblin",
            "type": "humanoid",
            "size": "Small",
            "alignment": "neutral evil",
            "armor_class": 15,
            "hit_points": 7,
            "speed": {"walk": 30},
            "strength": 8,
            "dexterity": 14,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 8,
            "charisma": 8,
            "skills": {"stealth": 6},
            "damage_vulnerabilities": "none",
            "damage_resistances": "none",
            "damage_immunities": "none",
            "condition_immunities": "none",
            "senses": {"darkvision": 60},
            "languages": "Common, Goblin",
            "cr": 0.25,
            "actions": [
                {
                    "name": "Scimitar",
                    "desc": "Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage.",
                    "attack_bonus": 4,
                    "damage_dice": "1d6",
                    "damage_bonus": 2,
                },
                {
                    "name": "Shortbow",
                    "desc": "Ranged Weapon Attack: +4 to hit, range 80/320 ft., one target. Hit: 5 (1d6 + 2) piercing damage.",
                    "attack_bonus": 4,
                    "damage_dice": "1d6",
                    "damage_bonus": 2,
                },
            ],
        },
        "spell": {
            "name": "Magic Missile",
            "school": "Evocation",
            "desc": [
                "You create three glowing darts of magical force. Each dart hits a creature of your choice that you can see within range. A dart deals 1d4 + 1 force damage to its target. The darts all strike simultaneously and you can direct them to hit one creature or several."
            ],
            "higher_level": [
                "When you cast this spell using a spell slot of 2nd level or higher, the spell creates one more dart for each slot level above 1st."
            ],
        },
        "item": {
            "name": "Sword of Sharpness",
            "type": "Weapon",
            "img_main": "https://i.imgur.com/abcdefg.png",
            "rarity": "Rare",
            "cost": "2000 gp",
            "category": "Martial Weapons",
            "requires_attunement": True,
            "damage_dice": "2d6",
            "damage_type": "Slashing",
            "weight": "6 lb.",
            "ac_string": None,
            "strength_requirement": 15,
            "stealth_disadvantage": True,
            "properties": ["Finesse", "Versatile (1d8)"],
            "desc": "This magical sword has a keen edge that seems to glide effortlessly through even the toughest armor.",
        },
    }


@pytest.mark.skip(reason="takes too long")
class TestOpen5eapi:
    def test_dndmonster_build(self, sample_data):
        monster_data = sample_data["monster"]
        monster = open5eapi.DnDMonster._build(monster_data)

        assert monster["name"] == monster_data["name"]
        assert monster["type"] == monster_data["type"]
        assert monster["image"] == monster_data.get("img_main")
        assert monster["size"] == monster_data.get("size")
        assert monster["subtype"] == monster_data.get("subtype")
        assert monster["alignment"] == monster_data.get("alignment")
        assert monster["armor_class"] == monster_data.get("armor_class")
        assert monster["armor_desc"] == monster_data.get("armor_desc")
        assert monster["hit_points"] == monster_data.get("hit_points")
        assert monster["hit_dice"] == monster_data.get("hit_dice")
        assert monster["speed"] == monster_data.get("speed")
        assert monster["strength"] == monster_data.get("strength")
        assert monster["dexterity"] == monster_data.get("dexterity")
        assert monster["constitution"] == monster_data.get("constitution")
        assert monster["intelligence"] == monster_data.get("intelligence")
        assert monster["wisdom"] == monster_data.get("wisdom")
        assert monster["charisma"] == monster_data.get("charisma")
        assert monster["strength_save"] == monster_data.get("strength_save")
        assert monster["dexterity_save"] == monster_data.get("dexterity_save")
        assert monster["constitution_save"] == monster_data.get("constitution_save")
        assert monster["intelligence_save"] == monster_data.get("intelligence_save")
        assert monster["wisdom_save"] == monster_data.get("wisdom_save")
        assert monster["charisma_save"] == monster_data.get("charisma_save")
        assert monster["perception"] == monster_data.get("perception")
        assert monster["skills"] == monster_data.get("skills")
        assert monster["vulnerabilities"] == monster_data.get("damage_vulnerabilities")
        assert monster["resistances"] == monster_data.get("damage_resistances")
        assert (
            monster["immunities"]
            == f"{monster_data['damage_immunities']}; {monster_data['condition_immunities']}"
        )
        assert monster["senses"] == monster_data.get("senses")
        assert monster["languages"] == monster_data.get("languages")
        assert monster["challenge_rating"] == monster_data.get("cr")
        assert monster["actions"] == monster_data.get("actions")
        assert monster["reactions"] == monster_data.get("reactions")
        assert monster["special_abilities"] == monster_data.get("special_abilities")

        monster_data = {
            "name": "Goblin",
            "type": "humanoid",
            "size": "small",
            "strength": 8,
            "dexterity": 14,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 8,
            "charisma": 8,
        }
        monster = open5eapi.DnDMonster._build(monster_data)

        # Check that missing fields were set to None
        assert monster["name"] == monster_data["name"]
        assert monster["type"] == monster_data["type"]

    def test_dndspell_build(self, sample_data):
        data = sample_data["spell"]
        spell = open5eapi.DnDSpell._build(data)
        assert spell["name"] == data["name"]
        assert spell["school"] == data["school"]
        assert spell["description"] == data["desc"]
        assert spell["variations"] == data["higher_level"]

    def test_dnditem_build(self, sample_data):
        data = sample_data["item"]

        item = open5eapi.DnDItem._build(data)

        assert item["name"] == "Sword of Sharpness"
        assert item["type"] == "Martial Weapons"
        assert item["image"] == "https://i.imgur.com/abcdefg.png"
        assert item["rarity"] == "Rare"
        assert item["cost"] == "2000 gp"
        assert item["category"] == "Martial Weapons"
        assert item["attunement"]
        assert item["damage_dice"] == "2d6"
        assert item["damage_type"] == "Slashing"
        assert item["weight"] == "6 lb."
        assert item["ac_string"] is None
        assert item["strength_requirement"] == 15
        assert item["stealth_disadvantage"]
        assert item["properties"] == ["Finesse", "Versatile (1d8)"]
        assert (
            item["desc"]
            == "This magical sword has a keen edge that seems to glide effortlessly through even the toughest armor."
        )

    def test_api_all(self):
        # Test that all() returns a list of monsters
        monsters = open5eapi.DnDMonster.all()
        assert len(monsters) > 0
        spells = open5eapi.DnDSpell.all()
        assert len(spells) > 0
        items = open5eapi.DnDItem.all()
        assert len(items) > 0

    def test_api_search(self):
        # Test that all() returns a list of monsters
        monsters = open5eapi.DnDMonster.search("goblin")
        assert len(monsters) > 0
        spells = open5eapi.DnDSpell.search("magic missile")
        assert len(spells) > 0
        items = open5eapi.DnDItem.search("leather")
        assert len(items) > 0

    def test_api_get(self):
        spell_url = "https://api.open5e.com/spells/magic-missile/"
        spell = open5eapi.DnDSpell.get(spell_url)
        assert spell["name"] == "Magic Missile"
        assert spell["school"] == "Evocation"
        assert (
            spell["description"]
            == "You create three glowing darts of magical force. Each dart hits a creature of your choice that you can see within range. A dart deals 1d4 + 1 force damage to its target. The darts all strike simultaneously, and you can direct them to hit one creature or several."
        )

        assert (
            spell["variations"]
            == "When you cast this spell using a spell slot of 2nd level or higher, the spell creates one more dart for each slot level above 1st."
        )

        monster_url = "https://api.open5e.com/monsters/aboleth/"
        monster = open5eapi.DnDMonster.get(monster_url)
        assert monster["name"] == "Aboleth"
        assert monster["size"] == "Large"
        assert monster["type"] == "aberration"
        assert monster["alignment"] == "lawful evil"
        assert monster["armor_class"] == 17
        assert monster["hit_points"] == 135
        assert monster["challenge_rating"] == 10
        assert monster["special_abilities"][0]["name"] == "Amphibious"

        item_url = "https://api.open5e.com/magicitems/glamoured-studded-leather/"
        item = open5eapi.DnDItem.get(item_url)
        assert item["name"] == "Glamoured Studded Leather"
        assert item["type"] == "Armor (studded leather)"
        assert item["rarity"] == "rare"


@pytest.mark.skip(reason="takes too long")
class TestDnDObject:
    def test_db_update(self):
        dndobject.DnDMonster.update_db()
        dndobject.DnDSpell.update_db()
        dndobject.DnDItem.update_db()

    def test_dndobject_all(self):
        objs = dndobject.DnDItem.all()
        for obj in objs:
            assert isinstance(obj, dndobject.DnDItem)
            assert obj.name is not None

        objs = dndobject.DnDSpell.all()
        for obj in objs:
            assert isinstance(obj, dndobject.DnDSpell)
            assert obj.name is not None

        objs = dndobject.DnDMonster.all()
        for obj in objs:
            assert isinstance(obj, dndobject.DnDMonster)
            assert obj.name is not None

    def test_dndobject_get(self):
        objs = dndobject.DnDItem.all()
        for obj in objs:
            result = dndobject.DnDItem.get(obj.pk)
            assert isinstance(obj, dndobject.DnDItem)
            assert result.name is not None

        objs = dndobject.DnDSpell.all()
        for obj in objs:
            result = dndobject.DnDSpell.get(obj.pk)
            assert isinstance(obj, dndobject.DnDSpell)
            assert result.name is not None

        objs = dndobject.DnDMonster.all()
        for obj in objs:
            result = dndobject.DnDMonster.get(obj.pk)
            assert isinstance(obj, dndobject.DnDMonster)
            assert result.name is not None

    def test_dndobject_search(self):
        objs = dndobject.DnDItem.search(name="glamoured")
        for obj in objs:
            assert isinstance(obj, dndobject.DnDItem)
            assert "glamoured" in obj.name

        objs = dndobject.DnDSpell.search(name="fire")
        for obj in objs:
            assert isinstance(obj, dndobject.DnDSpell)
            assert "fire" in obj.name

        objs = dndobject.DnDMonster.search(name="goblin")
        for obj in objs:
            assert isinstance(obj, dndobject.DnDMonster)
            assert "goblin" in obj.name


class TestOpenDnD:
    @pytest.mark.skip(reason="takes too long")
    def test_opendnd_updatedb(self):
        OpenDnD.update_db()

    def test_opendnd_search(self):
        objs = OpenDnD.searchitems(name="glamoured")
        for obj in objs:
            assert isinstance(obj, dndobject.DnDItem)
            assert "glamoured" in obj.name.lower()
            assert obj.image

        objs = OpenDnD.searchspells(name="fire")
        for obj in objs:
            assert isinstance(obj, dndobject.DnDSpell)
            assert "fire" in obj.name.lower()
            assert obj.image

        objs = OpenDnD.searchmonsters(name="goblin")
        for obj in objs:
            assert isinstance(obj, dndobject.DnDMonster)
            assert "goblin" in obj.name.lower()
            assert obj.image

    def test_opendnd_get(self):
        objs = OpenDnD.items()
        for obj in objs:
            assert isinstance(obj, dndobject.DnDItem)
            alt_obj = OpenDnD.items(pk=obj.pk)[0]
            assert obj.name == alt_obj.name
            assert obj.pk == alt_obj.pk

        objs = OpenDnD.spells()
        for obj in objs:
            assert isinstance(obj, dndobject.DnDSpell)
            alt_obj = OpenDnD.spells(pk=obj.pk)[0]
            assert obj.name == alt_obj.name
            assert obj.pk == alt_obj.pk

        objs = OpenDnD.monsters()
        for obj in objs:
            assert isinstance(obj, dndobject.DnDMonster)
            alt_obj = OpenDnD.monsters(pk=obj.pk)[0]
            assert obj.name == alt_obj.name
            assert obj.pk == alt_obj.pk
            assert obj.image == alt_obj.image
