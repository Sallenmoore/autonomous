FROM python:3.9

RUN apt-get update && apt-get install -y build-essential gcc wget git pandoc

# install dependencies
RUN pip install --upgrade pip
RUN pip install -i https://test.pypi.org/simple/ autonomous
COPY ./requirements.txt /var/tmp/requirements.txt
RUN pip install -r /var/tmp/requirements.txt

COPY ./gunicorn.conf.py /var/gunicorn.conf.py


