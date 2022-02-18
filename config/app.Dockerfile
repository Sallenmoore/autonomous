FROM python:3.9-alpine

RUN apk update && apk add --virtual build-dependencies build-base gcc wget git

# copy server script
COPY ./gunicorn.py /var/tmp/conf.py

# install dependencies
RUN pip install --upgrade pip
COPY ./requirements.txt /var/tmp/requirements.txt
RUN pip install -r /var/tmp/requirements.txt



