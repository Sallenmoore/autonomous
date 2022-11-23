import requests
from autonomous.logger import log
from autonomous.model.model import Model
import jsonpickle

class Response:

    @classmethod
    def package(cls, data):
        """
        _summary_

        _extended_summary_

        Args:
            error (str, optional): A description of the error that occured. Defaults to "".
            data (_type_, optional): A dictionary of serializable data. Defaults to calling endpoint.
            api_path (str, optional): _description_. Defaults to "/".

        Returns:
            _type_: _description_
        """

        #log(data)
        count = 0
        if not isinstance(data, (list, dict)):
            raise Exception("Data must be a list or dictionary")

        response = {"results":[]}
        for d in data:
            try:
                response["results"].append(d.serialize())
            except AttributeError:
                response["results"].append(d)

        log(response, LEVEL="DEBUG")
        return response

    @classmethod
    def unpackage(cls, data=None):
        """
        _summary_

        _extended_summary_

        Args:
            error (str, optional): A description of the error that occured. Defaults to "".
            data (_type_, optional): A dictionary of serializable data. Defaults to calling endpoint.
            api_path (str, optional): _description_. Defaults to "/".

        Returns:
            _type_: _description_
        """
        log(data, LEVEL="DEBUG")

        data = data.get('results', [])
        
        for i, o in enumerate(data):
            log(o)
            model = Model.model_loader(o['_auto_model'][1:-1])
            data[i] = model.deserialize(o)
            log(data[i])
                
        log(data, LEVEL="DEBUG")
        return data

    @classmethod
    def getjson(cls, uri):
        return cls.unpackage(requests.get(uri).json())

    @classmethod
    def postjson(cls, uri, data):
        pass