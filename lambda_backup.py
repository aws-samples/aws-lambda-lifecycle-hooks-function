import boto3
import json
import logging
import time

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
ssm_client = boto3.client("ssm")

LIFECYCLE_KEY = "LifecycleHookName"
ASG_KEY = "AutoScalingGroupName"
EC2_KEY = "EC2InstanceId"
DOCUMENT_NAME = "ASGLogBackup"
RESPONSE_DOCUMENT_KEY = "DocumentIdentifiers"

def check_response(response_json):
    try:
        if response_json['ResponseMetadata']['HTTPStatusCode'] == 200:
            return True
        else:
            return False
    except KeyError:
        return False

def list_document():
    document_filter_parameters = {'key': 'Name', 'value': DOCUMENT_NAME}
    response = ssm_client.list_documents(
        DocumentFilterList=[ document_filter_parameters ]
    )
    return response

def check_document():
    # If the document already exists, it will not create it.
    try:
        response = list_document()
        if check_response(response):
            logger.info("Documents list: %s", response)
            if response[RESPONSE_DOCUMENT_KEY]:
                logger.info("Documents exists: %s", response)
                return True
            else:
                return False
        else:
            logger.error("Documents' list error: %s", response)
            return False
    except Exception, e:
        logger.error("Document error: %s", str(e))
        return None   

def send_command(instance_id):
    # Until the document is not ready, waits in accordance to a backoff mechanism.
    while True:
        timewait = 1
        response = list_document()
        if any(response[RESPONSE_DOCUMENT_KEY]):
            break
        time.sleep(timewait)
        timewait += timewait
    try:
        response = ssm_client.send_command(
            InstanceIds = [ instance_id ], 
            DocumentName = DOCUMENT_NAME, 
            TimeoutSeconds = 120
            )
        if check_response(response):
            logger.info("Command sent: %s", response)       
            return response['Command']['CommandId']
        else:
            logger.error("Command could not be sent: %s", response)
            return None
    except Exception, e:
        logger.error("Command could not be sent: %s", str(e))
        return None

def check_command(command_id, instance_id):
    timewait = 1
    while True:
        response_iterator = ssm_client.list_command_invocations(
            CommandId = command_id, 
            InstanceId = instance_id, 
            Details=False
            )
        if check_response(response_iterator):
            response_iterator_status = response_iterator['CommandInvocations'][0]['Status']
            if response_iterator_status != 'Pending':
                if response_iterator_status == 'InProgress' or response_iterator_status == 'Success':
                    logging.info( "Status: %s", response_iterator_status)
                    return True
                else:
                    logging.error("ERROR: status: %s", response_iterator)
                    return False
        time.sleep(timewait)
        timewait += timewait

def abandon_lifecycle(life_cycle_hook, auto_scaling_group, instance_id):
    asg_client = boto3.client('autoscaling')
    try:
        response = asg_client.complete_lifecycle_action(
            LifecycleHookName=life_cycle_hook,
            AutoScalingGroupName=auto_scaling_group,
            LifecycleActionResult='ABANDON',
            InstanceId=instance_id
            )
        if check_response(response):
            logger.info("Lifecycle hook abandoned correctly: %s", response)
        else:
            logger.error("Lifecycle hook could not be abandoned: %s", response)
    except Exception, e:
        logger.error("Lifecycle hook abandon could not be executed: %s", str(e))
        return None    

def lambda_handler(event, context):
    try:
        logger.info(json.dumps(event))
        message = event['detail']
        if LIFECYCLE_KEY in message and ASG_KEY in message:
            life_cycle_hook = message[LIFECYCLE_KEY]
            auto_scaling_group = message[ASG_KEY]
            instance_id = message[EC2_KEY]
            if check_document():
                command_id = send_command(instance_id)
                if command_id != None:
                    if check_command(command_id, instance_id):
                        logging.info("Lambda executed correctly")
                    else:
                        abandon_lifecycle(life_cycle_hook, auto_scaling_group, instance_id)
                else:
                    abandon_lifecycle(life_cycle_hook, auto_scaling_group, instance_id)
            else:
                abandon_lifecycle(life_cycle_hook, auto_scaling_group, instance_id)
        else:
            logging.error("No valid JSON message: %s", parsed_message)
    except Exception, e:
        logging.error("Error: %s", str(e))