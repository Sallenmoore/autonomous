import os, sys
import inspect
from autonomous.model.model import Model
from autonomous import log

def zip_csv_to_dict(myfile):
    try:
        zf = ZipFile(myfile, 'r')
        in_file = zf.open(zf.filelist.pop(), 'r')
        return csv.DictReader(io.TextIOWrapper(in_file, 'utf-8'))
    except Exception as e:
        return []

