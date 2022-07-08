from src.sharedlib.db import Model
import logging
log = logging.getLogger()

class Character(Model):
    def model_attr(self) -> None:
        """
        _summary_

        _extended_summary_
        """
        self.image_url = str
        self.name = str
        self.player_class = str
        self.history = str
        self.hp = int
        self.status = str
        self.inventory = list

    @classmethod
    def search(cls, **kwargs):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        
        objs = cls.find(**kwargs) if kwargs else cls.all()
        # for o in objs:
        #     log.debug(str(o))
        return [o.serialize() for o in objs]

