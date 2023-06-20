from ...db.autodb import Database
from ...model.orm import ORM
import os
import sys


class DnDORM:
    def __init__(self, table):
        self._table = Database(
            path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db"
        ).get_table(table=table)
