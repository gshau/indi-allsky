#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


ALLSKY_DIRECTORY="/home/allsky/indi-allsky"
ALLSKY_ETC="/etc/indi-allsky"
DB_FOLDER="/var/lib/indi-allsky"
#DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
#SQLALCHEMY_DATABASE_URI="sqlite:///${DB_FILE}"
MIGRATION_FOLDER="$DB_FOLDER/migrations"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"
INDISERVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"


if [ "${INDI_ALLSKY_MARIADB_SSL:-false}" == "true" ]; then
    SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://${MARIADB_USER}:${MARIADB_PASSWORD}@${INDI_ALLSKY_MARIADB_HOST}:${INDI_ALLSKY_MARIADB_PORT}/${MARIADB_DATABASE}?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity"
else
    SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://${MARIADB_USER}:${MARIADB_PASSWORD}@${INDI_ALLSKY_MARIADB_HOST}:${INDI_ALLSKY_MARIADB_PORT}/${MARIADB_DATABASE}"
fi


# shellcheck disable=SC1091
source /home/allsky/venv/bin/activate


TMP_FLASK=$(mktemp --suffix=.json)
jq \
 --arg sqlalchemy_database_uri "$SQLALCHEMY_DATABASE_URI" \
 --arg indi_allsky_docroot "$HTDOCS_FOLDER" \
 --argjson indi_allsky_auth_all_views "$INDIALLSKY_FLASK_AUTH_ALL_VIEWS" \
 --arg migration_folder "$MIGRATION_FOLDER" \
 --arg allsky_service_name "${ALLSKY_SERVICE_NAME}.service" \
 --arg allsky_timer_name "${ALLSKY_SERVICE_NAME}.timer" \
 --arg indiserver_service_name "${INDISERVER_SERVICE_NAME}.service" \
 --arg indiserver_timer_name "${INDISERVER_SERVICE_NAME}.timer" \
 --arg gunicorn_service_name "${GUNICORN_SERVICE_NAME}.service" \
 '.SQLALCHEMY_DATABASE_URI = $sqlalchemy_database_uri | .INDI_ALLSKY_DOCROOT = $indi_allsky_docroot | .INDI_ALLSKY_AUTH_ALL_VIEWS = $indi_allsky_auth_all_views | .MIGRATION_FOLDER = $migration_folder | .ALLSKY_SERVICE_NAME = $allsky_service_name | .ALLSKY_TIMER_NAME = $allsky_timer_name | .INDISERVER_SERVICE_NAME = $indiserver_service_name | .INDISERVER_TIMER_NAME = $indiserver_timer_name | .GUNICORN_SERVICE_NAME = $gunicorn_service_name' \
 "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"
 

TMP_FLASK_KEYS=$(mktemp --suffix=.json)
jq \
 --arg secret_key "$INDIALLSKY_FLASK_SECRET_KEY" \
 --arg password_key "$INDIALLSKY_FLASK_PASSWORD_KEY" \
 '.SECRET_KEY = $secret_key | .PASSWORD_KEY = $password_key' \
 "${TMP_FLASK}" > "$TMP_FLASK_KEYS"


cp -f "$TMP_FLASK_KEYS" "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"
[[ -f "$TMP_FLASK_KEYS" ]] && rm -f "$TMP_FLASK_KEYS"


json_pp < "$ALLSKY_ETC/flask.json" >/dev/null


# wait for database and migrations
for X in $(seq 12); do
    echo "Waiting on migrations to complete ($((65-(5*X)))s)"
    sleep 5
done


cd "$ALLSKY_DIRECTORY"


# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
"${ALLSKY_DIRECTORY}/config.py" dump > "$TMP_CONFIG_DUMP"


# Detect IMAGE_FOLDER
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "$TMP_CONFIG_DUMP")
echo "Detected IMAGE_FOLDER: $IMAGE_FOLDER"


# replace the flask IMAGE_FOLDER
TMP_FLASK_3=$(mktemp --suffix=.json)
jq --arg image_folder "$IMAGE_FOLDER" '.INDI_ALLSKY_IMAGE_FOLDER = $image_folder' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_3"
cp -f "$TMP_FLASK_3" "${ALLSKY_ETC}/flask.json"
[[ -f "$TMP_FLASK_3" ]] && rm -f "$TMP_FLASK_3"


# replace indiserver host
INDI_SERVER=$(jq -r '.INDI_SERVER' "$TMP_CONFIG_DUMP")


# fix indi server hostname for docker
if [ "$INDI_SERVER" == "localhost" ]; then
    TMP_INDI_SERVER=$(mktemp --suffix=.json)
    jq \
     --arg indi_server "indiserver" \
     '.INDI_SERVER = $indi_server' \
     "$TMP_CONFIG_DUMP" > "$TMP_INDI_SERVER"
else
     TMP_INDI_SERVER="$TMP_CONFIG_DUMP"
fi


# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_INDI_SERVER" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"
[[ -f "$TMP_INDI_SERVER" ]] && rm -f "$TMP_INDI_SERVER"


# start the program
./allsky.py \
    --log stderr \
    run

