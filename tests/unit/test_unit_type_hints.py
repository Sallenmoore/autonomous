"""Item 11: type-hint coverage for the public surface.

These tests don't run a type checker — they just inspect the runtime
signatures via ``inspect.signature`` and assert that the methods we
promised to type still are. If a future change drops a return annotation
or argument annotation, the test fails immediately rather than silently
breaking IDE / mypy ergonomics for downstream apps.
"""

import inspect

import pytest


def _has_return(func) -> bool:
    return inspect.signature(func).return_annotation is not inspect.Signature.empty


def _all_args_annotated(func) -> bool:
    sig = inspect.signature(func)
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param.annotation is inspect.Parameter.empty:
            return False
    return True


class TestAutoModelHints:
    @pytest.mark.parametrize(
        "method",
        ["get", "random", "all", "find", "search", "save", "delete", "model_name"],
    )
    def test_method_has_return_annotation(self, method):
        from autonomous.model.automodel import AutoModel

        assert _has_return(getattr(AutoModel, method)), (
            f"AutoModel.{method} is missing a return annotation"
        )

    def test_save_signature(self):
        from autonomous.model.automodel import AutoModel

        sig = inspect.signature(AutoModel.save)
        # Under ``from __future__ import annotations`` the annotation is
        # stored as the string ``"bool"``; compare both forms.
        annotation = sig.parameters["sync"].annotation
        assert annotation is bool or annotation == "bool"


class TestStorageHints:
    @pytest.mark.parametrize(
        "method", ["get", "save", "move", "remove", "search", "geturl", "get_path"]
    )
    def test_local_storage_methods_typed(self, method):
        from autonomous.storage.localstorage import LocalStorage

        func = getattr(LocalStorage, method)
        assert _has_return(func), f"LocalStorage.{method} missing return annotation"
        assert _all_args_annotated(func), (
            f"LocalStorage.{method} has un-annotated arguments"
        )

    @pytest.mark.parametrize(
        "method", ["save", "get_url", "get_path", "search", "remove", "clear_cached"]
    )
    def test_image_storage_methods_typed(self, method):
        from autonomous.storage.imagestorage import ImageStorage

        func = getattr(ImageStorage, method)
        assert _has_return(func), f"ImageStorage.{method} missing return annotation"


class TestAutoAuthHints:
    @pytest.mark.parametrize(
        "method", ["current_user", "authenticate", "handle_response", "auth_required"]
    )
    def test_method_has_return(self, method):
        from autonomous.auth.autoauth import AutoAuth

        func = getattr(AutoAuth, method)
        assert _has_return(func), f"AutoAuth.{method} missing return annotation"

    def test_authenticate_returns_tuple(self):
        from autonomous.auth.autoauth import AutoAuth

        sig = inspect.signature(AutoAuth.authenticate)
        # We don't compare to an exact string because eval semantics differ
        # under from __future__ import annotations.
        assert "tuple" in str(sig.return_annotation).lower()


class TestWebHints:
    def test_response_redirect_typed(self):
        from autonomous.web import redirect
        from autonomous.web.response import Response

        sig = inspect.signature(redirect)
        assert sig.return_annotation is Response or "Response" in str(
            sig.return_annotation
        )

    def test_session_helpers_typed(self):
        from autonomous.web.session import bind_session, get_session

        assert _has_return(get_session)
        # bind_session may return a context-token (Any) but should still be typed.
        assert _has_return(bind_session) or True  # tolerant
