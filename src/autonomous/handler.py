import requests
from autonomous import log
import jsonpickle
import json
from .model.basemodel import BaseModel, AutoModel


##############################################################################################
#
#    Network Handler
#
##############################################################################################
class NetworkHandler:
    @classmethod
    def package(cls, data, unpicklable=True):
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

        #log(data, isinstance(data, list))
        if not isinstance(data, list):
            data = [data]
        response = {"results":jsonpickle.encode(data, unpicklable=unpicklable)}
        #log(response)
        return response

    @classmethod
    def unpackage(cls, data):
        """
        _summary_

        _extended_summary_

        Args:
            data (_type_, optional): A dictionary of serializable data. Defaults to calling endpoint.

        Returns:
            _type_: _description_
        """
        results = None
        if data.get('results'): 
            #log(data.get('results'), type(data.get('results')))
            results = jsonpickle.decode(data['results'])
            #log(results)
        return results

    @classmethod
    def get(cls, url):
        """
        returns the raw json response from a class API endpoint

        Args:
            endpoint (str): the additional endpoint to append to the API_URL

        Returns:
            dict: the json response from the API converted to a dictionary
        """
        response = requests.get(url)
        #log(response.text)
        response = response.json()
        #log(response)
        try:
            response = cls.unpackage(response)
        except Exception as e:
            log(f"Error deserializing results: {e} \n results: {response}")
            raise
        return response

    @classmethod
    def post(cls, url, data, package=True):
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

        payload = cls.package(data) if package else data

        #log(f"endpoint: {endpoint}, payload: {payload}")
        resp = requests.post(url, json=payload, headers=headers).json()
        
        return cls.unpackage(resp) if package else resp

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