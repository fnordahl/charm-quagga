# Copyright 2018 Frode Nordahl
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import charmhelpers.core as ch_core
import charmhelpers.core.sysctl as ch_core_sysctl
import charmhelpers.core.templating as ch_core_templating
import charms.reactive as reactive
import charm.quagga as quagga


@reactive.when_not('quagga.started')
def start_quagga():
    ch_core_sysctl.create("{'net.ipv4.ip_forward': 1}",
                          '/etc/sysctl.d/42-charm-quagga.conf')
    ch_core_templating.render('daemons', '/etc/quagga/daemons', {},
                              owner='quagga', group='quagga', perms=0o640)
    ch_core_templating.render('zebra.conf', '/etc/quagga/zebra.conf', {},
                              owner='quagga', group='quagga', perms=0o640)
    ch_core_templating.render('bgpd.conf', '/etc/quagga/bgpd.conf', {},
                              owner='quagga', group='quagga', perms=0o640)
    ch_core.host.service('restart', 'quagga')

    # Get bgp interface to generate our AS Number
    bgpserver = reactive.relations.endpoint_from_name('bgpserver')

    # Perform basic BGP configuration
    asn = bgpserver.generate_asn()
    quagga.vtysh(
        ['conf t',
         'router bgp {}'.format(asn),
         'bgp router-id {}'.format(
             ch_core.hookenv.unit_get('private-address')
             ),
         'redistribute connected',
         'exit',
         'exit',
         'write',
         ]
        )

    ch_core.hookenv.status_set('active', 'Ready (AS Number {})'.format(asn))
    reactive.set_state('quagga.started')


@reactive.when_any('endpoint.bgpserver.joined', 'endpoint.bgpclient.joined')
def publish_bgp_info():
    for endpoint in (
            reactive.relations.endpoint_from_flag('endpoint.bgpserver.joined'),
            reactive.relations.endpoint_from_flag('endpoint.bgpclient.joined'),
            ):
        endpoint.publish_info()


@reactive.when_any('endpoint.bgpserver.changed', 'endpoint.bgpclient.changed')
def configure_quagga():
    for endpoint in (
            reactive.relations.endpoint_from_flag(
                'endpoint.bgpserver.changed'),
            reactive.relations.endpoint_from_flag(
                'endpoint.bgpclient.changed'),
            ):
        for entry in endpoint.get_received_info():
            ch_core.hookenv.log("DEBUG: received info: '{}'".format(entry))
            if len(entry['links']):
                # configure BGP neighbours on extra-bindings interfaces
                for link in entry['links']:
                    ch_core.hookenv.log(
                            'DEBUG: configure neighbour {} '
                            'remote-as {}'
                            ''.format(link['remote'], entry['asn']))
                    quagga.vtysh(
                        ['conf t',
                         'router bgp {}'.format(endpoint.generate_asn()),
                         'neighbor {} remote-as {}'.format(
                             link['remote'], entry['asn']),
                         'exit',
                         'exit',
                         'write',
                         ]
                        )
            else:
                # configure BGP neighbour on relation interface
                relation_addr = ch_core.hookenv.relation_get(
                        attribute='private-address',
                        unit=entry['remote_unit_name'],
                        rid=entry['relation_id'])
                ch_core.hookenv.log('DEBUG: configure neighbour {} '
                                    'remote-as {}'
                                    ''.format(relation_addr, entry['asn']))
                quagga.vtysh(
                    ['conf t',
                     'router bgp {}'.format(endpoint.generate_asn()),
                     'neighbor {} remote-as {}'.format(
                         relation_addr, entry['asn']),
                     'exit',
                     'exit',
                     'write',
                     ]
                    )
