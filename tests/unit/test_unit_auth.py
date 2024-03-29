import urllib.request

import pytest

from autonomous import log
from autonomous.auth import AutoAuth, auth_required
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
        # AutoUser.table().flush_table()
        user_info = {
            "name": "test",
            "email": "test@test.com",
            "token": "testtoken",
        }
        user = AutoUser.authenticate(user_info)
        user2 = AutoUser.authenticate(user_info)
        assert user.pk == user2.pk
        user.state = "unauthenticated"
        assert not user.is_authenticated
        pk = user.save()
        user = AutoUser.authenticate(user_info)
        assert pk == user.pk
        assert user.pk == user2.pk
        assert user.is_authenticated
