# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from senlin.common import consts
from senlin.objects import base
from senlin.objects import fields

CONF = cfg.CONF
CONF.import_opt('default_action_timeout', 'senlin.common.config')


@base.SenlinObjectRegistry.register
class ClusterListRequestBody(base.SenlinObject):

    fields = {
        'name': fields.ListOfStringsField(nullable=True),
        'status': fields.ListOfEnumField(
            valid_values=list(consts.CLUSTER_STATUSES), nullable=True),
        'limit': fields.NonNegativeIntegerField(nullable=True),
        'marker': fields.UUIDField(nullable=True),
        'sort': fields.SortField(
            valid_keys=list(consts.CLUSTER_SORT_KEYS), nullable=True),
        'project_safe': fields.FlexibleBooleanField(default=True),
    }


@base.SenlinObjectRegistry.register
class ClusterCreateRequestBody(base.SenlinObject):

    fields = {
        'name': fields.NameField(),
        'profile_id': fields.StringField(),
        'min_size': fields.IntegerField(
            nullable=True, default=consts.CLUSTER_DEFAULT_MIN_SIZE),
        'max_size': fields.IntegerField(
            nullable=True, default=consts.CLUSTER_DEFAULT_MAX_SIZE),
        'desired_capacity': fields.IntegerField(
            nullable=True, default=consts.CLUSTER_DEFAULT_MIN_SIZE),
        'metadata': fields.JsonField(nullable=True, default={}),
        'timeout': fields.IntegerField(nullable=True,
                                       default=CONF.default_action_timeout),
    }


@base.SenlinObjectRegistry.register
class ClusterCreateRequest(base.SenlinObject):

    fields = {
        'cluster': fields.ObjectField('ClusterCreateRequestBody')
    }


@base.SenlinObjectRegistry.register
class ClusterGetRequest(base.SenlinObject):

    fields = {
        'identity': fields.StringField()
    }


@base.SenlinObjectRegistry.register
class ClusterUpdateRequest(base.SenlinObject):

    fields = {
        'identity': fields.StringField(),
        'name': fields.NameField(nullable=True),
        'profile_id': fields.StringField(nullable=True),
        'metadata': fields.JsonField(nullable=True),
        'timeout': fields.IntegerField(nullable=True),
    }
