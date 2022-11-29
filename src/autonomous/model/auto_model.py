from .model import Model
from .proxymodel import Proxy
from autonomous import log
    
class AutoModel:

###########################################################################################
##                                    DUNDER METHODS                                     ##
###########################################################################################

    def __init__(self, model, pk, **kwargs):
        """
        _summary_

        args:
            - attributes: a dict of attributes and their types

        Raises:
            Exception: _description_
        """
        


###########################################################################################
##                                  INSTANCE METHODS                                     ##
###########################################################################################

    # def get_record(self):
    #     """
    #     _summary_

    #     _extended_summary_

    #     Returns:
    #         _type_: _description_
    #     """
    #     obj_dict = {}
    #     for k,v in self.__dict__.items():
    #         try:
    #             json.dumps(v)
    #         except Exception as e:
    #             log(f"{e}: cannot jsonify attribute {k}: {v}")
    #         else:
    #             obj_dict[k] = v
    #     return obj_dict

    def delete(self, api_path="delete"):
        """
        _summary_

        _extended_summary_

        Args:
            api_path (str, optional): _description_. Defaults to "delete".

        Returns:
            _type_: _description_
        """
        #log(f"pk: {self.pk}:{type(self.pk)}")
        return self._post(api_path, self.pk) if self.pk else None

    def save(self, api_path="create"):
        """
        If the record has a pk, then switches to update. Otherwise,
        creates a new record and sets the pk.

        Args:
            api_path (str, optional): the endpoint save path if not 'create'. Defaults to "create".
        """
        #log(self)
        self._proxy_auto_models()
        
        if self.pk:
            api_path = "update"
        result = self._post(api_path, self)[0]
        return result['_auto_pk']

###########################################################################################
##                                     CLASS METHODS                                     ##
###########################################################################################
    
    @classmethod
    def _post(cls, endpoint, data):
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

        if not isinstance(data, (list)): data = [data]
        
        payload = response.package(data)
        
        #log(f"endpoint: {endpoint}, payload: {payload}")
        response = requests.post(f"{cls.API_URL}/{endpoint}", json=payload, headers=headers).json()
        response = response.unpackage(response)
        #log(f"endpoint: {endpoint}, response: {response}")
        return response


    @classmethod
    def _get(cls, endpoint):
        """
        returns the raw json response from a class API endpoint

        Args:
            endpoint (str): the additional endpoint to append to the API_URL

        Returns:
            dict: the json response from the API converted to a dictionary
        """
        response = requests.get(f"{cls.API_URL}/{endpoint}").json()
        #log(f"endpoint: {endpoint}, response: {response}")
        try:
            response = response.unpackage(response)
        except Exception as e:
            log(f"Error deserializing results: {e} \n results: {response}")
            raise
        return response

    @classmethod
    def get(cls, pk):
        """
        get a single record from the api based on the pk

        Args:
            pk (int): primary key of the requested record

        Returns:
            dict: a dictionary of the requested record
        """
        
        obj =  cls._get(pk)
        #log(f"obj: {obj}")
        return cls(**obj[0]) if obj else None

    @classmethod
    def search(cls, **kwargs):
        """
        returns objects filtered by search terms
        Args:
            text (_type_, optional): _description_. Defaults to None.
        Returns:
            _type_: _description_
        """
        
        if not kwargs: return None
        
        endpoint = f"search?{urllib.parse.urlencode(kwargs)}"

        #log(endpoint)
        result = [cls(**r) for r in cls._get(endpoint)]
        return result

    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        #log(endpoint)
        result = [cls(**r) for r in cls._get('all')]
        return result
