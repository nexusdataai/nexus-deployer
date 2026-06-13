#! /bin/bash

if [ -z "$TMPDIR" ]; then
    TMPDIR="/tmp"
else
    TMPDIR="${TMPDIR%/}"
fi

# Extract the credentials.bin file from the zip file
unzip -qq -o "$1" -d "$TMPDIR"

# Extracts properties from the /tmp/config.json file.
name=$(jq -r '.clientId' $TMPDIR/config.json)
endpoint=$(jq -r '.credentials' $TMPDIR/config.json)
envname=$(jq -r '.envName' $TMPDIR/config.json)

# Makes a cURL request to the AWS IoT credentials provider to get temporary security credentials.
creds_json=$(curl -s --cert $TMPDIR/cert.pem --key $TMPDIR/private.key -H "x-amzn-iot-thingname: ${name}" "https://${endpoint}/role-aliases/${envname}_RuntimeRoleAlias/credentials")

# Extract each parameter into a variable
export AWS_ACCESS_KEY_ID=$(echo "$creds_json" | jq -r '.credentials.accessKeyId')
export AWS_SECRET_ACCESS_KEY=$(echo "$creds_json" | jq -r '.credentials.secretAccessKey')
export AWS_SESSION_TOKEN=$(echo "$creds_json" | jq -r '.credentials.sessionToken')

# Remove the files unziped above
rm "$TMPDIR/config.json" "$TMPDIR/cert.pem" "$TMPDIR/private.key"

# Login to ECR / Docker Hub
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 008731404932.dkr.ecr.us-east-1.amazonaws.com
