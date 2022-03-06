from flask import current_app
from api.models.compendium import Compendium
import urllib
import json
import pytest


def api_verification(test_client, test_search_terms, endpoint="search"):
    
    url = f'/compendium/{endpoint}{urllib.parse.urlencode(test_search_terms)}'
    current_app.logger.debug(f'REQUEST URL: {url}')
    response = test_client.get()
    data = response.data.decode('utf-8')
    current_app.logger.debug(f'RESPONSE DATA: {data}')
    result = json.loads(data)
    results = result.get("results")
    assert response.status_code == 200
    assert result 
    return result
 
def test_search_monsters(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_monsters")

def test_search_spells(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_spells")


def test_search_documents(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_documents")


def test_search_backgrounds(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_backgrounds")


def test_search_planes(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_planes")


def test_search_sections(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_sections")


def test_search_feats(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_feats")


def test_search_conditions(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_conditions")


def test_search_races(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_races")


def test_search_classes(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_classes")


def test_search_magicitems(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_magicitems")


def test_search_weapons(test_client, test_search_terms):
    """
    _summary_
    """
    result = api_verification(test_client, test_search_terms, endpoint="search_weapons")


def test_search(test_client, test_search_term):
    """
    _summary_
    """
    params=""
    if test_search_term:
        params=urllib.parse.urlencode({"text":test_search_term})
    current_app.logger.debug(f'PARAMS: {params}')
    response = test_client.get(f'/compendium/search{params}')
    assert response.status_code == 200
    assert json.loads(response.data.decode('utf-8')).get("results")