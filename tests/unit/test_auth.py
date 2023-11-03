import urllib.request

import pytest

from autonomous import AutoModel, log
from autonomous.auth.github import GithubAuth
from autonomous.auth.google import GoogleAuth
from autonomous.auth.user import AutoUser


class TestAuth:
    def test_google_auth(self):
        auth = GoogleAuth()
        uri, status = auth.authenticate()
        log(uri, status)
        assert uri
        assert status

    def test_github_auth(self):
        auth = GithubAuth()
        uri, status = auth.authenticate()
        log(uri, status)
        assert uri
        assert status

    def test_user(self):
        AutoUser.flush_table()
        user_info = {
            "name": "test",
            "email": "test@test.com",
            "token": "testtoken",
        }
        user = AutoUser.authenticate(user_info)
        user2 = AutoUser.authenticate(user_info)
        result = user2.save()
        assert user.pk == user2.pk
        assert user.pk == result.pk
        user.state = "unauthenticated"
        result = user.save()
        user = AutoUser.authenticate(user_info)
        assert result.pk == user.pk == user2.pk
