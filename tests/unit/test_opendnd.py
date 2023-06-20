import pytest
import random
from autonomous.apis.opendnd.dndplayer import Player
from autonomous.apis.opendnd.dndnpc import NPC
from autonomous.apis.opendnd.dndshop import Shop
from autonomous.apis.opendnd.dndmonster import Monster
from autonomous.apis.opendnd.dnditem import Item
from autonomous.apis.opendnd.dndspell import Spell
from autonomous.apis.opendnd import open5eapi
from autonomous.apis.opendnd import dndbeyondapi
from autonomous.apis import OpenDnD
from autonomous import log


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
        "shop": {
            "name": "test",
            "owner_id": None,
            "description": "A Test Shop",
            "inventory": [
                {
                    "name": "test item A",
                    "description": "this is a test item A",
                    "cost": 1,
                },
                {
                    "name": "test item B",
                    "description": "this is a test item B",
                    "cost": 2,
                },
            ],
            "location": "TEST",
        },
        "player": {
            "name": "test",
            "age": 0,
            "decorations": {"avatarUrl": "test"},
            "notes": {"desc": "this is a test", "backstory": "this is a test"},
            "race": {"fullName": "test"},
            "speed": {"weightSpeeds": {"normal": {"walk": 1}}},
            "class_name": "test",
            "age": 0,
            "baseHitPoints": 0,
            "bonusHitPoints": 0,
            "removedHitPoints": 0,
            "temporaryHitPoints": 0,
            "currencies": {"test": 1},
            "stats": [
                {"id": 1, "name": None, "value": 12},
                {"id": 2, "name": None, "value": 14},
                {"id": 3, "name": None, "value": 17},
                {"id": 4, "name": None, "value": 13},
                {"id": 5, "name": None, "value": 14},
                {"id": 6, "name": None, "value": 18},
            ],
            "bonusStats": [
                {"id": 1, "name": None, "value": None},
                {"id": 2, "name": None, "value": None},
                {"id": 3, "name": None, "value": 1},
                {"id": 4, "name": None, "value": None},
                {"id": 5, "name": None, "value": None},
                {"id": 6, "name": None, "value": None},
            ],
            "inventory": [
                {
                    "definition": {
                        "name": "item a",
                        "description": "item a description",
                    },
                    "equipped": True,
                },
                {
                    "definition": {
                        "name": "item b",
                        "description": "item b description",
                        "armorTypeId": 1,
                        "armorClass": 1,
                    },
                    "equipped": True,
                },
            ],
            "actions": {
                "featureA": {
                    "catA": {"name": "TestA", "snippet": "This is a smippet A"}
                },
                "featureB": {
                    "catB": {"name": "TestB", "description": "This is a description B"}
                },
                "featureC": {
                    "catC": {
                        "name": "TestC",
                        "snippet": "This is a snippet C",
                        "description": "This is a description C",
                    }
                },
            },
            "options": {
                "featureA": {
                    "definition": {"name": "TestA", "snippet": "This is a smippet A"}
                },
                "featureB": {
                    "definition": {
                        "name": "TestB",
                        "description": "This is a description B",
                    }
                },
                "featureC": {
                    "definition": {
                        "name": "TestC",
                        "snippet": "This is a snippet C",
                        "description": "This is a description C",
                    }
                },
            },
            "spells": {
                "spellA": {
                    "definition": {"name": "TestA", "snippet": "This is a snippet A"}
                },
                "spellB": {
                    "definition": {
                        "name": "TestB",
                        "description": "This is a description B",
                    }
                },
                "spellC": {
                    "definition": {
                        "name": "TestC",
                        "snippet": "This is a snippet C",
                        "description": "This is a description C",
                    }
                },
            },
            "classSpells": {
                "spells": [
                    {"definition": {"name": "TestA", "snippet": "This is a snippet A"}},
                    {
                        "definition": {
                            "name": "TestB",
                            "description": "This is a description B",
                        }
                    },
                    {
                        "definition": {
                            "name": "TestC",
                            "snippet": "This is a snippet C",
                            "description": "This is a description C",
                        }
                    },
                ]
            },
            "modifiers": {
                "testA": [
                    {
                        "fixedValue": 100,
                        "type": "bonus",
                        "subType": "armor-class",
                    }
                ],
                "testB": [
                    {
                        "fixedValue": 99,
                        "type": "bonus",
                        "subType": "none",
                    }
                ],
                "testC": [
                    {
                        "fixedValue": 98,
                        "type": "none",
                        "subType": "armor-class",
                    }
                ],
                "testD": [
                    {
                        "type": "resistance",
                        "subType": "Is resistant to D",
                    }
                ],
                "testE": [
                    {
                        "type": "nothing",
                        "subType": "IS nothing",
                    }
                ],
            },
        },
        "npc": {
            "name": "test",
            "backstory": "This is a test",
            "race": "test",
            "class_name": "test",
            "age": 1,
            "hp": 1,
            "desc": "This is a test",
            "inventory": [
                {
                    "name": "item a",
                    "description": "item a description",
                },
                {
                    "name": "item b",
                    "description": "item b description",
                },
            ],
            "strength": 1,
            "dexterity": 2,
            "constitution": 3,
            "wisdom": 4,
            "intelligence": 5,
            "charisma": 6,
        },
    }


@pytest.fixture
def pop_db(sample_data):
    dndplayer = Player(**sample_data["player"])
    dndplayer.save()
    dndshop = Shop(**sample_data["shop"])
    dndshop.save()
    log("dndshop", dndshop)
    dndnpc = NPC(**sample_data["npc"])
    dndnpc.save()
    data = {"player": dndplayer, "shop": dndshop, "npc": dndnpc}
    yield data
    for p in Player.all():
        if p.name == sample_data["player"]["name"]:
            p.delete()

    for p in NPC.all():
        if p.name == sample_data["npc"]["name"]:
            p.delete()

    for p in Shop.all():
        if p.name == sample_data["shop"]["name"]:
            p.delete()


# @pytest.mark.skip(reason="Takes too long to run")
class TestOpen5eapi:
    def test_dndmonster_build(self, sample_data):
        monster_data = sample_data["monster"]
        monster = open5eapi.DnDMonster._build(monster_data)
        assert monster["name"] == monster_data["name"]
        assert monster["type"] == monster_data["type"]
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
        assert spell["desc"] == data["desc"]
        assert spell["variations"] == data["higher_level"]

    def test_dnditem_build(self, sample_data):
        data = sample_data["item"]

        item = open5eapi.DnDItem._build(data)

        assert item["name"] == "Sword of Sharpness"
        assert item["type"] == "Martial Weapons"
        assert item["image"] == {
            "asset_id": 0,
            "raw": None,
            "url": "https://i.imgur.com/abcdefg.png",
        }
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
            spell["desc"]
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


# @pytest.mark.skip(reason="Takes too long to run")
class TestDnDBeyondAPI:
    def test_player_build(self, sample_data):
        for dnd_id in [77709222, 68398459, 101495221, 70279502]:
            player = dndbeyondapi.DnDBeyondAPI.getcharacter(dnd_id)

            assert player["name"] is not None
            assert player["dnd_id"] is not None
            assert player["image"] is not None
            assert player["ac"] is not None
            assert player["desc"] is not None
            assert player["race"] is not None
            assert player["speed"] is not None
            assert player["class_name"] is not None
            assert player["hp"] is not None
            assert player["age"] is not None
            assert player["wealth"] is not None
            assert player["str"] is not None
            assert player["dex"] is not None
            assert player["con"] is not None
            assert player["int"] is not None
            assert player["wis"] is not None
            assert player["cha"] is not None
            assert player["inventory"] is not None
            assert player["features"] is not None
            assert player["spells"] is not None
            assert player["resistances"] is not None

        player = dndbeyondapi.DnDBeyondAPI.getcharacter(-1)

        assert not player


# @pytest.mark.skip(reason="takes too long")
class TestDnDObject:
    # @pytest.mark.skip(reason="takes too long")
    def test_monster_db_update(self):
        Monster.update_db()

    # @pytest.mark.skip(reason="takes too long")
    def test_spell_db_update(self):
        Spell.update_db()

    # @pytest.mark.skip(reason="takes too long")
    def test_item_db_update(self):
        Item.update_db()

    # @pytest.mark.skip(reason="takes too long")
    def test_dndobjectfromapi_all(self):
        objs = random.sample(Item.all(), 5)
        for obj in objs:
            assert isinstance(obj, Item)
            assert obj.name is not None

        objs = random.sample(Spell.all(), 5)
        for obj in objs:
            assert isinstance(obj, Spell)
            assert obj.name is not None

        objs = random.sample(Monster.all(), 5)
        for obj in objs:
            assert isinstance(obj, Monster)
            assert obj.name is not None

    # @pytest.mark.skip(reason="costs money")
    def test_dndobjectfromapi_get(self):
        obj = random.choice(Item.all())
        obj.generate_image()
        assert obj.image["url"]
        assert obj.image["asset_id"]
        assert obj.image["raw"] is None
        result = Item.get(obj.pk)
        assert isinstance(obj, Item)
        assert result.name is not None

        obj = random.choice(Spell.all())
        obj.generate_image()
        assert obj.image["url"]
        assert obj.image["asset_id"]
        assert obj.image["raw"] is None
        result = Spell.get(obj.pk)
        assert isinstance(obj, Spell)
        assert result.name is not None

        obj = random.choice(Monster.all())
        obj.generate_image()
        assert obj.image["url"]
        assert obj.image["asset_id"]
        assert obj.image["raw"] is None
        result = Monster.get(obj.pk)
        assert isinstance(obj, Monster)
        assert result.name is not None

    # @pytest.mark.skip(reason="takes too long")
    def test_dndobjectfromapi_search(self):
        objs = Item.search(name="resistance")
        for obj in objs:
            assert isinstance(obj, Item)
            assert "resistance" in obj.name.lower()

        objs = Spell.search(name="fire")
        for obj in objs:
            assert isinstance(obj, Spell)
            assert "fire" in obj.name.lower()

        objs = Monster.search(name="goblin")
        for obj in objs:
            assert isinstance(obj, Monster)
            assert "goblin" in obj.name.lower()

    # @pytest.mark.skip(reason="takes too long")
    def test_dndplayer(self):
        player = Player(dnd_id="77709222")
        player.updateinfo()
        player.save()

        assert player.dnd_id == "77709222"
        assert player.name
        assert player.image
        assert player.ac
        assert player.desc
        assert player.race
        assert player.speed
        assert player.class_name
        assert player.hp
        assert player.age
        assert player.wealth
        assert player.str
        assert player.dex
        assert player.con
        assert player.int
        assert player.wis
        assert player.cha
        assert player.inventory
        assert player.features
        assert player.spells
        assert player.resistances

        player = Player.find(dnd_id="-1")
        assert not player

    # @pytest.mark.skip(reason="costs money")
    def test_dndnpc(self, pop_db):
        npc = pop_db["npc"]
        for npc in NPC.all():
            if npc.name == "test":
                npc.generate_image()
                assert npc.image["url"]
                assert npc.image["asset_id"]
                assert npc.image["raw"] is None
                assert npc.inventory[0]["name"] == "item a"

    # @pytest.mark.skip(reason="costs money")
    def test_dndshop(self, pop_db):
        shop = pop_db["shop"]
        for shop in Shop.all():
            if shop.name == "test":
                shop.generate_image()
                assert shop.image["url"]
                assert shop.image["asset_id"]
                assert shop.image["raw"] is None
                assert shop.location == "TEST"
                assert len(shop.inventory) == 2
                assert shop.inventory[0]["name"] == "test item A"


# @pytest.mark.skip(reason="takes too long")
class TestOpenDnD:
    def test_opendnd_search(self, pop_db):
        objs = OpenDnD.items(name="glamoured")
        for obj in objs:
            assert isinstance(obj, Item)
            assert "glamoured" in obj.name.lower()

        objs = OpenDnD.spells(name="fire")
        for obj in objs:
            assert isinstance(obj, Spell)
            assert "fire" in obj.name.lower()

        objs = OpenDnD.monsters(name="goblin")
        for obj in objs:
            assert isinstance(obj, Monster)
            assert "goblin" in obj.name.lower()

        objs = OpenDnD.players(name="test")
        for obj in objs:
            assert isinstance(obj, Player)
            assert "test" in obj.name

        objs = OpenDnD.shops(name="test")
        for obj in objs:
            assert isinstance(obj, Shop)
            assert "test" in obj.name.lower()

        objs = OpenDnD.npcs(name="test")
        for obj in objs:
            assert isinstance(obj, NPC)
            assert "test" in obj.name

    def test_opendnd_get(self, pop_db):
        objs = OpenDnD.items()
        objs = random.sample(objs, 5)
        for obj in objs:
            assert isinstance(obj, Item)
            alt_obj = OpenDnD.items(pk=obj.pk)[0]
            assert obj.name == alt_obj.name
            assert obj.pk == alt_obj.pk

        objs = OpenDnD.spells()
        objs = random.sample(objs, 5)
        for obj in objs:
            assert isinstance(obj, Spell)
            alt_obj = OpenDnD.spells(pk=obj.pk)[0]
            assert obj.name == alt_obj.name
            assert obj.pk == alt_obj.pk

        objs = OpenDnD.monsters()
        objs = random.sample(objs, 5)
        for obj in objs:
            assert isinstance(obj, Monster)
            alt_obj = OpenDnD.monsters(pk=obj.pk)[0]
            assert obj.name == alt_obj.name
            assert obj.pk == alt_obj.pk
            assert obj.image == alt_obj.image

        objs = OpenDnD.players(pk=pop_db["player"].pk)
        for obj in objs:
            assert isinstance(obj, Player)
            assert "test" in obj.name

        objs = OpenDnD.shops(pk=pop_db["shop"].pk)
        for obj in objs:
            assert isinstance(obj, Shop)
            assert "test" in obj.name.lower()

        objs = OpenDnD.npcs(pk=pop_db["npc"].pk)
        for obj in objs:
            assert isinstance(obj, NPC)
            assert "test" in obj.name

    def test_opendnd_all(self, pop_db):
        objs = OpenDnD.items()
        assert len(objs) > 0

        objs = OpenDnD.spells()
        assert len(objs) > 0

        objs = OpenDnD.monsters()
        assert len(objs) > 0

        objs = OpenDnD.players()
        assert len(objs) > 0

        objs = OpenDnD.shops()
        assert len(objs) > 0

        objs = OpenDnD.npcs()
        assert len(objs) > 0

    # @pytest.mark.skip(reason="costs money")
    def test_opendnd_randomnpc(self):
        npc = OpenDnD.generatenpc()
        assert npc.name

    # @pytest.mark.skip(reason="costs money")
    def test_opendnd_randomencounter(self):
        encounter = OpenDnD.generateencounter()
        assert encounter["difficulty"]

    # @pytest.mark.skip(reason="costs money")
    def test_opendnd_randomshop(self):
        shop = OpenDnD.generateshop()
        assert shop.name

    # @pytest.mark.skip(reason="costs money")
    def test_opendnd_image_generate(self):
        npc = OpenDnD.generatenpc()
        npc.generate_image()
        assert npc.image["asset_id"]
        assert npc.image["url"]
        assert not npc.image["raw"]
        shop = OpenDnD.generateshop()
        shop.generate_image()
        assert shop.image["asset_id"]
        assert shop.image["url"]
        item = OpenDnD.items()[0]
        item.generate_image()
        assert item.image["asset_id"]
        assert item.image["url"]
        assert not item.image["raw"]
        monster = OpenDnD.monsters()[0]
        monster.generate_image()
        assert monster.image["asset_id"]
        assert monster.image["url"]
        assert not item.image["raw"]
        spell = OpenDnD.spells()[0]
        spell.generate_image()
        assert spell.image["asset_id"]
        assert spell.image["url"]
        assert not spell.image["raw"]
