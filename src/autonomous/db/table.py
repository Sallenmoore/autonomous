#external imports
import tinydb
from autonomous.db.storage import JSONPickleStorage
from autonomous import log
import json

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
            obj._auto_pk = self._table.all()[-1].doc_id+1 if len(self._table) else 1
        #log(obj, len(self._table))
        pk = self._table.upsert(tinydb.table.Document(obj.__dict__, doc_id=obj._auto_pk)).pop()
        #log(f"_auto_pk:{pk}")
        #breakpoint()
        return pk

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

    def search(self, **kwargs):
        """
        Returns an list of objects based on passed arguments
        as key/value pairs
        """
        matches_needed = len(kwargs)
        
        search_terms = {}
        for key, value in kwargs.items():
            if isinstance(value, str):
                search_terms[key] = value.lower().split()
                matches_needed += len(search_terms[key]) - 1
            else:
                search_terms[key] = value
                
        objs = self.all()
        if not objs:
            #"No objects found")
            return []
        matches = []
        for obj in objs:
            match_count = 0
            for k, v in search_terms.items():
                if isinstance(v, list):
                    for term in v:
                        #log(f"obj: {obj} k: {k}, term: {term} ")
                        if k in obj and str(term).lower() in str(obj[k]).lower():
                            match_count += 1
                elif isinstance(v, str) and v.lower() in str(obj[k]).lower():
                    match_count += 1
                elif v == obj[k]:
                    match_count += 1
            if match_count == matches_needed:
                #log(f"obj.name: {obj.name} match_count: {match_count}")
                matches.append(obj)
        #log(f"matches: {matches}")
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




