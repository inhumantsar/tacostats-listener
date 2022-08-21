aws --region us-east-2 ecr get-login-password | docker login --username AWS --password-stdin 390721581096.dkr.ecr.us-east-2.amazonaws.com
$version = $(Get-Content VERSION)
docker build -t 390721581096.dkr.ecr.us-east-2.amazonaws.com/tacostats-listener:v$version -f .\Dockerfile .
docker push 390721581096.dkr.ecr.us-east-2.amazonaws.com/tacostats-listener:v$version
aws s3 cp .\cloudformation.yaml s3://inhumantsar-tacostats-cfn/listener.yaml
aws cloudformation update-stack --stack-name tacostats-listener --template-url https://inhumantsar-tacostats-cfn.s3.amazonaws.com/listener.yaml --capabilities CAPABILITY_NAMED_IAM