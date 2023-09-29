import pytest

from autonomous import log
from autonomous.auth.github import GithubAuth
from autonomous.auth.google import GoogleAuth


class TestAuth:
    def test_google_auth(self):
        auth = GoogleAuth()
        assert True == auth.authorize()
        assert False == auth.authorize()

    def test_github_auth(self):
        auth = GithubAuth()
        assert True == auth.authorize()
        assert False == auth.authorize()
