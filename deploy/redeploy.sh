#!/bin/bash
# Update the running server to the app bundle in S3, with rollback. Runs ON the EC2 instance, e.g.:
#   git archive --format=tar.gz -o app.tgz HEAD Dockerfile LICENSE README.md requirements.txt contracts deploy docs scripts tests waterguard web
#   aws s3 cp app.tgz s3://waterguard-deploy-641079926578/app.tgz
#   aws ssm send-command --instance-ids <id> --document-name AWS-RunShellScript \
#       --parameters commands="aws s3 cp s3://waterguard-deploy-641079926578/app.tgz /tmp/app.tgz && tar -xzOf /tmp/app.tgz deploy/redeploy.sh | bash"
# /data (runs, caches) and /opt/waterguard/.env are kept. The analysis-code version that names reports on the
# ledger is carried over from the running container unless WATERGUARD_VERSION is given.
set -euo pipefail
B=waterguard-deploy-641079926578
export AWS_DEFAULT_REGION=ap-south-1
LOGS="--log-driver awslogs --log-opt awslogs-region=ap-south-1 --log-opt awslogs-group=/waterguard/app --log-opt awslogs-create-group=true"

V=${WATERGUARD_VERSION:-$(docker inspect waterguard --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | sed -n 's/^WATERGUARD_VERSION=//p' | head -1)}
[ -f /tmp/app.tgz ] || aws s3 cp s3://$B/app.tgz /tmp/app.tgz
rm -rf /opt/waterguard.new && mkdir -p /opt/waterguard.new
tar -xzf /tmp/app.tgz -C /opt/waterguard.new
cp /opt/waterguard/.env /opt/waterguard.new/.env

cd /opt/waterguard.new
docker build -q -t waterguard:new --build-arg WATERGUARD_VERSION="$V" .
docker tag waterguard:latest waterguard:prev

run() {  # image, extra docker args
  docker rm -f waterguard >/dev/null 2>&1 || true
  docker run -d --name waterguard --restart always -p 80:8000 -v /data:/data --env-file .env $2 "$1" >/dev/null
}
run waterguard:new "$LOGS"
for i in $(seq 1 30); do curl -fsS -o /dev/null http://localhost/ && break; sleep 2; done
if ! curl -fsS -o /dev/null http://localhost/; then
  echo "new container is not answering: rolling back"; docker logs --tail 40 waterguard || true
  cd /opt/waterguard && run waterguard:prev ""
  exit 1
fi
docker tag waterguard:new waterguard:latest
rm -rf /opt/waterguard.prev && mv /opt/waterguard /opt/waterguard.prev && mv /opt/waterguard.new /opt/waterguard
echo "deployed (analysis-code version $V); previous image kept as waterguard:prev"
