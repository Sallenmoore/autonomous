FROM python:3.9

RUN apt-get update && apt-get install -y build-essential gcc wget git pandoc

# install dependencies
RUN pip install --upgrade pip
COPY ./requirements.txt /var/tmp/requirements.txt
RUN pip install -r /var/tmp/requirements.txt

COPY ./gunicorn.py /var/gunicorn.conf.py


