#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Cluster endpoint for Senlin v1 ReST API.
"""

import jsonschema
import six
from webob import exc

from senlin.api.common import util
from senlin.api.common import wsgi
from senlin.common import consts
from senlin.common import exception as senlin_exc
from senlin.common.i18n import _
from senlin.common import utils
from senlin.objects import base as obj_base
from senlin.objects.requests import clusters as vorc


class ClusterController(wsgi.Controller):
    """WSGI controller for clusters resource in Senlin v1 API."""

    # Define request scope (must match what is in policy.json)
    REQUEST_SCOPE = 'clusters'

    SUPPORTED_ACTIONS = (
        ADD_NODES, DEL_NODES, SCALE_OUT, SCALE_IN, RESIZE,
        POLICY_ATTACH, POLICY_DETACH, POLICY_UPDATE,
        CHECK, RECOVER, REPLACE_NODES
    ) = (
        'add_nodes', 'del_nodes', 'scale_out', 'scale_in', 'resize',
        'policy_attach', 'policy_detach', 'policy_update',
        'check', 'recover', 'replace_nodes'
    )

    @util.policy_enforce
    def index(self, req):
        whitelist = {
            consts.CLUSTER_NAME: 'mixed',
            consts.CLUSTER_STATUS: 'mixed',
            consts.PARAM_LIMIT: 'single',
            consts.PARAM_MARKER: 'single',
            consts.PARAM_SORT: 'single',
            consts.PARAM_GLOBAL_PROJECT: 'single',
        }
        for key in req.params.keys():
            if key not in whitelist:
                raise exc.HTTPBadRequest(_("Invalid parameter '%s'") % key)

        params = util.get_allowed_params(req.params, whitelist)
        # Note: We have to do a boolean parsing here because 1) there is
        # a renaming, 2) the boolean is usually presented as a string.
        is_global = params.pop(consts.PARAM_GLOBAL_PROJECT, False)
        unsafe = utils.parse_bool_param(consts.PARAM_GLOBAL_PROJECT,
                                        is_global)
        params['project_safe'] = not unsafe
        norm_req = obj_base.SenlinObject.normalize_req(
            'ClusterListRequestBody', params, None)
        obj = None
        try:
            obj = vorc.ClusterListRequestBody.obj_from_primitive(norm_req)
            jsonschema.validate(norm_req, obj.to_json_schema())
        except ValueError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex))
        except jsonschema.exceptions.ValidationError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex.message))

        clusters = self.rpc_client.call2(req.context, 'cluster_list2', obj)
        return {'clusters': clusters}

    @util.policy_enforce
    def create(self, req, body):
        """Create a new cluster."""
        try:
            norm_req = obj_base.SenlinObject.normalize_req(
                'ClusterCreateRequest', body, 'cluster')
            obj = vorc.ClusterCreateRequest.obj_from_primitive(norm_req)
            jsonschema.validate(norm_req, obj.to_json_schema())
        except (ValueError) as ex:
            raise exc.HTTPBadRequest(six.text_type(ex))

        cluster = self.rpc_client.call2(req.context, 'cluster_create2',
                                        obj.cluster)
        action_id = cluster.pop('action')
        result = {
            'cluster': cluster,
            'location': '/actions/%s' % action_id,
        }
        return result

    @util.policy_enforce
    def get(self, req, cluster_id):
        """Gets detailed information for a cluster."""
        norm_req = obj_base.SenlinObject.normalize_req(
            'ClusterGetRequest', {'identity': cluster_id}, None)
        obj = None
        try:
            obj = vorc.ClusterGetRequest.obj_from_primitive(norm_req)
            jsonschema.validate(norm_req, obj.to_json_schema())
        except ValueError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex))
        except jsonschema.exceptions.ValidationError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex.message))

        cluster = self.rpc_client.call2(req.context, 'cluster_get2', obj)

        return {'cluster': cluster}

    @util.policy_enforce
    def update(self, req, cluster_id, body):
        """Update an existing cluster with new parameters."""
        data = body.get('cluster')
        if data is None:
            raise exc.HTTPBadRequest(_("Malformed request data, missing "
                                       "'cluster' key in request body."))
        params = body['cluster']
        params['identity'] = cluster_id
        norm_req = obj_base.SenlinObject.normalize_req(
            'ClusterUpdateRequest', params, None)
        try:
            obj = vorc.ClusterUpdateRequest.obj_from_primitive(norm_req)
            jsonschema.validate(norm_req, obj.to_json_schema())
        except ValueError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex))
        except jsonschema.exceptions.ValidationError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex.message))

        cluster = self.rpc_client.call2(req.context, 'cluster_update2', obj)

        action_id = cluster.pop('action')
        result = {
            'cluster': cluster,
            'location': '/actions/%s' % action_id,
        }
        return result

    def _do_resize(self, req, cluster_id, this_action, body):
        data = body.get(this_action)
        adj_type = data.get(consts.ADJUSTMENT_TYPE)
        number = data.get(consts.ADJUSTMENT_NUMBER)
        min_size = data.get(consts.ADJUSTMENT_MIN_SIZE)
        max_size = data.get(consts.ADJUSTMENT_MAX_SIZE)
        min_step = data.get(consts.ADJUSTMENT_MIN_STEP)
        strict = data.get(consts.ADJUSTMENT_STRICT)
        if adj_type is not None:
            if adj_type not in consts.ADJUSTMENT_TYPES:
                raise senlin_exc.InvalidParameter(name='adjustment_type',
                                                  value=adj_type)
            if number is None:
                msg = _("Missing number value for resize operation.")
                raise exc.HTTPBadRequest(msg)

        if number is not None:
            if adj_type is None:
                msg = _("Missing adjustment_type value for resize "
                        "operation.")
                raise exc.HTTPBadRequest(msg)
            number = utils.parse_int_param(consts.ADJUSTMENT_NUMBER, number,
                                           allow_negative=True)

        if min_size is not None:
            min_size = utils.parse_int_param(consts.ADJUSTMENT_MIN_SIZE,
                                             min_size)
        if max_size is not None:
            max_size = utils.parse_int_param(consts.ADJUSTMENT_MAX_SIZE,
                                             max_size, allow_negative=True)
        if (min_size is not None and max_size is not None and
                max_size > 0 and min_size > max_size):
            msg = _("The specified min_size (%(n)s) is greater than the "
                    "specified max_size (%(m)s).") % {'m': max_size,
                                                      'n': min_size}
            raise exc.HTTPBadRequest(msg)

        if min_step is not None:
            min_step = utils.parse_int_param(consts.ADJUSTMENT_MIN_STEP,
                                             min_step)
        if strict is not None:
            strict = utils.parse_bool_param(consts.ADJUSTMENT_STRICT, strict)
        else:
            strict = True

        result = self.rpc_client.cluster_resize(req.context, cluster_id,
                                                adj_type, number, min_size,
                                                max_size, min_step, strict)
        location = {'location': '/actions/%s' % result['action']}
        result.update(location)
        return result

    def _sanitize_policy(self, data):
        """Validate dict body of policy attach or update.

        :param dict data: A dictionary containing the properties of the policy
                          to be attached/updated including the policy ID.
        :returns: A sanitized dict containing the policy properties.
        :raises: :class:`~webob.exception.HTTPBadRequest` if the policy dict
                 contains invalid property values.
        """
        if not isinstance(data, dict):
            msg = _("The data provided is not a map.")
            raise exc.HTTPBadRequest(msg)

        if consts.CP_POLICY_ID not in data:
            msg = _("The 'policy_id' field is missing in the request.")
            raise exc.HTTPBadRequest(msg)

        if consts.CP_ENABLED in data:
            enabled = data.get(consts.CP_ENABLED)
            try:
                enabled = utils.parse_bool_param(consts.CP_ENABLED, enabled)
            except senlin_exc.InvalidParameter as ex:
                raise exc.HTTPBadRequest(six.text_type(ex))
            data[consts.CP_ENABLED] = enabled

        return data

    @wsgi.Controller.api_version('1.3')
    def _replace_nodes(self, req, cluster_id, this_action, body):
        params = body.get(this_action).get('nodes')
        if not params or not isinstance(params, dict):
            msg = _("The data provided is not a map.")
            raise exc.HTTPBadRequest(msg)

        new_nodes = params.values()
        if len(new_nodes) != len(list(set(new_nodes))):
            msg = _("The data provided contains duplicated nodes.")
            raise exc.HTTPBadRequest(msg)

        for (old_node, new_node) in params.items():
            if not old_node:
                msg = _("The original node id could not be empty.")
                raise exc.HTTPBadRequest(msg)
            if not new_node:
                msg = _("The replacement node id could not be empty.")
                raise exc.HTTPBadRequest(msg)

        res = self.rpc_client.cluster_replace_nodes(req.context,
                                                    cluster_id,
                                                    nodes=params)
        location = {'location': '/actions/%s' % res['action']}
        res.update(location)
        return res

    def _add_nodes(self, ctx, cid, nodes):
        params = {'identity': cid, 'nodes': nodes}
        norm_req = obj_base.SenlinObject.normalize_req(
            'ClusterAddNodesRequest', params, None)
        obj = None
        try:
            obj = vorc.ClusterAddNodesRequest.obj_from_primitive(norm_req)
            jsonschema.validate(norm_req, obj.to_json_schema())
        except ValueError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex))
        except jsonschema.exceptions.ValidationError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex.message))

        return self.rpc_client.call2(ctx, 'cluster_add_nodes2', obj)

    def _del_nodes(self, ctx, cid, nodes):
        params = {'identity': cid, 'nodes': nodes}
        norm_req = obj_base.SenlinObject.normalize_req(
            'ClusterDelNodesRequest', params, None)
        obj = None
        try:
            obj = vorc.ClusterDelNodesRequest.obj_from_primitive(norm_req)
            jsonschema.validate(norm_req, obj.to_json_schema())
        except ValueError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex))
        except jsonschema.exceptions.ValidationError as ex:
            raise exc.HTTPBadRequest(six.text_type(ex.message))

        return self.rpc_client.call2(ctx, 'cluster_del_nodes2', obj)

    @util.policy_enforce
    def action(self, req, cluster_id, body=None):
        """Perform specified action on a cluster."""
        body = body or {}
        if len(body) < 1:
            raise exc.HTTPBadRequest(_('No action specified'))

        if len(body) > 1:
            raise exc.HTTPBadRequest(_('Multiple actions specified'))

        this_action = list(body.keys())[0]
        if this_action not in self.SUPPORTED_ACTIONS:
            msg = _("Unrecognized action '%s' specified") % this_action
            raise exc.HTTPBadRequest(msg)

        if this_action == self.ADD_NODES:
            nodes = body.get(this_action).get('nodes', [])
            res = self._add_nodes(req.context, cluster_id, nodes)
        elif this_action == self.DEL_NODES:
            nodes = body.get(this_action).get('nodes', [])
            res = self._del_nodes(req.context, cluster_id, nodes)
        elif this_action == self.RESIZE:
            return self._do_resize(req, cluster_id, this_action, body)
        elif this_action == self.SCALE_OUT:
            count = body.get(this_action).get('count')
            res = self.rpc_client.cluster_scale_out(req.context, cluster_id,
                                                    count)
        elif this_action == self.SCALE_IN:
            count = body.get(this_action).get('count')
            res = self.rpc_client.cluster_scale_in(req.context, cluster_id,
                                                   count)
        elif this_action == self.POLICY_ATTACH:
            raw_data = body.get(this_action)
            data = self._sanitize_policy(raw_data)
            res = self.rpc_client.cluster_policy_attach(req.context,
                                                        cluster_id,
                                                        **data)
        elif this_action == self.POLICY_DETACH:
            data = body.get(this_action)
            policy_id = data.get('policy_id', None)
            if not policy_id:
                raise exc.HTTPBadRequest(_('No policy specified for detach.'))
            res = self.rpc_client.cluster_policy_detach(req.context,
                                                        cluster_id, policy_id)
        elif this_action == self.POLICY_UPDATE:
            # this_action == self.POLICY_UPDATE:
            # Note the POLICY_UPDATE action includes policy-enable/disable
            raw_data = body.get(this_action)
            data = self._sanitize_policy(raw_data)
            res = self.rpc_client.cluster_policy_update(req.context,
                                                        cluster_id, **data)
        elif this_action == self.CHECK:
            params = body.get(this_action)
            if not isinstance(params, dict):
                msg = _("The params provided is not a map.")
                raise exc.HTTPBadRequest(msg)
            res = self.rpc_client.cluster_check(req.context, cluster_id,
                                                params=params)
        elif this_action == self.REPLACE_NODES:
            return self._replace_nodes(req, cluster_id, this_action, body)
        else:
            # this_action == self.RECOVER:
            params = body.get(this_action)
            if not isinstance(params, dict):
                msg = _("The params provided is not a map.")
                raise exc.HTTPBadRequest(msg)
            res = self.rpc_client.cluster_recover(req.context, cluster_id,
                                                  params=params)

        location = {'location': '/actions/%s' % res['action']}
        res.update(location)
        return res

    @wsgi.Controller.api_version('1.2')
    @util.policy_enforce
    def collect(self, req, cluster_id, path):
        """Aggregate attribute values across a cluster."""
        stripped_path = path.strip()
        if stripped_path == '':
            raise exc.HTTPBadRequest(_("Required path attribute is missing."))

        return self.rpc_client.cluster_collect(req.context, cluster_id,
                                               stripped_path)

    @util.policy_enforce
    def delete(self, req, cluster_id):
        res = self.rpc_client.cluster_delete(req.context, cluster_id,
                                             cast=False)
        action_id = res.pop('action')
        result = {'location': '/actions/%s' % action_id}
        return result
