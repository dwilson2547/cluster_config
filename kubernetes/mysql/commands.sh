#!/bin/bash

# create sql to dump table to csv

echo "SELECT *" > script.sql
echo "FROM parts_direct.car" >> script.sql
echo "INTO OUTFILE '/var/lib/mysql-files/car.csv'" >> script.sql
echo "FIELDS TERMINATED BY ';'" >> script.sql
echo "ENCLOSED BY '\"'" >> script.sql
echo "LINES TERMINATED BY '\n';" >> script.sql


# create sql to load table from csv

echo "LOAD DATA INFILE '/var/lib/mysql-files/file.csv'" >> script.sql
echo "INTO TABLE your_table_name" >> script.sql
echo "FIELDS TERMINATED BY ','" >> script.sql
echo "ENCLOSED BY '\"'" >> script.sql
echo "LINES TERMINATED BY '\n'" >> script.sql
echo "IGNORE 1 ROWS;" >> script.sql

# Execute script

echo "mysql -u root -p parts_direct < /var/lib/mysql/script.sql" > run.sh