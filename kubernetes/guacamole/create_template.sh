#!/bin/bash

helm template guacamole beryju/guacamole --version 1.4.2 --namespace=guacamole --create-namespace > guacd_manifest.yaml