FROM python:3.10

RUN apt-get update
RUN apt-get install --no-install-recommends -y build-essential curl git

# Install the vendor applications
COPY ./vendor/dart-sass /var/dart-sass
ENV PATH="/var/dart-sass:${PATH}"

# install dependencies
RUN pip install --no-cache-dir --upgrade pip wheel
COPY ./requirements.txt /var/tmp/requirements.txt
RUN pip install -r /var/tmp/requirements.txt
RUN pip install autonomous==0.0.50 --extra-index-url https://test.pypi.org/simple/
RUN pip freeze > /var/tmp/requirements.txt.log

COPY ./vendor/gunicorn.conf.py /var/gunicorn.conf.py

