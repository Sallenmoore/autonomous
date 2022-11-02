#external imports
import re

from tinydb import Query, TinyDB, table, storages, where
import tinydb
from autonomous.logger import log

import jsonpickle

class Table:
    
    def __init__(self, name, path=None):
        """
        [summary]
        """
        self.path = path
        db = TinyDB(f"{self.path}/{name}.json")
        self._table = db.table(name=name)

    @property
    def db(self):
        return TinyDB(f"{self.path}/{self.name}.json")

    @property
    def name(self):
        return self._table.name

    def update(self, obj):
        """
        [summary]
        """
        #log(obj)
        #make it work even if pk has not been pickled
        try:
            pk = jsonpickle.decode(obj.get('pk'))
        except TypeError:
            pk = obj.get('pk')
        #log(obj, pk)      
        if not pk:
            #log(len(self._table))
            #log(self._table.all()[-1])
            pk = self._table.all()[-1].doc_id+1 if len(self._table) else 1
            obj["pk"] = jsonpickle.encode(pk)

        #log(f"pk: {obj['pk']}")
        new_pk = self._table.upsert(table.Document(obj, doc_id=pk)).pop()
        #log(f"old_pk:{pk}, new_pk:{new_pk}")
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
            #log(e)
            return None
        else:
            return pk

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
            obj = self._table.get(doc_id=obj_id)
        return obj

    def all(self):
        return self._table.all()
    
    def __str__(self):
        return self.name

    def clear(self):
        self._table.truncate()




