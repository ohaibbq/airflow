#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Default celery configuration."""
from __future__ import annotations

import logging
import ssl

import re2

from airflow.configuration import conf
from airflow.exceptions import AirflowConfigException, AirflowException


def _broker_supports_visibility_timeout(url):
    return url.startswith(("redis://", "rediss://", "sqs://", "sentinel://"))


log = logging.getLogger(__name__)

broker_url = conf.get("celery", "BROKER_URL")

broker_transport_options = conf.getsection("celery_broker_transport_options") or {}
if "visibility_timeout" not in broker_transport_options:
    if _broker_supports_visibility_timeout(broker_url):
        broker_transport_options["visibility_timeout"] = 21600

broker_transport_options_for_celery: dict = broker_transport_options.copy()
if "sentinel_kwargs" in broker_transport_options:
    try:
        sentinel_kwargs = broker_transport_options.get("sentinel_kwargs")
        if not isinstance(sentinel_kwargs, dict):
            raise ValueError
        broker_transport_options_for_celery["sentinel_kwargs"] = sentinel_kwargs
    except Exception:
        raise AirflowException("sentinel_kwargs should be written in the correct dictionary format.")

if conf.has_option("celery", "RESULT_BACKEND"):
    result_backend = conf.get_mandatory_value("celery", "RESULT_BACKEND")
else:
    log.debug("Value for celery result_backend not found. Using sql_alchemy_conn with db+ prefix.")
    result_backend = f'db+{conf.get("database", "SQL_ALCHEMY_CONN")}'

DEFAULT_CELERY_CONFIG = {
    "accept_content": ["json"],
    "event_serializer": "json",
    "worker_prefetch_multiplier": conf.getint("celery", "worker_prefetch_multiplier"),
    "task_acks_late": True,
    "task_default_queue": conf.get("operators", "DEFAULT_QUEUE"),
    "task_default_exchange": conf.get("operators", "DEFAULT_QUEUE"),
    "task_track_started": conf.getboolean("celery", "task_track_started"),
    "broker_url": broker_url,
    "broker_transport_options": broker_transport_options_for_celery,
    "result_backend": result_backend,
    "database_engine_options": conf.getjson(
        "celery", "result_backend_sqlalchemy_engine_options", fallback={}
    ),
    "worker_concurrency": conf.getint("celery", "WORKER_CONCURRENCY"),
    "worker_enable_remote_control": conf.getboolean("celery", "worker_enable_remote_control"),
}


def _get_celery_ssl_active() -> bool:
    try:
        return conf.getboolean("celery", "SSL_ACTIVE")
    except AirflowConfigException:
        log.warning("Celery Executor will run without SSL")
        return False


celery_ssl_active = _get_celery_ssl_active()

try:
    if celery_ssl_active:
        if broker_url and "amqp://" in broker_url:
            broker_use_ssl = {
                "keyfile": conf.get("celery", "SSL_KEY"),
                "certfile": conf.get("celery", "SSL_CERT"),
                "ca_certs": conf.get("celery", "SSL_CACERT"),
                "cert_reqs": ssl.CERT_REQUIRED,
            }
        elif broker_url and re2.search("rediss?://|sentinel://", broker_url):
            broker_use_ssl = {
                "ssl_keyfile": conf.get("celery", "SSL_KEY"),
                "ssl_certfile": conf.get("celery", "SSL_CERT"),
                "ssl_ca_certs": conf.get("celery", "SSL_CACERT"),
                "ssl_cert_reqs": ssl.CERT_REQUIRED,
            }
        else:
            raise AirflowException(
                "The broker you configured does not support SSL_ACTIVE to be True. "
                "Please use RabbitMQ or Redis if you would like to use SSL for broker."
            )

        DEFAULT_CELERY_CONFIG["broker_use_ssl"] = broker_use_ssl
except AirflowConfigException:
    raise AirflowException(
        "AirflowConfigException: SSL_ACTIVE is True, "
        "please ensure SSL_KEY, "
        "SSL_CERT and SSL_CACERT are set"
    )
except Exception as e:
    raise AirflowException(
        f"Exception: There was an unknown Celery SSL Error. Please ensure you want to use SSL and/or have "
        f"all necessary certs and key ({e})."
    )

if re2.search("rediss?://|amqp://|rpc://", result_backend):
    log.warning(
        "You have configured a result_backend of %s, it is highly recommended "
        "to use an alternative result_backend (i.e. a database).",
        result_backend,
    )
