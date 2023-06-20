from . import Storage
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from autonomous import log


class S3Storage(Storage):
    pass
    # def __init__(self):
    #     self.bucket = os.getenv("S3_BUCKET_NAME")
    #     self.path = os.getenv("APP_NAME", "app")
    #     self.client = boto3.client(
    #         "s3",
    #         config=Config(
    #             region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    #             signature_version="v4",
    #             retries={"max_attempts": 2, "mode": "standard"},
    #         ),
    #     )

    # def geturl(self, key, **kwargs):
    #     """Generate a presigned URL to share an S3 object
    #     :param key: string
    #     :param expiration: Time in seconds for the presigned URL to remain valid
    #     :return: Presigned URL as string. If error, returns None.
    #     """

    #     # Generate a presigned URL for the S3 object
    #     try:
    #         response = self.client.generate_presigned_url(
    #             "get_object",
    #             Params={"Bucket": self.bucket, "Key": key},
    #             ExpiresIn=kwargs.get("expiration", 3600),
    #         )
    #     except ClientError as e:
    #         log.error(e)
    #         return None

    #     # The response contains the presigned URL
    #     return response
