#!/bin/bash

 helm template postgres oci://registry-1.docker.io/bitnamicharts/postgresql  --version 16.7.27 --namespace=postgres --create-namespace > postgres_manifest.yaml