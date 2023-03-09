from setuptools import find_packages, setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="autonomous",
    version="0.0.43",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    author="Steven Allen Moore",
    author_email="samoore@binghamton.edu",
    description="A containerized application framework for Python built on top of Flask",
    long_description=long_description,
    long_description_content_type="text/markdown",
    readme="README.md",
    url="https://github.com/Sallenmoore/autonomous",
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "Flask",
        "firebase-admin",
        "gunicorn",
        "requests",
        "pygit2",
        "PyGithub",
        "openai",
        "jsmin",
        "cssmin",
        "dotenv",
    ],
    extras_require={"dev": ["pytest", "coverage", "twine", "wheel"]},
)
