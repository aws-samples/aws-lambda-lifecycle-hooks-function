# aws-lambda-lifecycle-hooks-function
#Using Auto Scaling lifecycle hooks, Lambda, and EC2 Run Command

##Introduction

When an Auto Scaling group needs to scale in, replace an unhealthy instance, or re-balance Availability Zones, the instance is terminated, data on the instance is lost and any on-going tasks are interrupted. This is normal behavior but sometimes there are use cases when you might need to run some commands, wait for a task to complete, or execute some operations (for example, backing up logs) before the instance is terminated. So Auto Scaling introduced lifecycle hooks, which give you more control over timing after an instance is marked for termination.
In this post, I explore how you can leverage Auto Scaling lifecycle hooks, AWS Lambda, and Amazon EC2 Run Command to back up your data automatically before the instance is terminated. The solution illustrated allows you to back up your data to an S3 bucket; however, with minimal changes, it is possible to adapt this design to carry out any task that you prefer before the instance gets terminated, for example, waiting for a worker to complete a task before terminating the instance.

 
##Using Auto Scaling lifecycle hooks, Lambda, and EC2 Run Command

You can configure your Auto Scaling group to add a lifecycle hook when an instance is selected for termination. The lifecycle hook enables you to perform custom actions as Auto Scaling launches or terminates instances. In order to perform these actions automatically, you can leverage Lambda and EC2 Run Command to allow you to avoid the use of additional software and to rely completely on AWS resources.
For example, when an instance is marked for termination, Amazon CloudWatch Events can execute an action based on that. This action can be a Lambda function to execute a remote command on the machine and upload your logs to your S3 bucket.
EC2 Run Command enables you to run remote scripts through the agent running within the instance. You use this feature to back up the instance logs and to complete the lifecycle hook so that the instance is terminated.
The example provided in this post works precisely this way. Lambda gathers the instance ID from CloudWatch Events and then triggers a remote command to back up the instance logs.
 
##Set up the environment

Make sure that you have the latest version of the AWS CLI installed locally. For more information, see Getting Set Up with the AWS Command Line Interface.

##Step 1 – Create an SNS topic to receive the result of the backup

In this step, you create an Amazon SNS topic in the region in which to run your Auto Scaling group. This topic allows EC2 Run Command to send you the outcome of the backup. The output of the aws iam create-topic command includes the ARN. Save the ARN, as you need it for future steps.
```
aws sns create-topic --name backupoutcome
```
Now subscribe your email address as the endpoint for SNS to receive messages.
```
aws sns subscribe --topic-arn <enter-your-sns-arn-here> --protocol email --notification-endpoint <your_email>
```

##Step 2 – Create an IAM role for your instances and your Lambda function

In this step, you use the AWS console to create the AWS Identity and Access Management (IAM) role for your instances and Lambda to enable them to run the SSM agent, upload your files to your S3 bucket, and complete the lifecycle hook.
First, you need to create a custom policy to allow your instances and Lambda function to complete lifecycle hooks and publish to the SNS topic set up in Step 1.

1)    Log into the IAM console.
2)    Choose Policies, Create Policy
3)    For Create Your Own Policy, choose Select.
4)    For Policy Name, type “ASGBackupPolicy”.
5)    For Policy Document, paste the following policy which allows to complete a lifecycle hook:
```JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "autoscaling:CompleteLifecycleAction",
        "sns:Publish"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
```
Create the role for EC2.

1)    In the left navigation pane, choose Roles, Create New Role.
2)    For Role Name, type “instance-role” and choose Next Step.
3)    Choose Amazon EC2 and choose Next Step.
4)    Add the policies AmazonEC2RoleforSSM and ASGBackupPolicy.
5)    Choose Next Step, Create Role.

Create the role for the Lambda function.

1)    In the left navigation pane, choose Roles, Create New Role.
2)    For Role Name, type “lambda-role” and choose Next Step.
3)    Choose AWS Lambda and choose Next Step.
4)    Add the policies AmazonSSMFullAccess, ASGBackupPolicy, and AWSLambdaBasicExecutionRole.
5)    Choose Next Step, Create Role.

##Step 3 – Create an Auto Scaling group and configure the lifecycle hook

In this step, you create the Auto Scaling group and configure the lifecycle hook.

1)    Log into the EC2 console.
2)    Choose Launch Configurations, Create launch configuration.
3)    Select the latest Amazon Linux AMI and whatever instance type you prefer, and choose Next: Configuration details.
4)    For Name, type “ASGBackupLaunchConfiguration”.
5)    For IAM role, choose “instance-role” and expand Advanced Details.
6)    For User data, add the following lines to install and launch the SSM agent at instance boot:
```
    #!/bin/bash
    sudo yum install amazon-ssm-agent -y
    sudo /sbin/start amazon-ssm-agent
```
7)    Choose Skip to review, Create launch configuration, select your key pair, and then choose Create launch configuration.
8)    Choose Create an Auto Scaling group using this launch configuration.
9)    For Group name, type “ASGBackup”.
10)    Select your VPC and at least one subnet and then choose Next: Configuration scaling policies, Review, and Create Auto Scaling group.

Your Auto Scaling group is now created and you need to add the lifecycle hook named “ASGBackup” by using the AWS CLI:
```
aws autoscaling put-lifecycle-hook --lifecycle-hook-name ASGBackup --auto-scaling-group-name ASGBackup --lifecycle-transition autoscaling:EC2_INSTANCE_TERMINATING --heartbeat-timeout 3600
```

##Step 4 – Create an S3 bucket for files

Create an S3 bucket where your data will be saved, or use an existing one. To create a new one, you can use this AWS CLI command:
```
aws s3api create-bucket --bucket <your_bucket_name>
```

##Step 5 – Create the SSM document

The following JSON document archives the files in “BACKUPDIRECTORY” and then copies them to your S3 bucket “S3BUCKET”. Every time this command completes its execution, a SNS message is sent to the SNS topic specified by the “SNSTARGET” variable and completes the lifecycle hook.

In your JSON document, you need to make a few changes according to your environment:
```
Auto Scaling group name (line 12) 	“ASGNAME=’ASGBackup'”,
Lifecycle hook name (line 13) 	“LIFECYCLEHOOKNAME=’ASGBackup'”,
Directory to back up (line 14) 	“BACKUPDIRECTORY=’/var/log'”,
S3 bucket (line 15) 	“S3BUCKET='<your_bucket_name>'”,
SNS target (line 16) 	“SNSTARGET=’arn:aws:sns:’${REGION}’:<your_account_id>:<your_sns_ backupoutcome_topic>”
```
Here is the document:
```JSON
{
  "schemaVersion": "1.2",
  "description": "Backup logs to S3",
  "parameters": {},
  "runtimeConfig": {
    "aws:runShellScript": {
      "properties": [
        {
          "id": "0.aws:runShellScript",
          "runCommand": [
            "",
            "ASGNAME='ASGBackup'",
            "LIFECYCLEHOOKNAME='ASGBackup'",
            "BACKUPDIRECTORY='/var/log'",
            "S3BUCKET='<your_bucket_name>'",
            "SNSTARGET='arn:aws:sns:'${REGION}':<your_account_id>:<your_sns_ backupoutcome_topic>'",           
            "INSTANCEID=$(curl http://169.254.169.254/latest/meta-data/instance-id)",
            "REGION=$(curl http://169.254.169.254/latest/meta-data/placement/availability-zone)",
            "REGION=${REGION::-1}",
            "HOOKRESULT='CONTINUE'",
            "MESSAGE=''",
            "",
            "tar -cf /tmp/${INSTANCEID}.tar $BACKUPDIRECTORY &> /tmp/backup",
            "if [ $? -ne 0 ]",
            "then",
            "   MESSAGE=$(cat /tmp/backup)",
            "else",
            "   aws s3 cp /tmp/${INSTANCEID}.tar s3://${S3BUCKET}/${INSTANCEID}/ &> /tmp/backup",
            "       MESSAGE=$(cat /tmp/backup)",
            "fi",
            "",
            "aws sns publish --subject 'ASG Backup' --message \"$MESSAGE\"  --target-arn ${SNSTARGET} --region ${REGION}",
            "aws autoscaling complete-lifecycle-action --lifecycle-hook-name ${LIFECYCLEHOOKNAME} --auto-scaling-group-name ${ASGNAME} --lifecycle-action-result ${HOOKRESULT} --instance-id ${INSTANCEID}  --region ${REGION}"
          ]
        }
      ]
    }
  }
}
```
1)    Log into the EC2 console.
2)    Choose Command History, Documents, Create document.
3)    For Document name, enter “ASGLogBackup”.
4)    For Content, add the above JSON, modified for your environment.
5)    Choose Create document.

##Step 6 – Create the Lambda function

The Lambda function uses modules included in the Python 2.7 Standard Library and the AWS SDK for Python module (boto3), which is preinstalled as part of Lambda. The function code performs the following:

- Checks to see whether the SSM document exists. This document is the script that your instance runs.
- Sends the command to the instance that is being terminated. It checks for the status of EC2 Run Command and if it fails, the Lambda function completes the lifecycle hook.

1)    Log in to the Lambda console.
2)    Choose Create Lambda function.
3)    For Select blueprint, choose Skip, Next.
4)    For Name, type “lambda_backup” and for Runtime, choose Python 2.7.
5)    For Lambda function code, paste the Lambda function from the [link] GitHub repository.
6)    Choose Choose an existing role.
7)    For Role, choose lambda-role (previously created).
8)    In Advanced settings, configure Timeout for 5 minutes.
9)    Choose Next, Create function.

Your Lambda function is now created.

##Step 7 – Configure CloudWatch Events to trigger the Lambda function

Create an event rule to trigger the Lambda function.

1)    Log in to the CloudWatch console.
2)    Choose Events, Create rule.
3)    For Select event source, choose Auto Scaling.
4)    For Specific instance event(s), choose EC2 Instance-terminate Lifecycle Action and for Specific group name(s), choose ASGBackup.
5)    For Targets, choose Lambda function and for Function, select the Lambda function that you previously created, “lambda_backup”.
6)    Choose Configure details.
7)    In Rule definition, type a name and choose Create rule.

Your event rule is now created; whenever your Auto Scaling group “ASGBackup” starts terminating an instance, your Lambda function will be triggered.

##Step 8 – Test the environment

From the Auto Scaling console, you can change the desired capacity and the minimum for your Auto Scaling group to 0 so that the instance running starts being terminated. After the termination starts, you can see from Instances tab that the instance lifecycle status changed to Termination:Wait. While the instance is in this state, the Lambda function and the command are executed.

You can review your CloudWatch logs to see the Lambda output. In the CloudWatch console, choose Logs and /aws/lambda/lambda_backup to see the execution output.

You can go to your S3 bucket and check that the files were uploaded. You can also check Command History in the EC2 console to see if the command was executed correctly.
Conclusion

Now that you’ve seen an example of how you can combine various AWS services to automate the backup of your files by relying only on AWS services, I hope you are inspired to create your own solutions.

Auto Scaling lifecycle hooks, Lambda, and EC2 Run Command are powerful tools because they allow you to respond to Auto Scaling events automatically, such as when an instance is terminated. However, you can also use the same idea for other solutions like exiting processes gracefully before an instance is terminated, deregistering your instance from service managers, and scaling stateful services by moving state to other running instances. There are an almost infinite number of use cases.
