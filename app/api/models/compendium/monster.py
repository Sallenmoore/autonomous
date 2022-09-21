from sharedlib.model.model import Model


class Monster(Model):
    resource = ["monsters"]

    def model_attr(self):
        return {
            'name':str,  
            'size':str,  
            'type':str,  
            'armor_class':str,  
            'armor_desc':int,  
            'hit_points':int,  
            'hit_dice':str,  
            'challenge_rating':str,  
            'img_main':str,
        }
        