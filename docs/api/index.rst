API Reference
=============

Auto-generated reference for the public surface of ``autonomous-app``.
Every module listed below is introspected at build time — signatures,
docstrings, and inheritance graphs come straight from the source.

If a class or function is missing here, it's either private
(``_underscore_prefixed``) or not re-exported from its package's
``__init__``. The vendored MongoEngine fork under ``autonomous.db.base``
and ``autonomous.db.queryset`` is intentionally excluded — use the
``autonomous.db`` package surface (``Document``, ``connect``,
``signals``, etc.) rather than reaching into the submodules.

.. autosummary::
   :toctree: generated

   autonomous
   autonomous.config
   autonomous.logger

ORM (``autonomous.model``, ``autonomous.db``)
---------------------------------------------

.. autosummary::
   :toctree: generated

   autonomous.model.automodel
   autonomous.model.autoattr
   autonomous.db

AI agents (``autonomous.ai``)
-----------------------------

.. autosummary::
   :toctree: generated

   autonomous.ai.baseagent
   autonomous.ai.jsonagent
   autonomous.ai.textagent
   autonomous.ai.imageagent
   autonomous.ai.audioagent
   autonomous.ai.retry
   autonomous.ai.models.local_model
   autonomous.ai.models.gemini
   autonomous.ai.models.openai_compat
   autonomous.ai.models.mock_model
   autonomous.ai.models.flux
   autonomous.ai.models.litellm

Auth (``autonomous.auth``)
--------------------------

.. autosummary::
   :toctree: generated

   autonomous.auth.autoauth
   autonomous.auth.user
   autonomous.auth.github
   autonomous.auth.google
   autonomous.auth.microsoft
   autonomous.auth.discord
   autonomous.auth.facebook

Web (``autonomous.web``)
------------------------

.. autosummary::
   :toctree: generated

   autonomous.web.response
   autonomous.web.session

Storage (``autonomous.storage``)
--------------------------------

.. autosummary::
   :toctree: generated

   autonomous.storage.localstorage
   autonomous.storage.imagestorage

Background tasks (``autonomous.taskrunner``)
--------------------------------------------

.. autosummary::
   :toctree: generated

   autonomous.taskrunner.autotasks

HTTP (``autonomous.http``)
--------------------------

.. autosummary::
   :toctree: generated

   autonomous.http
   autonomous.http.client

Observability (``autonomous.observability``)
--------------------------------------------

.. autosummary::
   :toctree: generated

   autonomous.observability
   autonomous.observability.metrics
   autonomous.observability.events
