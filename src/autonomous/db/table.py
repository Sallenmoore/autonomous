import json

import tinydb

from autonomous import log

from .storage import AutoStorage


class Table:
    def __init__(self, name, path="."):
        """
        [summary]
        """
        self.path = path
        # breakpoint()
        self._table = tinydb.TinyDB(f"{self.path}/{name}.json").table(name=name)

    @property
    def name(self):
        return self._table.name

    def save(self, obj):
        """
        [summary]
        """
        # log(obj)
        if not obj["pk"]:
            obj["pk"] = self._table.insert(obj)
        # log(obj, len(self._table))
        self._table.update(obj, doc_ids=[obj["pk"]])
        # log(f"_auto_pk:{pk}")
        return obj["pk"]

    def count(self):
        return len(self._table)

    def delete(self, pk):
        """
        [summary]
        """
        try:
            self._table.remove(
                doc_ids=[
                    pk,
                ]
            )
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
        for k, v in search_terms.items():
            if not v:
                continue
            query = tinydb.Query()[k]
            if isinstance(v, str):
                search_text = v.strip().split()

                def test_contains(value):
                    return any(s in value for s in search_text)

                # breakpoint()
                results = self._table.search(query.test(test_contains))
            else:
                results = self._table.search(query.search(v))

            matches += results

        filtered_matches = []
        filtered_matches = filter(lambda m: m not in filtered_matches, matches)
        # log(list(matches))
        # log(list(map(lambda m : id(m), matches)))
        return matches

    def get(self, pk):
        """
        [summary]
        """

        obj = None
        if isinstance(pk, int):
            # breakpoint()
            obj = self._table.get(doc_id=pk)
            # breakpoint()
            # log(obj_id, obj, self, self._table)
        return obj

    def all(self):
        result = self._table.all()
        # log(result)
        return result

    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def clear(self):
        len(self._table) and self._table.truncate()
