FROM alpine:3.20
RUN apk add --no-cache openssh-client
COPY egress.sh relay.sh /
ENTRYPOINT ["/bin/sh", "/egress.sh"]
