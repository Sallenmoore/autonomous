import json
import os


class WikiJSPage:
    def __init__(self, **kwargs):
        self.title: str = kwargs.get("title")
        self.description: str = kwargs.get("description")
        self.content: str = kwargs.get("content")
        self.id: int = kwargs.get("id")
        self.path: str = kwargs.get("path")
        self.updatedAt: str = kwargs.get("updatedAt")
        self.tags: list = []

        for t in kwargs.get("tags", []):
            if title := t.get("title"):
                self.tags.append(title)

    @property
    def url(self):
        return f"{os.environ.get('WIKIJS_BASE_URL')}/{self.path}"
    
    def __repr__(self):
        return json.dumps(self.__dict__, indent=4)
