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

import eventlet
import six

from oslo_log import log as logging

from senlin.common import context
from senlin.common.i18n import _
from senlin.common.i18n import _LE
from senlin.drivers import base
from senlin.drivers.openstack import neutron_v2 as neutronclient

LOG = logging.getLogger(__name__)


class LoadBalancerDriver(base.DriverBase):
    """Load-balancing driver based on Neutron LBaaS service."""

    def __init__(self, ctx):
        super(LoadBalancerDriver, self).__init__(ctx)
        self.ctx = ctx
        self._nc = None

    def nc(self):
        if self._nc:
            return self._nc

        self._nc = neutronclient.NeutronClient(self.ctx)
        return self._nc

    def _wait_for_lb_ready(self, lb_id, timeout=60, ignore_not_found=False):
        """Keep waiting until loadbalancer is ready

        This method will keep waiting until loadbalancer resource specified
        by lb_id becomes ready, i.e. its provisioning_status is ACTIVE and
        its operating_status is ONLINE.

        :param lb_id: ID of the load-balancer to check.
        :param timeout: timeout in seconds.
        :param ignore_not_found: if set to True, nonexistent loadbalancer
            resource is also an acceptable result.
        """
        waited = 0
        while waited < timeout:
            lb = self.nc().loadbalancer_get(lb_id)
            if lb is None:
                lb_ready = ignore_not_found
            else:
                lb_ready = ((lb.provisioning_status == 'ACTIVE') and
                            (lb.operating_status == 'ONLINE'))

            if lb_ready is True:
                return True

            LOG.debug(_('Waiting for loadbalancer %(lb)s to become ready'),
                      {'lb': lb_id})

            eventlet.sleep(2)
            waited += 2

        return False

    def lb_create(self, vip, pool):
        """Create a LBaaS instance

        :param vip: A dict containing the properties for the VIP;
        :param pool: A dict describing the pool of load-balancer members.
        """
        def _cleanup(msg, **kwargs):
            LOG.error(msg)
            self.lb_delete(**kwargs)
            return

        result = {}
        # Create loadblancer
        lb = self.nc().loadbalancer_create(vip['subnet'],
                                           vip.get('address', None),
                                           vip['admin_state_up'])
        result['loadbalancer'] = lb.id

        res = self._wait_for_lb_ready(lb.id)
        if res is False:
            msg = _LE('Failed in creating load balancer (%s).') % lb.id
            _cleanup(msg, **result)
            return False, msg

        # Create listener
        listener = self.nc().listener_create(lb.id, vip['protocol'],
                                             vip['protocol_port'],
                                             vip.get('connection_limit', None),
                                             vip['admin_state_up'])
        result['listener'] = listener.id
        res = self._wait_for_lb_ready(lb.id)
        if res is False:
            msg = _LE('Failed in creating listener (%s).') % listener.id
            _cleanup(msg, **result)
            return res, msg

        # Create pool
        pool = self.nc().pool_create(pool['lb_method'], listener.id,
                                     pool['protocol'], pool['admin_state_up'])
        result['pool'] = pool.id
        res = self._wait_for_lb_ready(lb.id)
        if res is False:
            msg = _LE('Failed in creating pool (%s).') % pool.id
            _cleanup(msg, **result)
            return res, msg

        return True, result

    def lb_delete(self, **kwargs):
        """Delete a Neutron lbaas instance

        The following Neutron lbaas resources will be deleted in order:
        1)healthmonitor; 2)pool; 3)listener; 4)loadbalancer.
        """
        lb_id = kwargs.pop('loadbalancer')

        healthmonitor_id = kwargs.pop('healthmonitor', None)
        if healthmonitor_id:
            self.nc().healthmonitor_delete(healthmonitor_id)
            self._wait_for_lb_ready(lb_id)

        pool_id = kwargs.pop('pool', None)
        if pool_id:
            self.nc().pool_delete(pool_id)
            self._wait_for_lb_ready(lb_id)

        listener_id = kwargs.pop('listener', None)
        if listener_id:
            self.nc().listener_delete(listener_id)
            self._wait_for_lb_ready(lb_id)

        self.nc().loadbalancer_delete(lb_id)
        self._wait_for_lb_ready(lb_id, True)

        return True, _('LB deletion succeeded')

    def member_add(self, node, lb_id, pool_id, port, subnet):
        """Add a member to Neutron lbaas pool.

        :param node: A node object to be added to the specified pool.
        :param lb_id: The ID of the loadbalancer.
        :param pool_id: The ID of the pool for receiving the node.
        :param port: The port for the new LB member to be created.
        :param subnet: The subnet to be used by the new LB member.
        :returns: The ID of the new LB member or None if errors occurred.
        """
        addresses = self._get_node_address(node, version=4)
        if not addresses:
            LOG.error(_LE('Node (%(n)s) does not have valid IPv4 address.'),
                      {'n': node.id})
            return None

        subnet_obj = self.nc().subnet_get(subnet)
        net_id = subnet_obj['network_id']
        net = self.nc().network_get(net_id)
        net_name = net['name']

        if net_name not in addresses:
            LOG.error(_LE('Node is not in subnet %(subnet)s'),
                      {'subnet': subnet})
            return None

        address = addresses[net_name]
        member = self.nc().pool_member_create(pool_id, address, port, subnet)
        self._wait_for_lb_ready(lb_id)

        return member.id

    def member_remove(self, lb_id, pool_id, member_id):
        """Delete a member from Neutron lbaas pool.

        :param lb_id: The ID of the loadbalancer the operation is targeted at;
        :param pool_id: The ID of the pool from which the member is deleted;
        :param member_id: The ID of the LB member.
        :returns: True if the operation succeeded or False if errors occurred.
        """
        try:
            self.nc().pool_member_delete(pool_id, member_id)
            self._wait_for_lb_ready(lb_id)
        except Exception as ex:
            LOG.error(_LE('Failed in removing member %(m)s from pool %(p)s: '
                          '%(ex)s'),
                      {'m': member_id, 'p': pool_id, 'ex': six.text_type(ex)})
            return False

        return True

    def _get_node_address(self, node, version=4):
        """Get IP address of node with specific version"""

        node_detail = node.get_details(context.get_current())
        node_addresses = node_detail.get('addresses')

        address = {}
        for network in node_addresses:
            for addr in node_addresses[network]:
                if addr['version'] == version:
                    address[network] = addr['addr']

        return address
