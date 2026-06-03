"""jsonschema must be importable as a core dependency (not [ai] extra).
The validation safety net in JSONAgent.generate relies on this being
available even when consumers haven't installed [ai]."""


def test_jsonschema_importable():
    import jsonschema  # noqa: F401
    # Sanity-check the Draft 2020-12 validator path used by _schema_validate.
    assert callable(jsonschema.validate)
