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
            self.parseDict(json_block)
        elif isinstance(json_block, list):
            self.parseList(json_block)
        else:
            self.addValue(json_block)

    def parseDict(self, d):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                self.headerdepth += 1
                self.addHeader(k)
                self.parseJSON(v)
                self.headerdepth -= 1
            else:
                self.addLabeledValue(k, v)
        self.markdown += "\n"

    def parseList(self, l):
        for value in l:
            if isinstance(value, dict):
                self.listdepth = 0
                self.parseDict(value)
            elif isinstance(value, list):
                self.listdepth += 1
                self.parseList(value)
                self.listdepth -= 1
            else:
                self.addListItem(value)
        self.markdown += "\n"

    def addHeader(self, value):
        if self.headerdepth > 5:
            self.headerdepth = 5
        elif self.headerdepth > 1:
            self.markdown += "\n"
        self.listdepth = 0
        self.markdown += f"""{self.htag * (self.headerdepth)} {value}"""
        self.markdown += "\n\n"

    def addListItem(self, value):
        self.markdown += f"""{self.tab * self.listdepth}{self.list_tag}{value}"""
        self.markdown += "\n"

    def addValue(self, value):
        self.markdown += f"{value}"
        self.markdown += "\n\n"

    def addLabeledValue(self, key, value):
        self.headerdepth += 1
        self.addHeader(key)
        self.headerdepth -= 1
        self.addValue(value)

    def parse(self):
        self.parseJSON(self.record)
        self.markdown = self.markdown.replace("#######", "######")
        return self.markdown
