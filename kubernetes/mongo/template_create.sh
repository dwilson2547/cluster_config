#!/bin/bash

 helm template mongodb oci://registry-1.docker.io/bitnamicharts/mongodb --version 16.5.45 --namespace=mongodb --create-namespace > mongodb_manifest.yaml