FROM python:3.10

RUN apt-get update
RUN apt-get install -y build-essential wget git

# install dependencies
RUN pip install --upgrade pip
COPY ./requirements.txt /var/tmp/requirements.txt
RUN pip install -r /var/tmp/requirements.txt

COPY ./gunicorn.conf.py /var/gunicorn.conf.py


