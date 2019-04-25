FROM python:3.6-alpine
MAINTAINER Jarrel Seah <jarrelscy@gmail.com>
COPY . /src
WORKDIR /src
RUN apk add --no-cache --virtual .build-deps gcc python3-dev linux-headers musl-dev
RUN pip install -r requirements.txt
RUN apk del .build-deps gcc python3-dev linux-headers musl-dev
