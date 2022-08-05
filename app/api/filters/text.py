import pdoc

def markdown_to_html(mkdn):
    return pdoc.render.to_html(mkdn)
