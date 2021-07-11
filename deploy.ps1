aws --region us-west-2 ecr get-login-password | docker login --username AWS --password-stdin 676444348764.dkr.ecr.us-west-2.amazonaws.com
$version = $(Get-Content VERSION)
docker build -t 676444348764.dkr.ecr.us-west-2.amazonaws.com/tacostats-listener:v$version -f .\Dockerfile .
docker push 676444348764.dkr.ecr.us-west-2.amazonaws.com/tacostats-listener:v$version
aws s3 cp .\cloudformation.yaml s3://tacostats-cfn/listener.yaml
aws cloudformation update-stack --stack-name tacostats-listener --template-url https://tacostats-cfn.s3.amazonaws.com/listener.yaml --capabilities CAPABILITY_NAMED_IAM