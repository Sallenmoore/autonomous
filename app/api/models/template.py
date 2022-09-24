from self.db import Model

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
