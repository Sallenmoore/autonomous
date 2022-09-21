from sharedlib.model.model import Model


class Item(Model):
    resource = ["magicitems", "weapons", "armor"]

    def model_attr(self):
        return {
            "name": str,
            "type": str,
            "category": str,
            "cost": str,
            "desc": str,
            "damage_dice": str,
            "damage_type": str,
            "weight": str,
            "ac_string": str,
            "strength_requirement": str,
            "rarity": str,
            "requires_attunement": str,
            "stealth_disadvantage": bool,
            "properties": list,
            'img_main':str,
        }