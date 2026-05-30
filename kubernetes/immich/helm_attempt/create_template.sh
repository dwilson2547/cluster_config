#!/bin/bash

helm template immich oci://ghcr.io/immich-app/immich-charts/immich --namespace=immich --create-namespace -f values.yml > immich_manifest.yaml