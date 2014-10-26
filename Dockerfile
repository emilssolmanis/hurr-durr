# DOCKER-VERSION 1.3.0
FROM debian:wheezy

MAINTAINER Emils Solmanis <emils.solmanis@gmail.com>

RUN apt-get update && apt-get install -y python-pip python-dev

COPY . /src
RUN cd /src; python2 setup.py install
