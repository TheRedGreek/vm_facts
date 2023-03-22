# vcenter_helper.py

import atexit
from pyVim import connect
from pyVmomi import vim

class VcenterConnection:
    def __init__(self, host, user, pwd, disable_ssl_verification=False):
        self.host = host
        self.user = user
        self.pwd = pwd
        self.disable_ssl_verification = disable_ssl_verification
        self.si = None

    def connect(self):
        """
        Connect to vCenter.
        """
        try:
            if self.disable_ssl_verification:
                service_instance = connect.SmartConnectNoSSL(host=self.host, user=self.user, pwd=self.pwd)
            else:
                service_instance = connect.SmartConnect(host=self.host, user=self.user, pwd=self.pwd)

            atexit.register(connect.Disconnect, service_instance)
            self.si = service_instance
            return service_instance
        except Exception as e:
            raise ConnectionError(f"Unable to connect to vCenter: {e}")

    def disconnect(self):
        """
        Disconnect from vCenter.
        """
        try:
            connect.Disconnect(self.si)
        except Exception as e:
            raise ConnectionError(f"Unable to disconnect from vCenter: {e}")

class VcenterFacts:
    def __init__(self, host, user, pwd, disable_ssl_verification=False):
        self.conn = VcenterConnection(host, user, pwd, disable_ssl_verification)
        self.si = self.conn.connect()

    def get_root(self):
        """
        Retrieve the root folder object.
        """
        content = self.si.content

        return content.rootFolder

    def get_datacenters(self, datacenter_name=None):
        """
        Retrieve a list of datacenter objects in the vCenter.
        If datacenter_name is specified, return a tuple with the matching datacenter and its name.
        """
        content = self.si.content

        if not datacenter_name:
            datacenters = {dc for dc in content.rootFolder.childEntity if isinstance(dc, vim.Datacenter)}
            return datacenters

        datacenters = {dc for dc in content.rootFolder.childEntity if isinstance(dc, vim.Datacenter)}        
        for dc in datacenters:
            if dc.name == datacenter_name:
                return dc

        raise Exception(f"No datacenter found with the name '{datacenter_name}'")
    
    def get_clusters_object(self, datacenter_name, cluster_name):
        """
        Retrieve a list of cluster objects in the vCenter.
        """
        datacenter = self.get_datacenters(datacenter_name)
        for cluster in datacenter.hostFolder.childEntity:
            if isinstance(cluster, vim.ClusterComputeResource) and cluster.name == cluster_name:
                return cluster
        raise Exception(f"No cluster found with the name '{cluster_name}'")


    def get_clusters(self, datacenter_name):
        """
        Retrieve a list of dictionaries, mapping cluster names to datacenter names.
        If datacenters are not specified, retrieves all datacenters.
        """
        clusters = []
        datacenter = self.get_datacenters(datacenter_name)
        for cluster in datacenter.hostFolder.childEntity:
            if isinstance(cluster, vim.ClusterComputeResource):
                total_memory = cluster.summary.totalMemory
                total_cores = cluster.summary.numCpuCores
                clusters.append({
                    'name': cluster.name,
                    'datacenter': datacenter.name,
                    'total_memory': total_memory,
                    'total_cores': total_cores,
                    })

        return clusters

    def get_datastore_clusters(self, datacenter_name):
        """
        Retrieve a list of dictionaries representing all available datastore clusters,
        each with its name, free space, and total space.
        If datacenters are not specified, retrieves all datacenters.
        """
        datacenter = self.get_datacenters(datacenter_name)
        datastore_clusters = []
        for cluster in datacenter.datastoreFolder.childEntity:
            if isinstance(cluster, vim.StoragePod):
                free_space = cluster.summary.freeSpace
                total_space = cluster.summary.capacity
                datastore_clusters.append({
                    'name': cluster.name,
                    'datacenter': datacenter.name,
                    'free_space': free_space,
                    'total_space': total_space,
                })

        return datastore_clusters
    
    def get_datastore_with_most_space_in_cluster(self, datastore_cluster_name):
        """
        Find the datastore with the most available storage in the specified datastore cluster.
        If a datacenter is specified, only consider datastores in that datacenter.
        """
        datacenters = self.get_datacenters()
        datastore_cluster = None

        for datacenter in datacenters:
            for cluster in datacenter.datastoreFolder.childEntity:
                if isinstance(cluster, vim.StoragePod) and cluster.name == datastore_cluster_name:
                    datastore_cluster = cluster
                    break
            if datastore_cluster:
                break

        if not datastore_cluster:
            raise Exception(f"No datastore cluster found with the name '{datastore_cluster_name}'")

        datastores = datastore_cluster.childEntity

        if not datastores:
            raise Exception("No datastores found in the specified datastore cluster")

        # Find the datastore with the most free space
        max_datastore = max(datastores, key=lambda x: x.summary.freeSpace)

        return {
            'name': max_datastore.name,
            'datastore_cluster': datastore_cluster_name,
            'free_space': max_datastore.summary.freeSpace,
            'total_space': max_datastore.summary.capacity
        }


    def get_networks(self, datacenter_name, clusters=None):
        """
        Retrieve a list of dictionaries, mapping network names to datacenter and cluster names.
        If datacenters or clusters are not specified, retrieves all datacenters or clusters.
        """
        datacenter = self.get_datacenters(datacenter_name)

        networks = []
        dc_clusters = [self.get_clusters_object(datacenter_name, cluster)]
        for cluster in dc_clusters:
            if not isinstance(cluster, vim.ClusterComputeResource):
                continue
            if not cluster.network:
                continue
            for network in cluster.network:
                networks.append({
                    'name': network.name,
                    'datacenter': datacenter_name,
                    'cluster': cluster.name,
                })

        return networks
    
    def find_folder_and_path(self, folder_name):
        """
        Find a folder and its path in the vCenter inventory.
        Return a dictionary with the folder object and its path.
        If the folder is not found, return None.
        """
        root_folder = self.get_root()
        if not isinstance(root_folder, vim.Folder):
            return None

        folder_name_lower = folder_name.lower()
        for item in root_folder.childEntity:
            if isinstance(item, vim.Folder):
                if item.name.lower() == folder_name_lower:
                    return {'folder': item, 'path': root_folder.name}
                else:
                    result = find_folder_and_path(folder_name, item)
                    if result:
                        folder_dict = result
                        folder_dict['path'] = f"{root_folder.name}/{folder_dict['path']}"
                        return folder_dict

        return None
    
    def get_template(self, template_name):
        """
        Retrieve the VM template object with the given name.
        """
        root_folder = self.get_root()

        # Loop through child entities of the root folder
        template_objs = []
        for child in root_folder.childEntity:
            if isinstance(child, vim.VirtualMachine) and child.config.template and child.summary.config.name.lower() == template_name.lower():
                template_objs.append(child)

        if not template_objs:
            # Clear the template_objs list to fetch all templates
            template_objs.clear()
            
            # Loop through child entities of the root folder
            for child in root_folder.childEntity:
                if isinstance(child, vim.VirtualMachine) and child.config.template:
                    template_objs.append(child)
                    
            all_templates = [child.summary.config.name for child in template_objs]
            raise Exception(f"No template found with the name '{template_name}'. Available templates: {', '.join(all_templates)}")

        return template_objs