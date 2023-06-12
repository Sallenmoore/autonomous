import os
import subprocess

from jsmin import jsmin

from autonomous import log


def search_files_with_extension(directory, extension, exclude=[]):
    """Recursively search for files with given extension in a directory tree."""
    matching_files = []
    for root, dirs, files in os.walk(directory):
        for e in exclude:
            if e in root:
                continue

        for file in files:
            for e in exclude:
                if e in file:
                    continue

            if file.endswith(extension):
                matching_files.append(os.path.join(root, file))
    return matching_files


def dartsass(path="static/style/main.scss", output="static/style/main.css", **kwargs):
    # print(f"==========================> dartsass  {path}, {output}, {kwargs}")
    subprocess.run(["sass", f"{path}:{output}"], capture_output=True)


def javascript(files="main", path="static/js", **kwargs):
    # Defining the path to the folder where the JS files are saved
    # Getting all the files from that folder
    if isinstance(files, list):
        for f in files:
            javascript(files=f, path=path, **kwargs)
    else:
        output = f"{path}/{files}.min.js"

        libfiles = search_files_with_extension(
            f"{path}/autojs", ".js", exclude=["tests/"]
        )
        lib_content = []
        for entry in libfiles:
            with open(entry, "r") as file:
                lib_content.append(file.read())

        # log(files, mainjs_content)

        # Create new master file
        with open(output, "w") as mainjs:
            # Add contents of files to master
            for i in lib_content:
                mainjs.write(f"{i}\n")
            js_file = open(f"{path}/{files}.js").read()
            mainjs.write(f"{js_file}\n")

            if kwargs.get("minified"):
                with open(mainjs, "r+") as js_file:
                    minified = jsmin(js_file.read())
                    js_file.seek(0)
                    js_file.write(minified)


def build_assets(
    csspath="static/style/main.scss",
    cssoutput="static/style/main.css",
    jsfiles="main",
    jspath="static/js",
):
    dartsass(path=csspath, output=cssoutput)
    javascript(files=jsfiles, path=jspath)
