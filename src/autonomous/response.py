import inspect
from autonomous.logger import log


class Response:

    @classmethod
    def package(cls, error="", data=None, api_path=""):
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

        if api_path == "":
            api_path = f"{inspect.stack()[1].function}"

        #log(data)
        count = 0
        if not isinstance(data, (list, tuple, dict)):
            data = [data,]
        count = len(data)

        response = []
        for d in data:
            try:
                response.append(d.serialize())
            except AttributeError:
                response.append(d)

        #log(response)
        results = {
            "api": api_path,
            "error":error,
            "results": response,
            "count": count
        }
        log(results, LEVEL="DEBUG")
        return results

    @classmethod
    def unpackage(cls, data=None, model=None):
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
        
        items = []
        for o in data.get('results',data.get('error', ["Unknown Error"])):
            if model:
                items.append(model.deserialize(o))
            else:
                items.append(d)
                
        log(data, LEVEL="DEBUG")
        return items