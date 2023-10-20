import json

import pypandoc

from autonomous.apis import WikiJS


class MarkdownParser:
    """
    Parses a record into Markdown
    """

    def __init__(self, record):
        self.record = record
        self.markdown = ""
        self.tab = "  "
        self.list_tag = "- "
        self.htag = "#"
        self.listdepth = 0
        self.headerdepth = 0

    def parseJSON(self, json_block):
        if isinstance(json_block, dict):
            self.listdepth = 0
            self.parseDict(json_block)
        elif isinstance(json_block, list):
            self.parseList(json_block)
            self.listdepth += 1
            self.headerdepth = 0
        else:
            self.listdepth = 0
            self.addValue(json_block)

    def parseDict(self, d):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                self.addHeader(k)
                self.headerdepth += 1
                self.parseJSON(v)
            else:
                self.addLabeledValue(k, v)

    def parseList(self, l):
        for index, value in enumerate(l):
            if isinstance(value, (dict, list)):
                self.parseJSON(value)
            else:
                self.addListItem(value)

    def addHeader(self, value):
        chain = self.htag * (self.headerdepth + 1) + value + "\n\n"
        self.markdown += chain

    def addListItem(self, value):
        self.markdown += f"{self.tab * self.listdepth}{self.list_tag} {value}\n"

    def addValue(self, value):
        self.markdown += f"{value}\n"

    def addLabeledValue(self, key, value):
        self.markdown += f"{key}: {value}\n"

    def parse(self):
        self.parseJSON(self.record)
        # self.markdown = self.markdown.replace("#######", "######")
        return self.markdown


class Page:
    """
    Creates a Page object that can be converted to amrkdown and pushed to a wiki
    Object must be:
        - a dict
        - a class with a __dict__ attribute
        - a class with a serialize() method
    The default wiki is the built in WIkiJS container. Overwrite with your own wiki API by setting the `wiki_api` class attribute.
    Inherit from autonomous.wiki.Wiki abstract class for the required interface.
    """

    wiki_api = WikiJS()
    parser = MarkdownParser

    @classmethod
    def convert(cls, record, title):
        """
        Converts the object to markdown
        """
        page = {title: record}
        return cls.parser(page).parse()

    @classmethod
    def push(cls, obj, title, id=None, **kwargs):
        if hasattr(obj, "serialize"):
            record = obj.serialize()
            content = cls.convert(record, title)
        else:
            raise TypeError(
                f"Cannot create page from {type(obj)}. Must be a class with a serialize() method."
            )
        if id:
            return cls.wiki_api.update_page(id, content=content, **kwargs)
        else:
            return cls.wiki_api.create_page(
                title,
                content,
                path=kwargs["path"],
                description=kwargs.get("description", title),
                tags=kwargs.get("tags", []),
            )
