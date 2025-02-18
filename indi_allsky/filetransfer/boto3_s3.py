from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import TransferFailure

from pathlib import Path
from datetime import datetime
from datetime import timedelta
import socket
import time
from botocore.client import Config
import boto3
import boto3.exceptions
import logging

logger = logging.getLogger('indi_allsky')


class boto3_s3(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(boto3_s3, self).__init__(*args, **kwargs)

        self._port = 443


    def connect(self, *args, **kwargs):
        super(boto3_s3, self).connect(*args, **kwargs)

        access_key = kwargs['access_key']
        secret_key = kwargs['secret_key']
        region = kwargs['region']
        #host = kwargs['hostname']  # endpoint_url
        tls = kwargs['tls']
        cert_bypass = kwargs['cert_bypass']


        if cert_bypass:
            verify = False
        else:
            verify = True


        boto_config = Config(
            connect_timeout=self._timeout,
            retries={'max_attempts': 0},
        )

        self.client = boto3.client(
            's3',
            region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            #endpoint_url='http://foobar',
            use_ssl=tls,
            verify=verify,
            config=boto_config,
        )


    def close(self):
        super(boto3_s3, self).close()


    def put(self, *args, **kwargs):
        super(boto3_s3, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        bucket = kwargs['bucket']
        key = kwargs['key']
        storage_class = kwargs['storage_class']
        expire_days = kwargs['expire_days']
        acl = kwargs['acl']

        local_file_p = Path(local_file)


        extra_args = dict()

        if acl:
            extra_args['ACL'] = acl  # all assets are normally publicly readable


        if storage_class:
            extra_args['StorageClass'] = storage_class


        if expire_days:
            now = datetime.now()
            extra_args['Expires'] = now + timedelta(days=expire_days)


        start = time.time()

        try:
            self.client.upload_file(
                str(local_file_p),
                bucket,
                str(key),
                ExtraArgs=extra_args,
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except boto3.exceptions.S3UploadFailedError as e:
            raise TransferFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


