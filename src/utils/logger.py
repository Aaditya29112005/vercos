from aws_lambda_powertools import Logger, Tracer, Metrics

# Initialize the AWS Lambda Powertools structured Logger, Tracer, and Metrics
logger = Logger(service="drone-inspection-backend")
tracer = Tracer(service="drone-inspection-backend")
metrics = Metrics(namespace="DroneInspectionPlatform", service="drone-inspection-backend")
