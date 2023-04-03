import os
import subprocess

from jsmin import jsmin


def dartsass(
    path="static/style/sass/main.scss", output="static/style/main.css", **kwargs
):
    # print(f"==========================> dartsass  {path}, {output}, {kwargs}")
    subprocess.run(["sass", f"{path}:{output}"], capture_output=True)


def javascript(path="static/js", output="static/main.js", **kwargs):
    # Defining the path to the folder where the JS files are saved
    # Getting all the files from that folder
    files = [
        os.path.join(path, f)
        for f in os.listdir(path)
        if os.path.isfile(os.path.join(path, f))
    ]

    # Create Array
    mainjs_content = []
    # Get contents of files
    for entry in files:
        with open(entry, "r") as file:
            mainjs_content.append(file.read())

    # Create new master file
    with open(output, "w") as mainjs:
        # Add contents of files to master
        for i in mainjs_content:
            mainjs.write(f"{i}\n")

    if kwargs.get("minified"):
        with open(mainjs, "r+") as js_file:
            minified = jsmin(js_file.read())
            js_file.seek(0)
            js_file.write(minified)


def build_assets(
    csspath="static/style/sass/main.scss",
    cssoutput="static/style/main.css",
    jspath="static/js",
    jsoutput="static/main.js",
):
    dartsass(path=csspath, output=cssoutput)
    javascript(path=jspath, output=jsoutput)
