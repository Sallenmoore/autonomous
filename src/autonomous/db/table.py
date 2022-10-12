#external imports
import re

from tinydb import Query, TinyDB, table, storages, where
import tinydb
import jsonpickle

from autonomous.logger import log

class Table:
    
    def __init__(self, name, path=None):
        """
        [summary]
        """
        db = TinyDB(f"{path}/{name}.json")
        self._table = db.table(name=name)

    def pickle(self, data):
        """
        [summary]
        """
        #log(data)
        pdata = jsonpickle.encode(data, warn=True, indent=2)
        #log(pdata)
        rdata = jsonpickle.decode(pdata)
        #log(rdata)
        return {'serialized_data':pdata}

    def unpickle(self, data):
        """
        [summary]
        """
        return jsonpickle.decode(data['serialized_data']) if data else None

    @property
    def name(self):
        return self._table.name

    def update(self, obj):
        """
        [summary]
        """
        if not hasattr(obj, 'pk') or not obj.pk:
            obj.pk = self._table.all()[-1].doc_id+1
        self._table.upsert(table.Document(self.pickle(obj), doc_id=obj.pk))
        #log(f"updated - obj: {obj.name}")
        return obj.pk 

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
            log("No objects found")
            return []
        matches = []
        for obj in objs:
            match_count = 0
            for k, v in search_terms.items():
                if isinstance(v, list):
                    for term in v:
                        #log(f"obj: {obj} k: {k}, term: {term} ")
                        if getattr(obj,k) and str(term).lower() in str(getattr(obj,k)).lower():
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
        
        #log(f"search_terms: {search_terms}")
        
        # matches = {}
        # query = Query()
        # for k, v in search_terms.items():
        #     q = getattr(query, k)
        #     if not isinstance(v, list):
        #         v = [v]
        #     pks = []
        #     for t in v:
        #         log(f"searching {k}: {t}")
        #         results = self._table.search(q.search(t))
        #         log(f"results: {results}")
        #         matches.update({r.doc_id: matches.get(r.doc_id, 0) + 1 for r in results})
        # log(f"matches: {matches}")
        #return [self.get(pk) for pk, match_count in matches.items() if match_count == matches_needed]

    def get(self, obj_id):
        """
        [summary]
        """
        #log(f"obj_id: {obj_id}")
        obj = self.unpickle(self._table.get(doc_id=obj_id)) if obj_id else None
        return obj

    def all(self):
        results = [self.unpickle(d) for d in self._table.all()]
        return results
    
    def __str__(self):
        return self.name




