# Import submodules so that we can expose their __all__
# Import everything from each submodule so that it can be accessed via
# autonomous.db, e.g. instead of `from autonomous.db.connection import connect`,
# users can simply use `from autonomous.db import connect`, or even
# `from autonomous.db import *` and then `connect('testdb')`.
from autonomous.db import (
    connection,
    document,
    errors,
    fields,
    queryset,
    signals,
)
from autonomous.db.connection import *  # noqa: F401
from autonomous.db.document import *  # noqa: F401
from autonomous.db.errors import *  # noqa: F401
from autonomous.db.fields import *  # noqa: F401
from autonomous.db.queryset import *  # noqa: F401
from autonomous.db.signals import *  # noqa: F401

__all__ = (
    list(document.__all__)
    + list(fields.__all__)
    + list(connection.__all__)
    + list(queryset.__all__)
    + list(signals.__all__)
    + list(errors.__all__)
)


VERSION = (0, 29, 0)


def get_version():
    """Return the VERSION as a string.

    For example, if `VERSION == (0, 10, 7)`, return '0.10.7'.
    """
    return ".".join(map(str, VERSION))


__version__ = get_version()
