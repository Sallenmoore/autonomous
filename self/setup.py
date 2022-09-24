from setuptools import setup, find_packages

VERSION = '0.0.1' 
DESCRIPTION = 'Self App Framework'
LONG_DESCRIPTION = 'app framework and stuff'

# Setting up
setup(
       # the name must match the folder name 'verysimplemodule'
        name="self", 
        version=VERSION,
        author="Steven Allen Moore",
        author_email="<samoore@binghamton.edu>",
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        packages=find_packages(),
        install_requires=[
            "libsass",
            "requests",
            "gunicorn",
            "pytest",
            "coverage",
            "tinydb",
            "pdoc",
        ], # add any additional packages that 
        # needs to be installed along with your package. Eg: 'caer'
        
        keywords=['python', 'app framework', 'self'],
        classifiers= [
            "Development Status :: 2 - Pre-Alpha",
            "Intended Audience :: Developers",
            "Programming Language :: Python :: 3",
            "Environment :: Web Environment",
            "Framework :: Flask",
            "Framework :: Pytest",
            "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)",
        ]
)