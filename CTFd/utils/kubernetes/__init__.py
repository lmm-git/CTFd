import re
import os

from CTFd import utils
from kubernetes import client

def create_k8s_client():
    configuration = client.Configuration()
    configuration.host = utils.get_app_config('KUBERNETES_HOST')

    configuration.api_key['authorization'] = utils.get_app_config('KUBERNETES_BEARER_TOKEN')
    configuration.api_key_prefix['authorization'] = 'Bearer'

    ssl_ca_cert_path = utils.get_app_config('KUBERNETES_SSL_CA_CERT')
    if not os.path.isabs(ssl_ca_cert_path):
        ssl_ca_cert_path = os.path.join(os.getcwd(), ssl_ca_cert_path)
    if not os.path.exists(ssl_ca_cert_path):
        raise "The KUBERNETES_SSL_CA_CERT at {} does not exist.".format(ssl_ca_cert_path)
    configuration.ssl_ca_cert = ssl_ca_cert_path

    return client.CoreV1Api(client.ApiClient(configuration))

k8s_client = create_k8s_client()

def get_namespace(user_id, challenge_id):
    fixed_user_id = re.sub(r'[^A-Za-z0-9]+', '', str(user_id))
    return 'ctfd-challenges-{}-{}'.format(fixed_user_id, str(challenge_id))

def is_challenge_running(user_id, challenge_id):
    namespace = get_namespace(user_id, challenge_id)
    existing_namespaces = k8s_client.list_namespace()
    for ns in existing_namespaces.items:
        if ns.metadata.name == namespace:
            return True

    return False

def start_challenge(user_id, challenge_id):
    # Create the namespace.
    namespace = get_namespace(user_id, challenge_id)
    new_ns = client.V1Namespace(
        metadata=client.V1ObjectMeta(
            name=namespace
        )
    )
    k8s_client.create_namespace(new_ns)

def stop_challenge(user_id, challenge_id):
    # Deleting the namespace should be enough.
    namespace = get_namespace(user_id, challenge_id)
    new_ns = client.V1Namespace(
        metadata=client.V1ObjectMeta(
            name=namespace
        )
    )
    k8s_client.delete_namespace(new_ns)
