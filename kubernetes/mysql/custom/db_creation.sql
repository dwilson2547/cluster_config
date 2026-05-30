
create database photodump;

CREATE USER 'pduser'@'%' IDENTIFIED BY '';

grant all privileges on photodump.* to 'pduser'@'%';

flush privileges;