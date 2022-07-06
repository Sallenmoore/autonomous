FROM python:3.9-alpine

RUN apk update && apk add --virtual build-dependencies build-base gcc wget git

# install dependencies
RUN pip install --upgrade pip
COPY ./requirements.txt /var/tmp/requirements.txt
RUN pip install -r /var/tmp/requirements.txt

COPY ./gunicorn.conf.py /var/gunicorn.conf.py

