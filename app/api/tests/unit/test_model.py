from src.models.campaign.character import Character
import pytest
import logging
log = logging.getLogger()

@pytest.fixture
def test_obj(): 
    testchar = Character(
        name="Test Character", 
        image_url = "test.png",
        player_class = "Test",
        history = "Test",
        hp = 100,
        status = "None",
        inventory = ["Test Item #1", "Test Item #2"]
    )
    yield testchar
    
def test_create_character_model(test_obj):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    assert test_obj.name == "Test Character"
    assert test_obj.image_url == "test.png"
    assert test_obj.player_class == "Test"
    assert test_obj.history == "Test"
    assert test_obj.hp == 100
    assert test_obj.status == "None"
    assert test_obj.inventory == ["Test Item #1", "Test Item #2"]
    assert test_obj.pk == int
    log.debug("Here")
    pk = test_obj.save()
    test_obj.pk = None
    test_obj.save()
    result = Character.get(pk)
    assert isinstance(result, Character)
    assert result.name == test_obj.name
    assert result.image_url == test_obj.image_url
    assert result.player_class == test_obj.player_class
    assert result.history == test_obj.history
    assert result.hp == test_obj.hp
    assert result.status == test_obj.status
    assert result.inventory == test_obj.inventory

def test_read_character_model(test_obj):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    pk = test_obj.save()
    found = Character.find(player_class="Test")
    got = Character.get(pk)
    
    assert pk
    assert all(f.name == "Test Character" for f in found)
    assert got.name == test_obj.name

def test_update_character_model(test_obj):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    pk = test_obj.save()
    results = Character.find(player_class="Test")
    for r in results:
        r.hp = 50
        r.save()
    results = Character.find(player_class="Test")
    for r in results:
        assert r.hp == 50
    

def test_delete(test_obj):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    pk = test_obj.save()
    results = Character.find(player_class="Test")
    for i in results:
        i.delete()

    assert  len(Character.find(player_class="Test")) == 0
