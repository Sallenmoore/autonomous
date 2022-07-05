from src.models.campaign.character import Character
from src.sharedlib.db import Table, Database
import pytest
from tinydb.storages import MemoryStorage
import logging
log = logging.getLogger()

@pytest.fixture
def session(): 
    db = Database(storage=MemoryStorage)
    yield db

@pytest.fixture
def test_obj(): 
    obj = {'name': 'Test', 'hp': 10, 'status': 'alive'}
    yield obj
    
def test_database(session):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    table = session.get_table("Test")
    assert table.name == "Test"
    assert table.all() == []
    

def test_table(session, test_obj):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    table = session.get_table("Test")
    assert str(table) == "Test"
    
    result = table.update(test_obj)
    log.debug(result)
    
    result = table.search(name=test_obj['name'], hp=test_obj['hp'])
    result = result.pop() #check first item in list
    assert result['name'] == test_obj['name']
    assert result['hp'] == test_obj['hp']
    assert result['status'] == test_obj['status']
    assert result['pk'] == test_obj['pk']

    result['hp'] = 20
    table.update(result) 
    result = table.get(result['pk'])
    assert result['name'] == test_obj['name']
    assert result['hp'] == result['hp']

    result['name'] = "Test2"
    del result['pk']
    log.debug(f"{type(result)}{result}")
    table.update(result)

    results = table.all()
    assert len(results) == 2
    assert results[0]['name'] == "Test2" or results[1]['name'] == "Test2"

    for result in results:
        table.delete(result['pk'])

    results = table.all()
    assert len(results) == 0