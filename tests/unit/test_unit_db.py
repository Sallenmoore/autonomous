# from autonomous import log
from pathlib import Path

import pytest

from autonomous import log
from autonomous.db.autodb import Database
from autonomous.db.table import AutoEscaper


class SubRecordTest:
    attributes = {"pk": None, "name": "buh"}

    def __init__(self, **kwargs):
        self.pk = None
        self.__dict__.update(kwargs)


class RecordTest:
    attributes = {"pk": None, "num": 5, "name": "buh", "sub": None}

    def __init__(self, **kwargs):
        self.pk = None
        self.num = 5
        self.name = "buh"
        self.sub = None
        self.__dict__.update(kwargs)


class TestDatabase:
    db = Database(
        host="localhost",
        port="10001",
        decode_responses=True,
    ).get_table("RecordTest", RecordTest.attributes)

    def test_encode_no_escaped_chars(self):
        assert AutoEscaper.encode("HelloWorld") == "HelloWorld"

    def test_encode_with_escaped_chars(self):
        value_str = "stevenallenmoore@gmail"
        encoded_str = AutoEscaper.encode(value_str)
        assert encoded_str == "stevenallenmoore\\@gmail"
        value_str = "stevenallenmoore.gmail"
        encoded_str = AutoEscaper.encode(value_str)
        assert encoded_str == "stevenallenmoore\\.gmail"

    def test_encode_with_multiple_escaped_chars(self):
        # Assuming that 'a' and 'b' are in cls.escaped_chars
        assert AutoEscaper.encode(".@") == "\\.\\@"
        value_str = "steven--allen;moo/re@gmai\l.com"
        encoded_str = AutoEscaper.encode(value_str)
        assert encoded_str == "steven\\-\\-allen\\;moo\\/re\\@gmai\\\l\\.com"

    def test_decode_no_escaped_chars(self):
        assert AutoEscaper.decode("Hello, World!") == "Hello, World!"

    def test_decode_with_escaped_chars(self):
        value_str = "stevenallenmoore\\@gmail"
        encoded_str = AutoEscaper.decode(value_str)
        assert encoded_str == "stevenallenmoore@gmail"
        value_str = "stevenallenmoore\\.gmail"
        encoded_str = AutoEscaper.decode(value_str)
        assert encoded_str == "stevenallenmoore.gmail"

    def test_decode_with_multiple_escaped_chars(self):
        # Assuming that 'a' and 'b' are in cls.escaped_chars
        assert AutoEscaper.decode("\\.\\@") == ".@"
        # Assuming that 'a' and 'b' are in cls.escaped_chars
        value_str = "steven\\-\\-allen\\;moo\\/re\\@gmai\\\l\\.com"
        decoded_str = AutoEscaper.decode(value_str)
        assert decoded_str == "steven--allen;moo/re@gmai\l.com"

    def test_db_create(self):
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert t.pk

    def test_db_count(self):
        num = self.db.count()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert self.db.count() == num + 1

    def test_db_clear(self):
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        self.db.clear()
        assert self.db.count() == 0
        assert len(self.db.all()) == 0

    def test_db_all(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert len(self.db.all()) == 1

    def test_db_random(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert self.db.random()

    def test_db_read(self):
        self.db.clear()
        t = RecordTest()
        pk = self.db.save(t.__dict__)
        model = self.db.get(pk)
        assert isinstance(model, dict)
        obj = RecordTest(**model)
        assert obj.pk == t.pk
        assert obj.num == t.num

    def test_db_update(self):
        self.db.clear()
        t = RecordTest()
        self.db.save(t.__dict__)
        t.num = 6
        self.db.save(t.__dict__)
        model = self.db.get(t.pk)
        log(type(model), model)
        assert isinstance(model, dict)
        obj = RecordTest(**model)
        assert obj.pk == t.pk
        assert t.num == obj.num == 6

    def test_db_delete(self):
        self.db.clear()
        t = RecordTest()
        self.db.save(t.__dict__)
        assert self.db.delete(t.pk) == 1

    def test_db_search(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        t.name = "change"
        self.db.save(t.__dict__)
        # log(self.db.explain(name="change"))
        assert all(isinstance(model, dict) for model in self.db.search(name="change"))
        assert len(self.db.search(name="buh")) == 0
        assert len(self.db.search(name="change")) == 1
        assert len(self.db.search(name="xxx")) == 0
        t.name = "stevenallenmoore@gmail.com"
        self.db.save(t.__dict__)
        log(self.db.all())
        # breakpoint()
        result = self.db.search(name="stevenallenmoore@gmail.com")
        assert result[0]["name"] == "stevenallenmoore@gmail.com"

        t.name = "ste--venallenm#oor e@gmail.com"
        self.db.save(t.__dict__)
        result = self.db.search(name="ste--venallenm#oor e@gmail.com")
        assert result[0]["name"] == "ste--venallenm#oor e@gmail.com"

    def test_db_fastsearch(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        t.name = "change"
        self.db.save(t.__dict__)
        # log(self.db.explain(name="change"))
        assert all(
            isinstance(model, dict) for model in self.db.fastsearch(name="change")
        )
        assert len(self.db.fastsearch(name="buh")) == 0
        assert len(self.db.fastsearch(name="change")) == 1
        assert len(self.db.fastsearch(name="xxx")) == 0
        t.name = "stevenallenmoore@gmail.com"
        self.db.save(t.__dict__)
        print(self.db.all())
        # breakpoint()
        result = self.db.fastsearch(name="stevenallenmoore@gmail.com")
        assert result[0]["name"] == "stevenallenmoore@gmail.com"

        t.name = "ste--venallenm#oor e@gmail.com"
        self.db.save(t.__dict__)
        result = self.db.fastsearch(name="ste--venallenm#oor e@gmail.com")
        assert result[0]["name"] == "ste--venallenm#oor e@gmail.com"

    @pytest.mark.skip(reason="not implemented")
    def test_subattribute_search(self):
        t = RecordTest()
        sub = SubRecordTest()
        sub.pk = self.db.save(sub.__dict__)
        t.sub = sub.__dict__
        self.db.save(t.__dict__)
        result = self.db.fastsearch(pk=sub.pk)
        assert len(result) == 1
        result = self.db.fastsearch(pk=000)
        assert len(result) == 0
