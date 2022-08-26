import inspect
import logging
log = logging.getLogger()

def package_response(error="", data=None, api_path=""):
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

    count = 0
    if data:
        try:
            count = len(data)
        except TypeError:
            count = 1
    
    results = {
        "api": api_path,
        "error":error,
        "results": data,
        "count": count
    }
    #log.debug(f"results data: {results}")
    return results