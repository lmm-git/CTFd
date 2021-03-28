import base64
import re
import os
import yaml

from CTFd import utils
from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.utils import FailToCreateError
from kubernetes.utils.create_from_yaml import create_from_dict

def create_k8s_client(token=None) -> client.ApiClient:
    configuration = client.Configuration()
    configuration.host = utils.get_app_config('KUBERNETES_HOST')

    configuration.api_key['authorization'] = token or utils.get_app_config('KUBERNETES_BEARER_TOKEN')
    configuration.api_key_prefix['authorization'] = 'Bearer'

    ssl_ca_cert_path = utils.get_app_config('KUBERNETES_SSL_CA_CERT')
    if not os.path.isabs(ssl_ca_cert_path):
        ssl_ca_cert_path = os.path.join(os.getcwd(), ssl_ca_cert_path)
    if not os.path.exists(ssl_ca_cert_path):
        raise "The KUBERNETES_SSL_CA_CERT at {} does not exist.".format(ssl_ca_cert_path)
    configuration.ssl_ca_cert = ssl_ca_cert_path

    return client.ApiClient(configuration)

k8s_client = create_k8s_client()
core_k8s_client = client.CoreV1Api(k8s_client)
rbac_k8s_client = client.RbacAuthorizationV1Api(k8s_client)

def get_namespace(user_id, challenge_id) -> str:
    fixed_user_id = re.sub(r'[^A-Za-z0-9]+', '', str(user_id))
    return 'ctfd-challenges-{}-{}'.format(fixed_user_id, str(challenge_id))

def challenge_running_state(user_id, challenge_id) -> str:
    namespace = get_namespace(user_id, challenge_id)
    existing_namespaces = core_k8s_client.list_namespace()
    for ns in existing_namespaces.items:
        if ns.metadata.name == namespace:
            if not ns.metadata.deletion_timestamp:
                return "started"
            else:
                return "stopping"
    return "stopped"

def create_service_account_token(namespace) -> str:
    # Create a new Service account
    service_account_body = {"metadata": {"name": "manager"} }
    core_k8s_client.create_namespaced_service_account(namespace, service_account_body)

    # Give a role
    role = client.V1Role(
        metadata={
            "name": "manager-access"
        },
        rules=[
            client.V1PolicyRule(
                api_groups=[""],
                resources=["services"],
                verbs=["list", "get", "watch", "create", "update", "patch", "delete"]
            ),
            client.V1PolicyRule(
                api_groups=["apps"],
                resources=["deployments"],
                verbs=["list", "get", "watch", "create", "update", "patch", "delete"]
            ),
            client.V1PolicyRule(
                api_groups=["rbac.authorization.k8s.io"],
                resources=["roles", "rolebindings"],
                verbs=["list", "get", "watch", "create", "update", "patch", "delete"]
            ),
            client.V1PolicyRule(
                api_groups=["networking.k8s.io"],
                resources=["ingresses", "networkpolicies"],
                verbs=["list", "get", "watch", "create", "update", "patch", "delete"]
            ),
        ]
    )
    rbac_k8s_client.create_namespaced_role(namespace, body=role)

    # Give role to manager
    role_binding = client.V1RoleBinding(
        metadata={
            "name": "manager-manager-access",
        },
        role_ref=client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="Role",
            name="manager-access",
        ),
        subjects=[
            client.V1Subject(
                kind="ServiceAccount",
                name="manager",
                namespace=namespace,
            )
        ]
    )
    rbac_k8s_client.create_namespaced_role_binding(namespace, role_binding)

    # Retrieve token for service account for deploying.
    service_account = core_k8s_client.read_namespaced_service_account("manager", namespace)
    secret = service_account.secrets[0] if service_account.secrets else None
    if not secret:
        raise Exception("Could not retrieve token for service account, no secret was found")
    secret = core_k8s_client.read_namespaced_secret(secret.name, namespace)
    if not secret.data["token"]:
        raise Exception("Could not retrieve token for service account, no token was found")
    token = base64.decodestring(secret.data["token"].encode("ascii")).decode("ascii")
    return token

def start_challenge(user_id, challenge):
    """ Starts a challenge by creating a new namespace for the challenge - user combination """
    # Create the namespace.
    try:
        namespace = get_namespace(user_id, challenge.id)
        new_ns = client.V1Namespace(
            metadata=client.V1ObjectMeta(
                name=namespace
            )
        )
        new_ns = core_k8s_client.create_namespace(new_ns)
    except ApiException as e:
        if e.status == 409:
            raise Exception("Challenge namespace already exists.") from e
        raise e from e

    # Create a new service account and use that token
    # for deploying the new namespace.
    try:
        token = create_service_account_token(namespace)
        k8s_manager_client = create_k8s_client(token)
    except ApiException:
        stop_challenge(user_id, challenge.id)
        raise Exception("Could not create service account")

    # Create the deployments.
    try:
        if not (challenge.kubernetes_description and challenge.kubernetes_description.strip()):
            raise Exception("No deployment specified in challenge.")
        yml_document_all = yaml.safe_load_all(challenge.kubernetes_description.strip())
        yml_document_all = list(yml_document_all)

        failures = []
        k8s_objects = []
        for yml_document in yml_document_all:
            if not yml_document:
                continue
            try:
                created = create_from_dict(k8s_manager_client, yml_document, namespace=namespace)
                k8s_objects.append(created)
            except FailToCreateError as failure:
                failures.extend(failure.api_exceptions)
        if failures:
            raise FailToCreateError(failures)
    except FailToCreateError as e:
        stop_challenge(user_id, challenge.id)
        raise Exception("Challenge could not be created: {}.".format(e)) from e


def stop_challenge(user_id, challenge_id):
    # Deleting the namespace should be enough.
    namespace = get_namespace(user_id, challenge_id)
    try:
        core_k8s_client.delete_namespace(namespace)
    except ApiException as e:
        if e.status == 404:
            raise Exception("Challenge namespace could not be found") from e
        raise e from e
