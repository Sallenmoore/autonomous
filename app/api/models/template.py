from src.sharedlib.db import Model

import logging
log = logging.getLogger()

class Template(Model):
    """
    _summary_

    _extended_summary_

    Args:
        Model (_type_): _description_
    """

    #########################################################################
    ##                        Required Methods                             ##
    #########################################################################
    def model_attr(self):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        return {
            "name":str,
        }


    #########################################################################
    ###                       @properties                                  ##
    #########################################################################

    #########################################################################
    ###                       Class Methods                                ##
    #########################################################################
    @classmethod
    def search(cls, **kwargs):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        
        objs = cls.find(**kwargs) if kwargs else cls.all()
        return [o.serialize() for o in objs]
