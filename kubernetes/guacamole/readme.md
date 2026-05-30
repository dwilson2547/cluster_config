helm repo add dmunozv04 https://dmunozv04.github.io/charts
helm install my-guacamole dmunozv04/guacamole --version 0.1.8


helm repo add beryju https://charts.beryju.io
helm install guacamole beryju/guacamole

helm install postgresql bitnami/postgresql \
 --set auth.username=guacamole \
 --set auth.password=password \
 --set auth.postgresPassword=password \
 --set auth.database=guacamole --wait