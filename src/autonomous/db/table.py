#external imports
import tinydb
from autonomous.model.basemodel import BaseModel, AutoModel
from autonomous.db.storage import JSONPickleStorage
from autonomous import log
import json
import re

class Table:
    
    def __init__(self, name, path=None):
        """
        [summary]
        """
        self.path = path
        #breakpoint()
        self._table = tinydb.TinyDB(f"{self.path}/{name}.json", storage=JSONPickleStorage).table(name=name)

    @property
    def name(self):
        return self._table.name

    def update(self, obj):
        """
        [summary]
        """
        #log(obj)
        if not obj._auto_pk:
            obj._auto_pk = self._table.insert(obj.__dict__)
        #log(obj, len(self._table))
        self._table.update(obj.__dict__, doc_ids=[obj._auto_pk]).pop()
        #log(f"_auto_pk:{pk}")
        #breakpoint()
        return obj._auto_pk

    def count(self):
        return len(self._table)

    def delete(self, pk):
        """
        [summary]
        """ 
        try:
            self._table.remove(doc_ids=[pk,]) 
        except Exception as e:
            log(e)
            return pk
        else:
            return None

    def search(self, **search_terms):
        """
        Returns an list of objects based on passed arguments
        as key/value pairs
        """
        matches = []
        if objs := self.all():
          for k, v in search_terms.items():
            if not v: continue
            query = getattr(tinydb.Query(), k)
            if isinstance(v, str):
              search_text = v.strip().split()
              query = query.search(search_text.pop(0), flags=re.IGNORECASE)
              while len(search_text):
                 query = query & query.search(first, flags=re.IGNORECASE)
            else:
              query = query.search(v)

            matches += self._table.search(query)

        filtered_matches = [] 
        filtered_matches = filter(lambda m: m not in filtered_matches, matches)
        #log(list(matches))
        #log(list(map(lambda m : id(m), matches)))
        return matches

    def get(self, obj_id):
        """
        [summary]
        """
        
        obj = None
        if isinstance(obj_id, int):
            #breakpoint()
            obj = self._table.get(doc_id=obj_id)
            #breakpoint()
            #log(obj_id, obj, self, self._table)
        return obj

    def all(self):
        result = self._table.all()
        #log(result)
        return result
    
    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def clear(self):
        len(self._table) and self._table.truncate()




