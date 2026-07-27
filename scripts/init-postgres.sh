#!/bin/bash
# Create the glpi_dw warehouse DB + a dedicated user, in addition to the default
# `airflow` DB the official image already provisions.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE USER glpi WITH PASSWORD 'glpi';
    CREATE DATABASE glpi_dw OWNER glpi;
    GRANT ALL PRIVILEGES ON DATABASE glpi_dw TO glpi;
EOSQL
