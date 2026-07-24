#!/bin/bash

set -e

echo "Starting deployment..."

cd /opt/media-platform


echo "Fetching latest code..."

git fetch origin

git  pull


echo "Restarting services..."

 docker compose --env-file .env -f compose/infrastructure.yml -f compose/services.yml up -d --build


echo "Deployment completed"
