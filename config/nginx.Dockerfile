FROM nginx

RUN mkdir -p /srv/static
COPY ./nginx.conf /etc/nginx/nginx.conf