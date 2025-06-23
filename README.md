Docker Image Refresh
===================

[![](https://images.microbadger.com/badges/version/tuxity/docker-image-puller.svg)](https://hub.docker.com/r/tuxity/docker-image-puller/)
![](https://images.microbadger.com/badges/image/tuxity/docker-image-puller.svg)

Forked from https://hub.docker.com/r/tuxity/docker-image-puller because docker image puller is flawed in how it deconstructs image name making it unusable for any image registry on a non-standard port.

## Overview

If you work with docker and continuous integrations tools, you might need to update your images on your servers as soon as your build is finished.

This tool is a tiny webserver listening for a `POST` and automatically update the specified image using [Docker](https://docs.docker.com/engine/reference/api/docker_remote_api/) API.

You just have to run the image on your server, and configure your CI tool.

## Installation

Launch the image on your server, where the images you want to update are
```
docker run -d \
  --name docker-image-refresh \
  --env TOKEN=abcd4242 \
  --env REGISTRY_USER=uni \
  --env REGISTRY_PASSWD=password \
  --env REGISTRY_URL=https://some.regitry.fo \
  -p 8080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  yourimageregistry/docker-image-refresh
```

Available env variable:
```
TOKEN*
REGISTRY_USERNAME
REGISTRY_PASSWORD
REGISTRY_URL (default: https://index.docker.io/v1/)
HOST (default: 0.0.0.0)
PORT (default: 8080)
DEBUG (default: False)
```

\* mandatory variables. For `TOKEN` You can generate a random string, it's a security measure.

## Request
After running the container, you can make request to the server.

How to make a request from your CI pipeline:
```
curl -v -X POST \
  "https://docker-image-refresh:8080/images/pull" \
  -F "token=$WEBHOOK_TOKEN" \
  -F "restart_containers=true" \
  -F "image=$IMAGE"
```

replace $WEBHOOK_TOKEN and $IMAGE as needed.

## Logs

You can access container logs with
```
docker logs --follow docker-image-refresh
````

