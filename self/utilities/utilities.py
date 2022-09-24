import os, sys

######### CONSTANTS ###########
ROOT_DIR = os.path.dirname(sys.modules['__main__'].__file__)
APP_NAME = os.path.dirname(sys.modules['__main__'].__name__)


def zip_csv_to_dict(self, myfile):
    try:
        zf = ZipFile(myfile, 'r')
        in_file = zf.open(zf.filelist.pop(), 'r')
        return csv.DictReader(io.TextIOWrapper(in_file, 'utf-8'))
    except Exception as e:
        return []
