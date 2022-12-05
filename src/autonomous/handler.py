import requests
from autonomous import log
import jsonpickle
import json
from autonomous.model.basemodel import BaseModel, AutoModel

##############################################################################################
#
#    Network Handler
#
##############################################################################################
class AutoHandler(jsonpickle.handlers.BaseHandler):

    def flatten(self, obj, data):
        log(data, type(data))
        autom = AutoModel(obj, save=False)
        #Flatten obj into a json-friendly form and write result to data.
        log(autom, type(autom))
        data['autom']= json.dumps(autom.__dict__)
        return data

    def restore(self, data):
        log(data, type(data))
        return self.context.restore(data['autom'])
        #Restore an object of the registered type from the json-friendly representation obj and return it.


##############################################################################################
#
#    Network Handler
#
##############################################################################################
class NetworkHandler:
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
        
        #log(data)
        return data

    @classmethod
    def get_request(cls, url):
        """
        returns the raw json response from a class API endpoint

        Args:
            endpoint (str): the additional endpoint to append to the API_URL

        Returns:
            dict: the json response from the API converted to a dictionary
        """
        response = requests.get(url).json()
        #log(f"endpoint: {endpoint}, response: {response}")
        try:
            response = response.unpackage(response)
        except Exception as e:
            log(f"Error deserializing results: {e} \n results: {response}")
            raise
        return response

    @classmethod
    def post_request(cls, url, data):
        """
        _summary_

        Args:
            endpoint (_type_): _description_
            data (_type_): _description_
            redirect_path (str, optional): _description_. Defaults to "index".

        Returns:
            _type_: _description_
        """
        #log(f"endpoint: {endpoint} \ndata:{data.__dict__}")
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}

        payload = cls.package(data)

        #log(f"endpoint: {endpoint}, payload: {payload}")
        resp = requests.post(url, json=payload, headers=headers).json()
        
        return cls.unpackage(resp)

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