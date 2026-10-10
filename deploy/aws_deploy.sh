#!/bin/bash
# One-time AWS deploy of WaterGuard: IAM role, security group, EC2 (t3.xlarge), CloudFront (HTTPS).
# Assumes app.tgz / data.tgz are in s3://waterguard-deploy-641079926578 and /waterguard/env is in SSM.
set -euo pipefail
export AWS_PAGER="" AWS_REGION=ap-south-1 MSYS_NO_PATHCONV=1
HERE=$(cd "$(dirname "$0")" && pwd)
W() { if command -v cygpath >/dev/null; then echo "file://$(cygpath -w "$1")"; else echo "file://$1"; fi; }
TMP=$(mktemp -d)

echo "== IAM role WaterGuardEC2 (S3 read of the deploy bucket, SSM parameter /waterguard/*, Bedrock invoke, SSM agent)"
cat > $TMP/trust.json <<'J'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
J
cat > $TMP/policy.json <<'J'
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::waterguard-deploy-641079926578/*"},
 {"Effect":"Allow","Action":"ssm:GetParameter","Resource":"arn:aws:ssm:ap-south-1:641079926578:parameter/waterguard/*"},
 {"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream","bedrock:Converse","bedrock:ConverseStream"],
  "Resource":["arn:aws:bedrock:*::foundation-model/*","arn:aws:bedrock:*:641079926578:inference-profile/*"]}
]}
J
aws iam get-role --role-name WaterGuardEC2 >/dev/null 2>&1 || {
  aws iam create-role --role-name WaterGuardEC2 --assume-role-policy-document "$(W $TMP/trust.json)" >/dev/null
  aws iam attach-role-policy --role-name WaterGuardEC2 --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam create-instance-profile --instance-profile-name WaterGuardEC2 >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name WaterGuardEC2 --role-name WaterGuardEC2
  echo "   waiting for the instance profile to propagate"; sleep 15
}
aws iam put-role-policy --role-name WaterGuardEC2 --policy-name waterguard --policy-document "$(W $TMP/policy.json)"

echo "== Security group: port 80 open to CloudFront only"
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=waterguard Name=vpc-id,Values=$VPC --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name waterguard --description "WaterGuard web (CloudFront only)" --vpc-id $VPC --query GroupId --output text)
  PL=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query 'PrefixLists[0].PrefixListId' --output text)
  aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$PL}]" >/dev/null
fi

echo "== EC2 t3.xlarge"
AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
IID=$(aws ec2 run-instances --image-id $AMI --instance-type t3.xlarge --security-group-ids $SG \
  --iam-instance-profile Name=WaterGuardEC2 --user-data "$(W $HERE/user-data.sh)" \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=40,VolumeType=gp3}' \
  --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=waterguard}]' \
  --query 'Instances[0].InstanceId' --output text)
echo "   $IID"
aws ec2 wait instance-running --instance-ids $IID
DNS=$(aws ec2 describe-instances --instance-ids $IID --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
echo "   $DNS"

echo "== CloudFront (HTTPS, no caching)"
cat > $TMP/cf.json <<J
{"CallerReference":"waterguard-$(date +%s)","Comment":"WaterGuard","Enabled":true,"PriceClass":"PriceClass_200",
 "Origins":{"Quantity":1,"Items":[{"Id":"ec2","DomainName":"$DNS",
   "CustomOriginConfig":{"HTTPPort":80,"HTTPSPort":443,"OriginProtocolPolicy":"http-only","OriginReadTimeout":60,"OriginKeepaliveTimeout":5}}]},
 "DefaultCacheBehavior":{"TargetOriginId":"ec2","ViewerProtocolPolicy":"redirect-to-https","Compress":true,
   "AllowedMethods":{"Quantity":7,"Items":["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],"CachedMethods":{"Quantity":2,"Items":["GET","HEAD"]}},
   "CachePolicyId":"4135ea2d-6df8-44a3-9df3-4b5a84be39ad","OriginRequestPolicyId":"b689b0a8-53d0-40ab-baf2-68738e2966ac"}}
J
CF=$(aws cloudfront create-distribution --distribution-config "$(W $TMP/cf.json)" --query 'Distribution.[Id,DomainName]' --output text)
rm -rf $TMP
echo
echo "Instance:   $IID"
echo "CloudFront: $CF"
echo "Live URL (ready in ~10 min, after the server builds and CloudFront deploys): https://$(echo $CF | awk '{print $2}')"
