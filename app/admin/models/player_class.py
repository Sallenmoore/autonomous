from sharedlib.model.APIModel import APIModel

class PlayerClass(APIModel):
    API_URL="http://api:44666/compendium/player_class"

    @classmethod
    def  class_list(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        results = cls.all()

        log.debug(f"results: {results}")

        return [r.name for r in results['results']]