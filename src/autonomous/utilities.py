import os, sys
import inspect
from autonomous.model.model import Model
from autonomous.logger import log

def zip_csv_to_dict(myfile):
    try:
        zf = ZipFile(myfile, 'r')
        in_file = zf.open(zf.filelist.pop(), 'r')
        return csv.DictReader(io.TextIOWrapper(in_file, 'utf-8'))
    except Exception as e:
        return []

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

    #log(data)
    count = 0
    if not isinstance(data, (list, tuple, dict)):
        data = [data,]
    count = len(data)
    try:
        response = [d.serialize() for d in data]
    except AttributeError:
        response = data

    #log(response)
    results = {
        "api": api_path,
        "error":error,
        "results": response,
        "count": count
    }
    #log(results)
    return results

def unpackage_response(data=None):
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
    data = data['data']
    items = Model.deserialize(data)
    #log(f"items: {items}")
    
    return items