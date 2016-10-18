# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import ConfigParser
import json, os, subprocess
from datetime import datetime, timedelta
from django.http import HttpResponse   # noqa

from horizon import views
import logging
from openstack_dashboard.api import ceilometer, nova


import threading, time

import keystoneclient.v2_0.client as ksclient
from heatclient import client as heat_client


LOG = logging.getLogger(__name__)

config = ConfigParser.RawConfigParser()
config.read(os.path.join(os.path.dirname(__file__), 'instances.cfg'))

# HOSTS
hosts_list = [e.strip() for e in config.get('DEFAULT', 'hosts_list').split(',')]
ifaces_list = [e.strip() for e in config.get('DEFAULT', 'ifaces_list').split(',')]
host_metrics_list = [e.strip() for e in config.get('Host_metrics', 'host_metrics_list').split(',')]
host_units_list = [e.strip() for e in config.get('Host_metrics', 'host_units_list').split(',')]
host_ranges_list = [e.strip() for e in config.get('Host_metrics', 'host_ranges_list').split(',')]
host_yellows_list = [e.strip() for e in config.get('Host_metrics', 'host_yellows_list').split(',')]
host_reds_list = [e.strip() for e in config.get('Host_metrics', 'host_reds_list').split(',')]

# VMS
vm_metrics_list = [e.strip() for e in config.get('Vm_metrics', 'vm_metrics_list').split(',')]
vm_units_list = [e.strip() for e in config.get('Vm_metrics', 'vm_units_list').split(',')]
vm_ranges_list = [e.strip() for e in config.get('Vm_metrics', 'vm_ranges_list').split(',')]
vm_yellows_list = [e.strip() for e in config.get('Vm_metrics', 'vm_yellows_list').split(',')]
vm_reds_list = [e.strip() for e in config.get('Vm_metrics', 'vm_reds_list').split(',')]

# VMS FOR THE DEMO
demo_vms_list = [e.strip() for e in config.get('Demo_vms', 'demo_vms_list').split(',')]


#Admin token and delta_t initialization
admin_token = ""
delta_t = 60

#Stack object
stacks_obj = []

#************DEMO FLAG*******************
flag_demo = True
#****************************************

#Static version (demo)
if(flag_demo):
    stacks_obj = [{'stack_id': u'<stack_id>', 'stack_name': u'<stack_name>', 'resources': [{'resource_name': u'<resource_name>', 'resource_id': u'<resource_id>'}], 'application_name': '<custom_application_name>'}, {...}]


#Standard version [data is retrieved using Openstack clients (Heat, Nova and Keystone)]
else:
    ass_vm_appname_threads = []

    ENV_HEAT_OS_API_VERSION = "1"
    ENV_OS_AUTH_URL = "http://keystone:35357/v2.0"
    ENV_OS_USERNAME = "admin"
    ENV_OS_TENANT_NAME = "admin"
    ENV_OS_PASSWORD = "<PASSWORD>"


    # Static heat parameters
    heat_service_id = "<heat_service_id>"
    fixed_heat_endpoint = "http://heat:8004/v1/%(tenant_id)s"
    heat_endpoint = "http://heat:8004/v1/<endpoint>"




class IndexView(views.APIView):
    template_name = 'admin/instancegaugescw/index.html'

    #Admin token section
    global admin_token
    os.system("curl -i \'http://keystone:5000/v2.0/tokens\' -X POST -H \"Content-Type: application/json\" -H \"Accept: application/json\"  -d \'{\"auth\": {\"tenantName\": \"admin\", \"passwordCredentials\": {\"username\": \"admin\", \"password\": \"<PASSWORD>\"}}}\' > /tmp/adm_token; sed \'1,8d\' /tmp/adm_token > /tmp/temp; cat /tmp/temp | jq \'.access.token.id\' > /tmp/adm_token")
    admin_token = subprocess.check_output("sed -e \'s/\"//g\' /tmp/adm_token", shell=True).rstrip()



# HOSTS GAUGES Management
# ------------------------------------------------------------------------------------------------------------------------
def UpdateHostGauges(request):

    global admin_token, delta_t

    hosts = []
    query_metrics = ""
    query = ""
    samples = []
    vms_sum_samples = []

    from_time = datetime.now()
    to_time = from_time - timedelta(seconds=delta_t)

    from_time = from_time.strftime("%Y-%m-%dT%H:%M:%S")
    to_time = to_time.strftime("%Y-%m-%dT%H:%M:%S")

    start = r'{\"<\":{\"timestamp\":\"'+from_time+r'\"}},'
    stop = r'{\">\":{\"timestamp\":\"'+to_time+r'\"}},'
    orderby = r'"orderby" : "[{\"timestamp\": \"DESC\"}, {\"counter_name\": \"ASC\"}]"'
    limit = r'"limit": 20'

    limit_multiplier = 2

    LOG.debug('HOSTS GAUGES')

    #Composing the query and retrieve data samples
    #----------------------------------------------------------------
    selected_cpt = request.GET.get('host', None)
    query_resources = r'{\"=\":{\"resource_id\":\"'+str(selected_cpt)+r'\"}}'

    for i in range(len(host_metrics_list)):
        if host_metrics_list[i] == "hardware.memory.used":
            metric = "mem_used"
            counter_name = r'{\"=\":{\"counter_name\":\"'+str(metric)+r'\"}}'

            vms_list = nova.hypervisor_search(request, selected_cpt)
            query_vms = ""
            #LOG.debug('VMS LIST: %s', vms_list[0].servers)

            #**************************************************************************************
            #Demo version
            if(flag_demo):
                count = 0
                for vm in vms_list[0].servers:
                    if vm.get("uuid") in demo_vms_list:
                        if query_vms == "":
                            query_vms = r'{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                        else:
                            query_vms += r',{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                        count += 1

            #Standard version
            else:
                count = 0
                for vm in vms_list[0].servers:
                    if query_vms == "":
                        query_vms = r'{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                    else:
                        query_vms += r',{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                    count += 1
            #**************************************************************************************


            if query_vms == "":
                LOG.debug('VMs query is empty!')
                vms_sum_samples.append({"resource_id": selected_cpt, "counter_name": metric, "counter_volume": 0, "counter_unit": host_units_list[i], "range": host_ranges_list[i], "metric_position": i})
                continue

            limit_vms = r'"limit": '+str(limit_multiplier*len(vms_list[0].servers))
            #LOG.debug('LIMIT: %s', limit)

            if count == 1:
                query_vms = r'{"filter": "{\"and\":['+str(counter_name)+r','+start+stop+str(query_vms)+r']}",'+str(orderby)+r','+str(limit_vms)+'}'
            else:
                query_vms = r'{"filter": "{\"and\":['+str(counter_name)+r','+start+stop+r'{\"or\":['+str(query_vms)+r']}]}",'+str(orderby)+r','+str(limit_vms)+'}'
 
            host_file = open("/tmp/hosts_query.txt", "w")
            host_file.write(query_vms)
            host_file.close()
            output = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/hosts_query.txt http://ceilometer:8777/v2/query/samples", shell=True)

            result = json.loads(output)
            #LOG.debug('QUERY: %s', query_vms)
            #LOG.debug('RESULT: %s', result)
            if len(result) ==0:
                vms_sum_samples.append({"resource_id": selected_cpt, "counter_name": metric, "counter_volume": 0, "counter_unit": host_units_list[i], "range": host_ranges_list[i], "metric_position": i})
                continue

            temp_vms = []
            volume_sum = 0
            for res in result:
                #LOG.debug('RES: %s', res["metadata"]["display_name"])
                if len(temp_vms) == 0:
                    #LOG.debug('RES: %s', res)
                    temp_vms.append({"vm_id": res["resource_id"], "volume": res["volume"]})
                    volume_sum += res["volume"]
                else:
                    flag_insert_vms = True
                    for j in range(len(temp_vms)):
                        if temp_vms[j]["vm_id"] == res["resource_id"]:
                            flag_insert_vms = False
                            break
                    if flag_insert_vms:
                        temp_vms.append({"vm_id": res["resource_id"], "volume": res["volume"]})
                        volume_sum += res["volume"]

            if volume_sum != 0:
                volume_sum = round((volume_sum / 1024),2)

            vms_sum_samples.append({"resource_id": selected_cpt, "counter_name": metric, "counter_volume": volume_sum, "counter_unit": host_units_list[i], "range": host_ranges_list[i], "metric_position": i})


        # For the hardware.network.outgoing.bytes.rate metric
        elif host_metrics_list[i] == "hardware.network.outgoing.bytes.rate":
            for iface in ifaces_list:
                if iface.startswith(selected_cpt):
                    #LOG.debug('IFACE: %s', iface)
                    iface_name = r'{\"=\":{\"counter_name\":\"'+str(host_metrics_list[i])+r'\"}}'
                    outgoingrate_resource = r'{\"=\":{\"resource_id\":\"'+str(iface)+r'\"}}'
                    limit_rate = r'"limit": 5'

                    query = r'{"filter": "{\"and\":['+str(iface_name)+r','+start+stop+outgoingrate_resource+r']}",'+str(orderby)+r','+str(limit_rate)+'}'
                    host_file = open("/tmp/hosts_query.txt", "w")
                    host_file.write(query)
                    host_file.close()
                    result = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/hosts_query.txt http://ceilometer:8777/v2/query/samples", shell=True)
                    #LOG.debug('QUERY: %s', query)
                    #LOG.debug('IFACE SAMPLES: %s', json.loads(result))
                    samples.append(json.loads(result))
                    break

        else:
            if query_metrics == "":
                query_metrics = r'{\"=\":{\"counter_name\":\"'+str(host_metrics_list[i])+r'\"}}'
            else:
                query_metrics += r',{\"=\":{\"counter_name\":\"'+str(host_metrics_list[i])+r'\"}}'

    query = r'{"filter": "{\"and\":['+str(query_resources)+r','+start+stop+r'{\"or\":['+str(query_metrics)+r']}]}",'+str(orderby)+r','+str(limit)+'}'
    host_file = open("/tmp/hosts_query.txt", "w")
    host_file.write(query)
    host_file.close()
    result = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/hosts_query.txt http://ceilometer:8777/v2/query/samples", shell=True)#.rstrip()

    samples.append(json.loads(result))
    LOG.debug('SAMPLES: %s', samples)

    #Composing the vector to return into the HttpResponse
    #----------------------------------------------------------------
    for i in range(len(samples)):
        for j in range(len(samples[i])):
            json_sample = samples[i][j]

            metric_display_name = change_label(json_sample["meter"])
            metric_pos = host_metrics_list.index(json_sample["meter"])
            metric_range = host_ranges_list[metric_pos]
            metric_unit = host_units_list[metric_pos]

            #Used ONLY to manage the hardware.network.outgoing.bytes.rate samples which have "nova-cpt1.eth3.11" like string as resource_id
            if json_sample["resource_id"].startswith(selected_cpt):
                json_sample["resource_id"] = selected_cpt


            if len(hosts) == 0:
                hosts.append({"resource_id": json_sample["resource_id"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range}]})

            else:
                for k in range(len(hosts)):
                    if hosts[k]["resource_id"] == json_sample["resource_id"]:

                        flag_insert = True
                        for l in range(len(hosts[k]["metrics"])):
                            if hosts[k]["metrics"][l]["counter_name"] == metric_display_name:
                                flag_insert = False
                                break

                        if flag_insert:
                            hosts[k]["metrics"].append({"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume": change_scale(metric_display_name, json_sample["volume"]), "counter_unit": metric_unit, "range": metric_range})

    #LOG.debug('PRE HOST: %s', hosts)


    for host in hosts:
        for vms_sum in vms_sum_samples:
            if host["resource_id"] == vms_sum["resource_id"]:
                host["metrics"].append({"counter_name": vms_sum["counter_name"], "counter_volume": vms_sum["counter_volume"], "metric_position": vms_sum["metric_position"], "counter_unit": vms_sum["counter_unit"], "range": vms_sum["range"]})
                break

        if len(host["metrics"]) != len(host_metrics_list):
            for i in range(len(host_metrics_list)):
                flag_insert = True
                for j in range(len(host["metrics"])):
                    if host["metrics"][j]["counter_name"] == change_label(host_metrics_list[i]):
                        flag_insert = False
                        break

                if flag_insert:
                    LOG.debug('HOSTS ----> Inserted missing metric: %s', change_label(host_metrics_list[i]))
                    host["metrics"].append({"counter_name": change_label(host_metrics_list[i]), "counter_volume": 0, "metric_position": i, "counter_unit": host_units_list[i], "range": host_ranges_list[i]})


    #LOG.debug('\n\nPOST HOSTS: %s', hosts)

    #Order by metric name position
    for host in hosts:
        sorted_list = sorted(host["metrics"], key=lambda k: int(k["metric_position"]), reverse = False)
        #LOG.debug('SORTED: %s', sorted_list)
        host["metrics"] = sorted_list

    LOG.debug('Updated nova-cpt gauges values: %s', hosts)
    #----------------------------------------------------------------
    return HttpResponse(json.dumps(hosts),content_type="application/json")
# ------------------------------------------------------------------------------------------------------------------------



def change_label(metric_name):
    new_label = ""

    if metric_name.startswith("hardware."):
        metric_name = metric_name.split("hardware.")

        if metric_name[1] == "memory.used":
            new_label = "mem_used"

        elif metric_name[1] == "network.outgoing.bytes.rate":
            new_label = "outgoing.bytes"

        else:
            new_label = metric_name[1]

    elif metric_name.startswith("host."):
        metric_name = metric_name.split("host.")
        new_label = metric_name[1]

    else:
        return metric_name

    return new_label


def change_scale(metric_name, metric_volume):

    if metric_name == "outgoing.bytes":
        #B/s -> Mb/s  => [  x / (1000^2) ] *8
        return round((8* metric_volume / 1000 / 1000),3) 

    else:
        return metric_volume


def get_appname_and_resourcename(resource_id):

    global stacks_obj

    appname_and_resourcename = []
    for stack in stacks_obj:
        flag = False
        for resource in stack["resources"]:
            if resource["resource_id"] == resource_id:
                appname_and_resourcename.append({"application_name": stack["application_name"], "resource_name": resource["resource_name"]})
                flag = True
                break
        if flag:
            break

    return appname_and_resourcename




# VM GAUGES Management
# ------------------------------------------------------------------------------------------------------------------------
def UpdateVmsGauges(request):
    global admin_token, delta_t

    vms_per_host = []
    query = ""
    samples = []

    from_time = datetime.now()
    to_time = from_time - timedelta(seconds=delta_t)

    from_time = from_time.strftime("%Y-%m-%dT%H:%M:%S")
    to_time = to_time.strftime("%Y-%m-%dT%H:%M:%S")

    start = r'{\"<\":{\"timestamp\":\"'+from_time+r'\"}},'
    stop = r'{\">\":{\"timestamp\":\"'+to_time+r'\"}},'
    orderby = r'"orderby" : "[{\"timestamp\": \"DESC\"}, {\"counter_name\": \"ASC\"}]"'

    limit_multiplier = 4

    selected_cpt = request.GET.get('host', False)
    vms_list = nova.hypervisor_search(request, selected_cpt)

    #Composing the query and retrieve data samples
    #----------------------------------------------------------------
    for vm_metric in vm_metrics_list:
        counter_name = r'{\"=\":{\"counter_name\":\"'+str(vm_metric)+r'\"}}'

        query_vms = ""
        #LOG.debug('VMS LIST: %s', vms_list[0].servers)
        count = 0
        for vm in vms_list[0].servers:

            #**************************************************************************************
            if(flag_demo):
                #Demo version
                if vm.get("uuid") in demo_vms_list:
                    if query_vms == "":
                        query_vms = r'{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                    else:
                        query_vms += r',{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                    count += 1

            else:
                #Standard version
                if query_vms == "":
                    query_vms = r'{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                else:
                    query_vms += r',{\"=\":{\"resource_id\":\"'+str(vm.get("uuid"))+r'\"}}'
                count += 1
            #**************************************************************************************



        #LOG.debug('QUERY: %s', query_vms)
        if query_vms == "":
            continue

        limit = r'"limit": '+str(limit_multiplier*len(vms_list[0].servers))

        if count == 1:
            query = r'{"filter": "{\"and\":['+str(counter_name)+r','+start+stop+str(query_vms)+r']}",'+str(orderby)+r','+str(limit)+'}'
        else:
            query = r'{"filter": "{\"and\":['+str(counter_name)+r','+start+stop+r'{\"or\":['+str(query_vms)+r']}]}",'+str(orderby)+r','+str(limit)+'}'

        host_file = open("/tmp/vms_query.txt", "w")
        host_file.write(query)
        host_file.close()
        result = subprocess.check_output("curl -X POST -H \'User-Agent: ceilometerclient.openstack.common.apiclient\' -H \'X-Auth-Token: "+str(admin_token)+"\' -H \'Content-Type: application/json\' --data @/tmp/vms_query.txt http://ceilometer:8777/v2/query/samples", shell=True)

        samples.append(json.loads(result))
        #LOG.debug('RESULT: %s', json.loads(result))

    #Composing the vector to return into the HttpResponse
    #----------------------------------------------------------------
    for i in range(len(samples)):
        for j in range(len(samples[i])):
            json_sample = samples[i][j]

            metric_display_name = change_label(json_sample["meter"])
            metric_pos = vm_metrics_list.index(json_sample["meter"])
            metric_range = vm_ranges_list[metric_pos]
            metric_unit = vm_units_list[metric_pos]
            #LOG.debug('DISPLAY NAME: %s, POS: %s', metric_display_name, metric_pos)

            if len(vms_per_host) == 0:
                association = get_appname_and_resourcename(json_sample["resource_id"])
                #LOG.debug('ASSOCIATION: %s', association)

                if len(association) != 0:
                    if metric_display_name == "mem_used":
                        vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": association[0]["application_name"], "vm_name": association[0]["resource_name"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": json_sample["metadata"]["memory_mb"]}]})
                    else:
                        vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": association[0]["application_name"], "vm_name": association[0]["resource_name"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": metric_range}]})

                else:
                    if metric_display_name == "mem_used":
                        vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": "--", "vm_name": "", "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": json_sample["metadata"]["memory_mb"]}]})
                    else:
                        vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": "--", "vm_name": "", "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": metric_range}]})


            else:
                flag_other_vm = True
                for k in range(len(vms_per_host)):
                    if vms_per_host[k]["resource_id"] == json_sample["resource_id"]:
                        flag_other_vm = False
                        flag_insert = True
                        for l in range(len(vms_per_host[k]["metrics"])):
                            if vms_per_host[k]["metrics"][l]["counter_name"] == metric_display_name:
                                flag_insert = False
                                break

                        if flag_insert:
                            if metric_display_name == "mem_used":
                                vms_per_host[k]["metrics"].append({"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": json_sample["metadata"]["memory_mb"]})
                            else:
                                vms_per_host[k]["metrics"].append({"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": metric_range})


                if flag_other_vm:

                    association = get_appname_and_resourcename(json_sample["resource_id"])

                    if len(association) != 0:
                        if metric_display_name == "mem_used":
                            vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": association[0]["application_name"], "vm_name": association[0]["resource_name"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": json_sample["metadata"]["memory_mb"]}]})
                        else:
                            vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": association[0]["application_name"], "vm_name": association[0]["resource_name"], "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": metric_range}]})

                    else:
                        if metric_display_name == "mem_used":
                            vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": "--", "vm_name": "", "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": json_sample["metadata"]["memory_mb"]}]})
                        else:
                            vms_per_host.append({"resource_id": json_sample["resource_id"], "application_name": "--", "vm_name": "", "metrics": [{"counter_name": metric_display_name, "metric_position": metric_pos, "counter_volume":json_sample["volume"], "counter_unit": metric_unit, "range": metric_range}]})


    #Adding vm with empty gauges if no samples of that vm were found on mongo
    for vm in vms_list[0].servers:

        #**************************************************************************************
        if(flag_demo):
            #Demo version
            if vm.get("uuid") in demo_vms_list:
                flag_insert = True
                for item in vms_per_host:
                    if item["resource_id"] == vm.get("uuid"):
                        flag_insert = False
                        break

                if flag_insert:
                    association = get_appname_and_resourcename(vm.get("uuid"))
                    #vms_per_host.append({"resource_id": vm.get("uuid"), "metrics": []})
                    vms_per_host.append({"resource_id": vm.get("uuid"), "application_name": association[0]["application_name"], "vm_name": association[0]["resource_name"], "metrics": []})

        else:
            #Standard version
            flag_insert = True
            for item in vms_per_host:
                if item["resource_id"] == vm.get("uuid"):
                    flag_insert = False
                    break

            if flag_insert:
                association = get_appname_and_resourcename(vm.get("uuid"))
                if len(association) != 0:
                    vms_per_host.append({"resource_id": vm.get("uuid"), "application_name": association[0]["application_name"], "vm_name": association[0]["resource_name"], "metrics": []})
                else:
                    vms_per_host.append({"resource_id": vm.get("uuid"), "application_name": "--", "vm_name": "", "metrics": []})

        #**************************************************************************************
    #LOG.debug('PRE VMS: %s', vms_per_host)


    for vm in vms_per_host:
        if len(vm["metrics"]) != len(vm_metrics_list):
            for i in range(len(vm_metrics_list)):
                flag_insert = True
                for j in range(len(vm["metrics"])):
                    if vm["metrics"][j]["counter_name"] == change_label(vm_metrics_list[i]):
                        flag_insert = False
                        break

                if flag_insert:
                    #LOG.debug('VMS ----> Inserted missing metric: %s for %s', change_label(vm_metrics_list[i]), vm["resource_id"])
                    vm["metrics"].append({"counter_name": change_label(vm_metrics_list[i]), "counter_volume": 0, "counter_unit":  vm_units_list[i], "range": vm_ranges_list[i], "metric_position": i})


    #Order by metric name position
    for vm in vms_per_host:
        sorted_list = sorted(vm["metrics"], key=lambda k: int(k["metric_position"]), reverse = False)
        #LOG.debug('SORTED: %s', sorted_list)
        vm["metrics"] = sorted_list

    vms_per_host = sorted(vms_per_host, key=lambda k: k["vm_name"], reverse = False)
    #LOG.debug('Updated vms gauges values: %s', vms_per_host)
    #----------------------------------------------------------------
    return HttpResponse(json.dumps(vms_per_host),content_type="application/json")
# ------------------------------------------------------------------------------------------------------------------------






# ASSOCIATE VM-APPNAME Management
# ------------------------------------------------------------------------------------------------------------------------
def AssociateVmAppName(request):
    # Retrieve heat_service_id and heat_endpoint from keystone
    keystone = ksclient.Client(
        auth_url=ENV_OS_AUTH_URL,
        username=ENV_OS_USERNAME,
        password=ENV_OS_PASSWORD,
        tenant_name= ENV_OS_TENANT_NAME
    )


    # Retrieve stacks from stack_list
    heat = heat_client.Client(
        ENV_HEAT_OS_API_VERSION,
        endpoint = heat_endpoint,
        token = keystone.auth_token
    )

    global stacks_obj
    stacks_number = 0

    for stack in heat.stacks.list(global_tenant=True):

        if (count < stacks_limit):
        LOG.debug('STACK NAME: %s', stack.stack_name)
        t = threading.Thread(target=getVmsAppNameThread, args=(request, stack, stacks_obj))
        ass_vm_appname_threads.append(t)

        t.setDaemon(True)
        t.start()

    for t in ass_vm_appname_threads: t.join()

    LOG.debug('PROVA %s %s', len(stacks_obj), stacks_number)
    LOG.debug('STACKS AND RESOURCES: %s', stacks_obj)

    return HttpResponse(json.dumps(stacks_obj),content_type="application/json")




def getVmsAppNameThread(request, stack, stacks_obj):
    # LOG.info('\n\n\nStack: %s - %s - Project: %s\n\n', stack.id, stack.stack_name, stack.project)
    global fixed_heat_endpoint
    temp_endpoint = fixed_heat_endpoint.replace('%(tenant_id)s', stack.project )

    keystone_temp = ksclient.Client(
        auth_url=ENV_OS_AUTH_URL,
        username=ENV_OS_USERNAME,
        password=ENV_OS_PASSWORD,
        tenant_id=stack.project
    )

    heat_temp = heat_client.Client(
        ENV_HEAT_OS_API_VERSION,
        endpoint = temp_endpoint,
        token = keystone_temp.auth_token
    )

    resources_obj = []
    for resource in heat_temp.resources.list(stack.id):
        if resource.resource_type == "OS::Nova::Server":
            server = nova.server_get(request, resource.physical_resource_id)
            resources_obj.append({"resource_id": resource.physical_resource_id, "resource_name": server.name})

    template = heat_temp.stacks.template(stack.id)
    template_params = template.get("parameters")


    application_name = "--"
    if ("application_name" in json.dumps(template_params)):
        application_name = template_params["application_name"]["default"]

    LOG.debug('Appending stack resources: %s', stack.stack_name)
    stacks_obj.append({"stack_id": stack.id, "stack_name": stack.stack_name, "application_name": application_name, "resources": resources_obj})
# ------------------------------------------------------------------------------------------------------------------------
