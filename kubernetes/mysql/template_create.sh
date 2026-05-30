#!/bin/bash

 helm template mysql oci://registry-1.docker.io/bitnamicharts/mysql   --version 14.0.3 --namespace=mysql --create-namespace > mysql_manifest.yaml
