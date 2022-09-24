#external imports
import re

from tinydb import Query, TinyDB, table, storages, where
import tinydb

from sharedlib.logger import log

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
            
            object['pk'] = self._table.insert(table.Document(object, doc_id=doc_id+1))
            
        self._table.update(object, doc_ids=[object['pk']])
        return object.get('pk') 

    def delete(self, id):
        """
        [summary]
        """ 
        return self._table.remove(doc_ids=[id,])

    def search(self, **kwargs):
        """
        Returns an list of objects based on passed arguments
        as key/value pairs
        """
        matches_needed = len(kwargs)
        results = {}
        #log(f"kwargs: {kwargs}")
        for k,v in kwargs.items():

            q = Query()
            field = getattr(q, k)
            #log((f"table: {self._table.name} field : {field} -- searching for v : {v} "))
            v = v if isinstance(v, (list, tuple)) else [v]
            
            #log(f"v: {v}")
            #log(f"kwargs: {kwargs}")
            for term in v:
                log(f"v: {v}, term: {term}")
                records = self._table.search(field.search(term,flags=re.IGNORECASE))
                records = {r['pk']:r for r in records}
                results.update(records) 

        #log(f"table: {self._table.name} results: {results}")
        #log(f"results: {results}")
        return results.values()

    def get(self, obj_id):
        """
        [summary]
        """
        
        return self._table.get(doc_id=obj_id) if obj_id else None

    def all(self):
        return self._table.all()
    
    def __str__(self):
        return self._table.name




