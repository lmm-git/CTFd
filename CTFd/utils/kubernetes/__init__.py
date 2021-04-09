import base64
import json
import re
import os
import yaml

from typing import List, Tuple, Dict

from CTFd.utils import get_app_config, get_config
from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.utils import FailToCreateError
from kubernetes.utils.create_from_yaml import create_from_dict
from kubernetes.watch import Watch

def k8s_enabled() -> bool:
    return get_app_config("KUBERNETES_ENABLED")

def create_k8s_client(token=None) -> client.ApiClient:
    configuration = client.Configuration()
    configuration.host = get_app_config('KUBERNETES_HOST')

    configuration.api_key['authorization'] = token or get_app_config('KUBERNETES_BEARER_TOKEN')
    configuration.api_key_prefix['authorization'] = 'Bearer'

    ssl_ca_cert_path = get_app_config('KUBERNETES_SSL_CA_CERT')
    if not ssl_ca_cert_path:
        raise Exception("No certificate file given.")
    if not os.path.isabs(ssl_ca_cert_path):
        ssl_ca_cert_path = os.path.join(os.getcwd(), ssl_ca_cert_path)
    if not os.path.exists(ssl_ca_cert_path):
        raise Exception("The KUBERNETES_SSL_CA_CERT at {} does not exist.".format(ssl_ca_cert_path))
    configuration.ssl_ca_cert = ssl_ca_cert_path

    return client.ApiClient(configuration)

def _user_prefix(user_id):
    fixed_user_id = re.sub(r'[^A-Za-z0-9]+', '', str(user_id))
    return 'ctfd-challenges-{}'.format(fixed_user_id)

def _get_namespace(user_id, challenge_id) -> str:
    return '{}-{}'.format(_user_prefix(user_id), str(challenge_id))

def _check_endpoint_ready(endpoint) -> bool:
    if not endpoint.subsets:
        return False
    # If there are no "not_ready_adresses", all pods are ready
    if all(map(lambda subset: not subset.not_ready_addresses, endpoint.subsets)):
        return True
    return False

def _get_exposed_services(core_k8s_client, namespace, watch=False) -> List[Tuple[str, int, bool]]:
    services = core_k8s_client.list_namespaced_service(namespace, label_selector="ctfd=expose")
    ip_ports = []
    for service in services.items:
        all_endpoints_ready = False
        if watch:
            endpoint_watch = Watch()
            for endpoint_event in endpoint_watch.stream(func=core_k8s_client.list_namespaced_endpoints,
                    namespace=namespace,
                    field_selector="metadata.name={}".format(service.metadata.name)):
                endpoint = endpoint_event["object"]
                if _check_endpoint_ready(endpoint):
                    all_endpoints_ready = True
                    endpoint_watch.stop()
        else:
            endpoints = core_k8s_client.list_namespaced_endpoints(namespace,
                field_selector="metadata.name={}".format(service.metadata.name)
            )
            all_endpoints_ready = all(map(lambda endpoint: _check_endpoint_ready(endpoint), endpoints.items))

        cluster_ip = service.spec.cluster_ip
        for port in service.spec.ports:
            ip_ports.append((cluster_ip, port.port, all_endpoints_ready))

    return ip_ports

def challenge_k8s_state(user_id, challenge_id) -> (str, List[Tuple[str, int]]):
    """Retrieves the current state of the challenge including all exposed IPs and ports"""
    k8s_client = create_k8s_client()
    core_k8s_client = client.CoreV1Api(k8s_client)

    namespace = _get_namespace(user_id, challenge_id)
    existing_namespaces = core_k8s_client.list_namespace()
    for ns in existing_namespaces.items:
        if ns.metadata.name == namespace:
            if ns.status.phase == "Terminating":
                return ("stopping", None)
            elif ns.status.phase == "Active":
                exposed = _get_exposed_services(core_k8s_client, namespace)
                all_services_ready = all(map(lambda tpl: tpl[2], exposed))
                if not all_services_ready:
                    return("starting", None)
                else:
                    ip_ports = list(map(lambda expose: expose[:-1], exposed))
                    return ("started", ip_ports)
            else:
                return ("unknown", None)
    return ("stopped", None)

def challenges_k8s_states(user_id):
    """Retrieves the current state of the challenges including all exposed IPs and ports"""
    prefix = "{}-".format(_user_prefix(user_id))
    k8s_client = create_k8s_client()
    core_k8s_client = client.CoreV1Api(k8s_client)

    ret_val = {}
    existing_namespaces = core_k8s_client.list_namespace()
    for ns in existing_namespaces.items:
        if ns.metadata.name.startswith(prefix):
            challenge_id = ns.metadata.name.replace(prefix, "")
            if ns.status.phase == "Terminating":
                ret_val[challenge_id] = ("stopping", None)
            elif ns.status.phase == "Active":
                exposed = _get_exposed_services(core_k8s_client, ns.metadata.name)
                all_services_ready = all(map(lambda tpl: tpl[2], exposed))
                if not all_services_ready:
                    ret_val[challenge_id] = ("starting", None)
                else:
                    ip_ports = list(map(lambda expose: expose[:-1], exposed))
                    ret_val[challenge_id] = ("started", ip_ports)
            else:
                ret_val[challenge_id] = ("unknown", None)
    return ret_val

def challenge_k8s_state_stream(user_id, challenge_id):
    k8s_client = create_k8s_client()
    core_k8s_client = client.CoreV1Api(k8s_client)

    namespace = _get_namespace(user_id, challenge_id)

    watch = Watch()
    for event in watch.stream(func=core_k8s_client.list_namespace, field_selector="metadata.name={}".format(namespace)):
        the_namespace = event["object"]
        if the_namespace.status.phase == "Active":
            state = {"state": "starting", "exposed": None}
            yield "data: {}\n\n".format(json.dumps(state))
            if the_namespace.metadata.labels and the_namespace.metadata.labels.get("ctfd", None) == "ready":
                # From here on, it's only the starting case.
                exposed_services = _get_exposed_services(core_k8s_client, namespace, watch=True)
                exposed = [{ "host": ip, "port": port } for (ip, port, _) in exposed_services]
                state = {"state": "started", "exposed": exposed}
                yield "data: {}\n\n".format(json.dumps(state))

        elif the_namespace.status.phase == "Terminating":
            state = {"state": "stopping", "exposed": None}
            yield "data: {}\n\n".format(json.dumps(state))
            if event['type'] == 'DELETED':
                state = {"state": "stopped", "exposed": None}
                yield "data: {}\n\n".format(json.dumps(state))
                watch.stop()
                return

def number_running_challenges_for(user_id) -> int:
    """Determines how many challenges are currently running for a specific user"""
    k8s_client = create_k8s_client()
    core_k8s_client = client.CoreV1Api(k8s_client)

    prefix = _user_prefix(user_id)
    namespaces = core_k8s_client.list_namespace()
    return sum([1 if ns.metadata.name.startswith(prefix) else 0 for ns in namespaces.items])

def create_service_account_token(k8s_client, namespace) -> str:
    core_k8s_client = client.CoreV1Api(k8s_client)
    rbac_k8s_client = client.RbacAuthorizationV1Api(k8s_client)

    # Create a new Service account
    service_account_body = {"metadata": {"name": "manager"}}
    core_k8s_client.create_namespaced_service_account(namespace, service_account_body)

    # Give a role
    role = client.V1Role(
        metadata={
            "name": "manager-access"
        },
        rules=[
            client.V1PolicyRule(
                api_groups=[""],
                resources=["services", "pods"],
                verbs=["list", "get", "watch", "create", "update", "patch", "delete"]
            ),
            client.V1PolicyRule(
                api_groups=["apps"],
                resources=["deployments", "replicasets"],
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
    token = base64.decodebytes(secret.data["token"].encode("utf-8")).decode("utf-8")
    return token

def apply_k8s_yml(yaml_content, k8s_manager_client, namespace):
    yml_document_all = yaml.safe_load_all(yaml_content)
    yml_document_all = list(yml_document_all)

    failures = []
    for yml_document in yml_document_all:
        if not yml_document:
            continue
        try:
            created = create_from_dict(k8s_manager_client, yml_document, namespace=namespace)
        except FailToCreateError as failure:
            failures.extend(failure.api_exceptions)
    if failures:
        raise FailToCreateError(failures)

def start_challenge(user_id, challenge):
    """ Starts a challenge by creating a new namespace for the challenge - user combination """
    k8s_client = create_k8s_client()
    core_k8s_client = client.CoreV1Api(k8s_client)

    # Create the namespace.
    try:
        namespace = _get_namespace(user_id, challenge.id)
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
        token = create_service_account_token(k8s_client, namespace)
        k8s_manager_client = create_k8s_client(token)
    except ApiException as exc:
        stop_challenge(user_id, challenge.id)
        raise Exception("Could not create service account: {}".format(exc)) from exc

    # Create default pull secret
    try:
        default_pull_secret = get_config('kubernetes_pull_secret', None)
        if default_pull_secret:
            core_k8s_client.create_namespaced_secret(namespace, {
                'metadata': {
                    'name': 'ctfd-pull-secret',
                },
                'type': 'kubernetes.io/dockerconfigjson',
                'data': {
                    '.dockerconfigjson': base64.encodebytes(default_pull_secret.encode('utf-8')).decode('utf-8')
                }
            })
    except ApiException as exc:
        stop_challenge(user_id, challenge.id)
        print(f"[k8s] Could not create default pull secret: {exc}")
        raise Exception("Could not create default pull secret: <error hidden>") from exc

    # Create flag secret
    try:
        flag_data = {}
        for idx, flag in enumerate(challenge.flags):
            flag_data[f'flag_{idx}'] = base64.encodebytes(str(flag.content).strip().encode('utf-8')).decode(
                'utf-8').strip()

        core_k8s_client.create_namespaced_secret(namespace, {
            'metadata': {
                'name': 'ctfd-flags',
            },
            'type': 'Opaque',
            'data': flag_data,
        })

    except ApiException as exc:
        stop_challenge(user_id, challenge.id)
        #print(f"[k8s] Could not create flag secret: {exc}")
        raise Exception("Could not create challenge flag secret: <error hidden>{}".format(exc)) from exc

    # Create default k8s challenge namespace configurations
    try:
        global_challenge_namespace_config = get_config('kubernetes_default_namespace_config', None)
        if global_challenge_namespace_config:
            apply_k8s_yml(global_challenge_namespace_config, k8s_manager_client, namespace)
    except FailToCreateError as e:
        stop_challenge(user_id, challenge.id)
        raise Exception("Challenge could not be created, failed deploying global configs: {}.".format(e)) from e

    # Create the deployments.
    try:
        if not (challenge.kubernetes_description and challenge.kubernetes_description.strip()):
            raise Exception("No deployment specified in challenge.")

        apply_k8s_yml(challenge.kubernetes_description.strip(), k8s_manager_client, namespace)
    except FailToCreateError as e:
        stop_challenge(user_id, challenge.id)
        raise Exception("Challenge could not be created: {}.".format(e)) from e

    # Mark this namespace as ready (for listeners).
    try:
        core_k8s_client.patch_namespace(namespace, body={"metadata": {"labels": {"ctfd": "ready"}}})
    except ApiException as e:
        stop_challenge(user_id, challenge.id)
        raise Exception("Namespace could not be marked as ready: {}.".format(e)) from e


def stop_challenge(user_id, challenge_id):
    k8s_client = create_k8s_client()
    core_k8s_client = client.CoreV1Api(k8s_client)

    # Deleting the namespace should be enough.
    namespace = _get_namespace(user_id, challenge_id)
    try:
        core_k8s_client.delete_namespace(namespace)
    except ApiException as e:
        if e.status == 404:
            raise Exception("Challenge namespace could not be found") from e
        raise e from e
