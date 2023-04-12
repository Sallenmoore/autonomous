import os
import subprocess

from jsmin import jsmin

from autonomous import log


def dartsass(path="static/style/main.scss", output="static/style/main.css", **kwargs):
    # print(f"==========================> dartsass  {path}, {output}, {kwargs}")
    subprocess.run(["sass", f"{path}:{output}"], capture_output=True)


def javascript(path="static/js", output="static/js/main.min.js", **kwargs):
    # Defining the path to the folder where the JS files are saved
    # Getting all the files from that folder
    files = []
    for f in os.listdir(path):
        fn = os.path.join(path, f)
        # log(fn)
        if os.path.isfile(fn) and f != os.path.basename(output):
            files.append(fn)
    # log(files)

    # Create Array
    mainjs_content = []
    # Get contents of files
    for entry in files:
        with open(entry, "r") as file:
            mainjs_content.append(file.read())

    # log(files, mainjs_content)

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
    csspath="static/style/main.scss",
    cssoutput="static/style/main.css",
    jspath="static/js",
    jsoutput="static/js/main.min.js",
):
    dartsass(path=csspath, output=cssoutput)
    javascript(path=jspath, output=jsoutput)
