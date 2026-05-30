helm repo add bitnami https://charts.bitnami.com/bitnami
helm install my-mysql bitnami/mysql --version 14.0.3

helm pull oci://registry-1.docker.io/bitnamicharts/mysql --version 14.0.3