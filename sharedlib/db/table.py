#external imports
from tinydb import Query, TinyDB, table, storages
import tinydb

import logging
log = logging.getLogger()

class Table:
    
    def __init__(self, name, path=None):
        """
        [summary]
        """
        db = TinyDB(f"{path}/{name}.json")
        self._table = db.table(name=name)

    @property
    def name(self):
        return self._table.name

    def update(self, object):
        """
        [summary]
        """
        if not object.get('pk'):
            doc_id = len(self._table)

            log.debug(f'doc_id: {doc_id}')
            
            object['pk'] = self._table.insert(table.Document(object, doc_id=doc_id+1))

            log.debug(f'after_insert: {object}')
            
        self._table.update(object, doc_ids=[object['pk']])
        return object.get('pk') 

    def delete(self, id):
        """
        [summary]
        """ 
        log.debug(id)

        result = self._table.remove(doc_ids=[id,])

        log.debug(result)

        return result

    def search(self, **kwargs):
        """
        Returns an list of objects based on passed arguments
        as key/value pairs
        """
        q = Query().fragment(kwargs)
        return self._table.search(q)

    def get(self, id):
        """
        [summary]
        """
        log.debug(f"get {id}")
        
        return self._table.get(doc_id=id)

    def all(self):
        return self._table.all()
    
    def __str__(self):
        return self._table.name




