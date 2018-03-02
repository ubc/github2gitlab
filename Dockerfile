FROM python:2.7-alpine3.7

ENV PBR_VERSION=1.5.6

RUN apk add --update --no-cache git

WORKDIR /src

COPY . .

RUN pip install --no-cache-dir -e .

CMD [ "github2gitlab" ]
