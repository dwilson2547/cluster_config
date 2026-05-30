helm repo add bitnami https://charts.bitnami.com/bitnami
helm install my-postgresql bitnami/postgresql --version 16.7.27

helm pull oci://registry-1.docker.io/bitnamicharts/postgresql --version 16.7.27
