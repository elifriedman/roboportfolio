# Use Alpine Linux as the base image
FROM alpine:3.18

# Install required packages
RUN apk update && \
    apk add --no-cache openjdk17-jre yq

# Set the JAVA_HOME environment variable
ENV JAVA_HOME=/usr/lib/jvm/default-jvm

RUN mkdir -p /webapi

# Download the IBKR Client Portal ZIP file and extract it to /webapi
RUN wget https://download2.interactivebrokers.com/portal/clientportal.gw.zip && \
    unzip clientportal.gw.zip -d /webapi && \
    rm clientportal.gw.zip

WORKDIR /webapi

# Add the '172.*' IP range to the 'allow' list for docker
RUN yq eval -i '.ips.allow |= . + ["172.*"]' root/conf.yaml

# Expose port
EXPOSE 5000

# Start the API
CMD sh bin/run.sh root/conf.yaml
