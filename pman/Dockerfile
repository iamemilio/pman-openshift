#
# Dockerfile for pman repository.
#
# Build with
#
#   docker build -t <name> .
#
# For example if building a local version, you could do:
#
#   docker build -t local/pman .
#
# In the case of a proxy (located at 192.168.13.14:3128), do:
#
#    docker build --build-arg http_proxy=http://192.168.13.14:3128 -t local/pman .
#

FROM fnndsc/ubuntu-python3:latest
MAINTAINER fnndsc "dev@babymri.org"

COPY pman /tmp

RUN apt-get update \
  && apt-get install -y libssl-dev libcurl4-openssl-dev bsdmainutils \
  && pip3 install /tmp/pman \
  && pip3 install docker

COPY ./docker-entrypoint.py /dock/docker-entrypoint.py
RUN chmod 777 /dock && chmod 777 /dock/docker-entrypoint.py
ENTRYPOINT ["/dock/docker-entrypoint.py"]
EXPOSE 5010
