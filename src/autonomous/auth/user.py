from datetime import datetime

from autonomous import AutoModel


class AutoUser(AutoModel):
    attributes = {
        "name": "",
        "email": "",
        "last_login": datetime.now(),
        "auth": {"state": "unauthenticated", "token": "", "provider": ""},
    }
