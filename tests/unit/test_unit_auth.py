from autonomous import log
from autonomous.auth.github import GithubAuth
from autonomous.auth.google import GoogleAuth
from autonomous.auth.user import User


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
        user_info = {
            "name": "test",
            "email": "test@test.com",
            "token": "testtoken",
        }
        User(**user_info).save()
        user = User.authenticate(user_info)
        user2 = User.authenticate(user_info)
        assert user.pk == user2.pk
        user.state = "unauthenticated"
        assert not user.is_authenticated
        res = user.save()
        user = User.authenticate(user_info)
        assert res == user
        assert user.pk == user2.pk
        assert user.is_authenticated
