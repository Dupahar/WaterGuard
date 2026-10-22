#!/bin/bash
# EC2 boot script (Amazon Linux 2023): fetch app + data from S3, secrets from SSM, run in Docker on port 80.
set -euxo pipefail
B=waterguard-deploy-641079926578
export AWS_DEFAULT_REGION=ap-south-1

fallocate -l 8G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
dnf install -y docker
systemctl enable --now docker

mkdir -p /opt/waterguard /data
for i in 1 2 3 4 5 6; do aws s3 cp s3://$B/app.tgz /opt/waterguard/app.tgz && break || sleep 10; done
aws s3 cp s3://$B/data.tgz /tmp/data.tgz
tar -xzf /opt/waterguard/app.tgz -C /opt/waterguard
tar -xzf /tmp/data.tgz -C /data --strip-components=1 && rm /tmp/data.tgz
aws ssm get-parameter --name /waterguard/env --with-decryption --query Parameter.Value --output text > /opt/waterguard/.env
chmod 600 /opt/waterguard/.env

cd /opt/waterguard
docker build -t waterguard .
# logs (incl. the inspector's metric lines, Embedded Metric Format) go to CloudWatch /waterguard/app
docker run -d --name waterguard --restart always -p 80:8000 -v /data:/data --env-file .env \n  --log-driver awslogs --log-opt awslogs-region=ap-south-1 --log-opt awslogs-group=/waterguard/app \n  --log-opt awslogs-create-group=true waterguard
