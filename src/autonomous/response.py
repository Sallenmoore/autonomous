import requests
from autonomous import log
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
        if not isinstance(data, list):data = [data]
        
        return {"results":jsonpickle.encode(data)}

    @classmethod
    def unpackage(cls, data=None):
        """
        _summary_

        _extended_summary_

        Args:
            data (_type_, optional): A dictionary of serializable data. Defaults to calling endpoint.

        Returns:
            _type_: _description_
        """
        #log(data)

        data = data.get('results')
        data = jsonpickle.decode(data)
        log(data)
        return data

    # @classmethod
    # def getjson(cls, uri):
    #     return cls.unpackage(requests.get(uri).json())

    # @classmethod
    # def postjson(cls, uri, data):
    #     pass

    # @classmethod
    # def encode(cls, record):
    #     if not record: 
    #         return None  
    #     elif isinstance(record, (tuple,list)):
    #         record = [cls.encode(r) for r in record]
    #     elif isinstance(record, (dict)):
    #         encoded_record = {}
    #         for k,v in record.items():
    #             encoded_record[k] = cls.encode(v)
    #         record = encoded_record
    #     else:
    #         record = jsonpickle.encode(v)
    #     return record

    # @classmethod
    # def decode(cls, record):
    #     if not record: 
    #         return None  
    #     elif isinstance(record, (tuple,list)):
    #         record = [cls.decode(r) for r in record]
    #     elif isinstance(record, (dict)):
    #         for k,v in record.items():
    #             encoded_record[k] = cls.decode(v)
    #         record = encoded_record
    #     else:
    #         record = jsonpickle.decode(v)
    #     return record 