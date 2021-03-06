# Copyright 2017 PerfKitBenchmarker Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Resource encapsulating provisioned Data Warehouse in the cloud Services.

Classes to wrap specific backend services are in the corresponding provider
directory as a subclass of BaseEdwService.
"""
import json
import os

from perfkitbenchmarker import data
from perfkitbenchmarker import flags
from perfkitbenchmarker import resource


flags.DEFINE_integer('edw_service_cluster_concurrency', 5,
                     'Number of queries to run concurrently on the cluster.')
flags.DEFINE_string('edw_service_cluster_snapshot', None,
                    'If set, the snapshot to restore as cluster.')
flags.DEFINE_string('edw_service_cluster_identifier', None,
                    'If set, the preprovisioned edw cluster.')
flags.DEFINE_string('edw_service_endpoint', None,
                    'If set, the preprovisioned edw cluster endpoint.')
flags.DEFINE_string('edw_service_cluster_db', None,
                    'If set, the db on cluster to use during the benchmark ('
                    'only applicable when using snapshots).')
flags.DEFINE_string('edw_service_cluster_user', None,
                    'If set, the user authorized on cluster (only applicable '
                    'when using snapshots).')
flags.DEFINE_string('edw_service_cluster_password', None,
                    'If set, the password authorized on cluster (only '
                    'applicable when using snapshots).')
flags.DEFINE_string('snowflake_snowsql_config_override_file', None,
                    'The SnowSQL configuration to use.'
                    'https://docs.snowflake.net/manuals/user-guide/snowsql-config.html#snowsql-config-file')  # pylint: disable=line-too-long
flags.DEFINE_string('snowflake_connection', None,
                    'Named Snowflake connection defined in SnowSQL config file.'
                    'https://docs.snowflake.net/manuals/user-guide/snowsql-start.html#using-named-connections')  # pylint: disable=line-too-long

FLAGS = flags.FLAGS


TYPE_2_PROVIDER = dict([('athena', 'aws'), ('redshift', 'aws'),
                        ('spectrum', 'aws'), ('snowflake_aws', 'aws'),
                        ('bigquery', 'gcp'),
                        ('azuresqldatawarehouse', 'azure')])
TYPE_2_MODULE = dict([
    ('athena', 'perfkitbenchmarker.providers.aws.athena'),
    ('redshift', 'perfkitbenchmarker.providers.aws.redshift'),
    ('spectrum', 'perfkitbenchmarker.providers.aws.spectrum'),
    ('snowflake_aws', 'perfkitbenchmarker.providers.aws.snowflake'),
    ('bigquery', 'perfkitbenchmarker.providers.gcp.bigquery'),
    ('azuresqldatawarehouse', 'perfkitbenchmarker.providers.azure.'
     'azure_sql_data_warehouse')
])
DEFAULT_NUMBER_OF_NODES = 1
# The order of stages is important to the successful lifecycle completion.
EDW_SERVICE_LIFECYCLE_STAGES = ['create', 'load', 'query', 'delete']


class EdwService(resource.BaseResource):
  """Object representing a EDW Service."""

  def __init__(self, edw_service_spec):
    """Initialize the edw service object.

    Args:
      edw_service_spec: spec of the edw service.
    """
    # Hand over the actual creation to the resource module, which assumes the
    # resource is pkb managed by default
    is_user_managed = self.IsUserManaged(edw_service_spec)
    # edw_service attribute
    self.cluster_identifier = self.GetClusterIdentifier(edw_service_spec)
    super(EdwService, self).__init__(user_managed=is_user_managed)

    # Provision related attributes
    if edw_service_spec.snapshot:
      self.snapshot = edw_service_spec.snapshot
    else:
      self.snapshot = None

    # Cluster related attributes
    self.concurrency = edw_service_spec.concurrency
    self.node_type = edw_service_spec.node_type

    if edw_service_spec.node_count:
      self.node_count = edw_service_spec.node_count
    else:
      self.node_count = DEFAULT_NUMBER_OF_NODES

    # Interaction related attributes
    if edw_service_spec.endpoint:
      self.endpoint = edw_service_spec.endpoint
    else:
      self.endpoint = ''
    self.db = edw_service_spec.db
    self.user = edw_service_spec.user
    self.password = edw_service_spec.password
    # resource config attribute
    self.spec = edw_service_spec
    # resource workflow management
    self.supports_wait_on_delete = True

  def IsUserManaged(self, edw_service_spec):
    """Indicates if the edw service instance is user managed.

    Args:
      edw_service_spec: spec of the edw service.

    Returns:
      A boolean, set to True if the edw service instance is user managed, False
       otherwise.
    """
    return edw_service_spec.cluster_identifier is not None

  def GetClusterIdentifier(self, edw_service_spec):
    """Returns a string name of the Cluster Identifier.

    Args:
      edw_service_spec: spec of the edw service.

    Returns:
      A string, set to the name of the cluster identifier.
    """
    if self.IsUserManaged(edw_service_spec):
      return edw_service_spec.cluster_identifier
    else:
      return 'pkb-' + FLAGS.run_uri

  def GetMetadata(self):
    """Return a dictionary of the metadata for this edw service."""
    basic_data = {'edw_service_type': self.spec.type,
                  'edw_cluster_identifier': self.cluster_identifier,
                  'edw_cluster_node_type': self.node_type,
                  'edw_cluster_node_count': self.node_count}
    return basic_data

  def RunCommandHelper(self):
    """Returns EDW instance specific launch command components.

    Returns:
      A string with additional command components needed when invoking script
      runner.
    """
    raise NotImplementedError

  def InstallAndAuthenticateRunner(self, vm, benchmark_name):
    """Method to perform installation and authentication of runner utilities.

    The default implementation raises an Error, to ensure client specific
    implementation.

    Args:
      vm: Client vm on which the script will be run.
      benchmark_name: String name of the benchmark, to allow extraction and
        usage of benchmark specific artifacts (certificates, etc.) during client
        vm preparation.
    """
    raise NotImplementedError

  def PrepareClientVm(self, vm, benchmark_name):
    """Prepare phase to install the runtime environment on the client vm.

    Args:
      vm: Client vm on which the script will be run.
      benchmark_name: String name of the benchmark, to allow extraction and
        usage of benchmark specific artifacts (certificates, etc.) during client
        vm preparation.
    """
    vm.Install('pip')
    vm.RemoteCommand('sudo pip install absl-py')
    self.InstallAndAuthenticateRunner(vm, benchmark_name)

  def PushDataDefinitionDataManipulationScripts(self, vm):
    """Method to push the database bootstrap and teardown scripts to the vm.

    Args:
      vm: Client vm on which the scripts will be run.
    """
    raise NotImplementedError

  def PushScriptExecutionFramework(self, vm):
    """Method to push the runner to execute sql scripts on the vm.

    Args:
      vm: Client vm on which the script will be run.
    """
    # Push generic runner
    vm.PushFile(data.ResourcePath(os.path.join('edw', 'script_driver.py')))

  def GenerateLifecycleStageScriptName(self, lifecycle_stage):
    """Computes the default name for script implementing an edw lifecycle stage.

    Args:
      lifecycle_stage: Stage for which the corresponding sql script is desired.

    Returns:
      script name for implementing the argument lifecycle_stage.
    """
    return os.path.basename(
        os.path.normpath('database_%s.sql' % lifecycle_stage))

  def GenerateScriptExecutionCommand(self, script):
    """Method to generate the command for running the sql script on the vm.

    Args:
      script: Script to execute on the client vm.

    Returns:
      base command components to run the sql script on the vm.
    """
    return ['python', 'script_driver.py', '--script={}'.format(script)]

  def GetScriptExecutionResults(self, script_name, client_vm):
    """A function to trigger single/multi script execution and return performance.

    Args:
      script_name: Script to execute on the client vm.
      client_vm: Client vm on which the script will be executed.

    Returns:
      A tuple of script execution performance results.
      - latency of executing the script.
      - reference job_id executed on the edw_service.
    """
    script_execution_command = self.GenerateScriptExecutionCommand(script_name)
    stdout, _ = client_vm.RemoteCommand(script_execution_command)
    all_script_performance = json.loads(stdout)
    script_performance = all_script_performance[script_name]
    return script_performance['execution_time'], script_performance['job_id']

  @classmethod
  def RunScriptOnClientVm(cls, vm, database, script):
    """A function to execute the script on the client vm.

    Args:
      vm: Client vm on which the script will be run.
      database: The database within which the query executes.
      script: Named query to execute (expected to be on the client vm).

    Returns:
      A dictionary with the execution performance results that includes
      execution status and the latency of executing the script.
    """
    raise NotImplementedError

  def GetDatasetLastUpdatedTime(self, dataset=None):
    """Get the formatted last modified timestamp of the dataset."""
    raise NotImplementedError

  def ExtractDataset(self,
                     dest_bucket,
                     dataset=None,
                     tables=None,
                     dest_format='CSV'):
    """Extract all tables in a dataset to object storage.

    Args:
      dest_bucket: Name of the bucket to extract the data to. Should already
        exist.
      dataset: Optional name of the dataset. If none, will be determined by the
        service.
      tables: Optional list of table names to extract. If none, all tables in
        the dataset will be extracted.
      dest_format: Format to extract data in.
    """
    raise NotImplementedError

  def RemoveDataset(self, dataset=None):
    """Removes a dataset.

    Args:
      dataset: Optional name of the dataset. If none, will be determined by the
        service.
    """
    raise NotImplementedError

  def CreateDataset(self, dataset=None, description=None):
    """Creates a new dataset.

    Args:
      dataset: Optional name of the dataset. If none, will be determined by the
        service.
      description: Optional description of the dataset.
    """
    raise NotImplementedError

  def LoadDataset(self, source_bucket, tables, dataset=None):
    """Load all tables in a dataset to a database from object storage.

    Args:
      source_bucket: Name of the bucket to load the data from. Should already
        exist. Each table must have its own subfolder in the bucket named after
        the table, containing one or more csv files that make up the table data.
      tables: List of table names to load.
      dataset: Optional name of the dataset. If none, will be determined by the
        service.
    """
    raise NotImplementedError
