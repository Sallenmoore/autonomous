from setuptools import setup
import os

setup(
    name=os.environ.get("FLASK_APP"),
    packages=[os.environ.get("FLASK_APP")],
    include_package_data=True,
    install_requires=[
        'flask',
    ],
)