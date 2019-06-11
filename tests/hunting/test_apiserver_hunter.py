import requests_mock
import time

from src.modules.hunting.apiserver import AccessApiServer, AccessApiServerWithToken, ServerApiAccess, AccessApiServerActive
from src.modules.hunting.apiserver import ListNamespaces, ListPodsAndNamespaces, ListRoles, ListClusterRoles
from src.modules.hunting.apiserver import ApiServerPassiveHunterFinished
from src.modules.hunting.apiserver import CreateANamespace, DeleteANamespace
from src.modules.discovery.apiserver import ApiServer
from src.core.events.types import Event
from src.core.types import UnauthenticatedAccess, InformationDisclosure
from src.core.events import handler

counter = 0

def test_ApiServerToken():
    global counter 
    counter = 0

    e = ApiServer()
    e.host = "1.2.3.4"
    e.auth_token = "my-secret-token"

    # Test that the pod's token is passed on through the event
    h = AccessApiServerWithToken(e)
    assert h.event.auth_token == "my-secret-token"

    # This test doesn't generate any events
    time.sleep(0.01)
    assert counter == 0

def test_AccessApiServer():
    global counter 
    counter = 0

    e = ApiServer()
    e.host = "mockKubernetes"
    e.port = 443
    e.protocol = "https"

    with requests_mock.Mocker() as m:
        m.get('https://mockKubernetes:443/api', text='{}')
        m.get('https://mockKubernetes:443/api/v1/namespaces', text='{"items":[{"metadata":{"name":"hello"}}]}')
        m.get('https://mockKubernetes:443/api/v1/pods', 
            text='{"items":[{"metadata":{"name":"podA", "namespace":"namespaceA"}}, \
                            {"metadata":{"name":"podB", "namespace":"namespaceB"}}]}')
        m.get('https://mockkubernetes:443/apis/rbac.authorization.k8s.io/v1/roles', status_code=403)
        m.get('https://mockkubernetes:443/apis/rbac.authorization.k8s.io/v1/clusterroles', text='{"items":[]}')

        h = AccessApiServer(e)
        h.execute()

        # We should see events for Server API Access, Namespaces, Pods, and the passive hunter finished
        time.sleep(0.01)
        assert counter == 4

    # Try with an auth token
    counter = 0
    with requests_mock.Mocker() as m:
        # TODO check that these responses reflect what Kubernetes does
        m.get('https://mockKubernetesToken:443/api', text='{}')
        m.get('https://mockKubernetesToken:443/api/v1/namespaces', text='{"items":[{"metadata":{"name":"hello"}}]}')
        m.get('https://mockKubernetesToken:443/api/v1/pods', 
            text='{"items":[{"metadata":{"name":"podA", "namespace":"namespaceA"}}, \
                            {"metadata":{"name":"podB", "namespace":"namespaceB"}}]}')
        m.get('https://mockkubernetesToken:443/apis/rbac.authorization.k8s.io/v1/roles', status_code=403)
        m.get('https://mockkubernetesToken:443/apis/rbac.authorization.k8s.io/v1/clusterroles', 
            text='{"items":[{"metadata":{"name":"my-role"}}]}')

        e.auth_token = "so-secret"
        e.host = "mockKubernetesToken"
        h = AccessApiServerWithToken(e)
        h.execute()

        # We should see the same set of events but with the addition of Cluster Roles
        time.sleep(0.01)
        assert counter == 5

@handler.subscribe(ListNamespaces)
class test_ListNamespaces(object):
    def __init__(self, event):
        print("ListNamespaces")
        assert event.evidence == ['hello']
        if event.host == "mockKubernetesToken":
            assert event.auth_token == "so-secret"
        else:
            assert event.auth_token is None
        global counter
        counter += 1
        

@handler.subscribe(ListPodsAndNamespaces)
class test_ListPodsAndNamespaces(object):
    def __init__(self, event):
        print("ListPodsAndNamespaces")
        assert len(event.evidence) == 2
        for pod in event.evidence:
            if pod["name"] == "podA":
                assert pod["namespace"] == "namespaceA"
            if pod["name"] == "podB":
                assert pod["namespace"] == "namespaceB"                
        if event.host == "mockKubernetesToken":
            assert event.auth_token == "so-secret"
            assert "token" in event.name
            assert "anon" not in event.name
        else:
            assert event.auth_token is None
            assert "token" not in event.name
            assert "anon" in event.name
        global counter
        counter += 1

# Should never see this because the API call in the test returns 403 status code
@handler.subscribe(ListRoles)
class test_ListRoles(object):
    def __init__(self, event):
        print("ListRoles")
        assert 0 
        global counter
        counter += 1

# Should only see this when we have a token because the API call returns an empty list of items
# in the test where we have no token
@handler.subscribe(ListClusterRoles)
class test_ListClusterRoles(object):
    def __init__(self, event):
        print("ListClusterRoles")
        assert event.auth_token == "so-secret"
        global counter
        counter += 1

@handler.subscribe(ServerApiAccess)
class test_ServerApiAccess(object):
    def __init__(self, event):
        print("ServerApiAccess")
        if event.category == UnauthenticatedAccess:
            assert event.auth_token is None
        else:
            assert event.category == InformationDisclosure
            assert event.auth_token == "so-secret"
        global counter
        counter += 1

@handler.subscribe(ApiServerPassiveHunterFinished)
class test_PassiveHunterFinished(object):
    def __init__(self, event):
        print("PassiveHunterFinished")
        assert event.namespaces == ["hello"]
        global counter
        counter += 1

def test_AccessApiServerActive():
    e = ApiServerPassiveHunterFinished(namespaces=["hello-namespace"])
    e.host = "mockKubernetes"
    e.port = 443
    e.protocol = "https"

    with requests_mock.Mocker() as m:
        # TODO more tests here with real responses
        m.post('https://mockKubernetes:443/api/v1/namespaces', text="""
{
  "kind": "Namespace",
  "apiVersion": "v1",
  "metadata": {
    "name": "abcde",
    "selfLink": "/api/v1/namespaces/abcde",
    "uid": "4a7aa47c-39ba-11e9-ab46-08002781145e",
    "resourceVersion": "694180",
    "creationTimestamp": "2019-02-26T11:33:08Z"
  },
  "spec": {
    "finalizers": [
      "kubernetes"
    ]
  },
  "status": {
    "phase": "Active"
  }
}
"""
)
        m.post('https://mockKubernetes:443/api/v1/clusterroles', text='{}')
        m.post('https://mockkubernetes:443/apis/rbac.authorization.k8s.io/v1/clusterroles', text='{}')
        m.post('https://mockkubernetes:443/api/v1/namespaces/hello-namespace/pods', text='{}')
        m.post('https://mockkubernetes:443/apis/rbac.authorization.k8s.io/v1/namespaces/hello-namespace/roles', text='{}')

        m.delete('https://mockKubernetes:443/api/v1/namespaces/abcde', text="""
{
  "kind": "Namespace",
  "apiVersion": "v1",
  "metadata": {
    "name": "abcde",
    "selfLink": "/api/v1/namespaces/abcde",
    "uid": "4a7aa47c-39ba-11e9-ab46-08002781145e",
    "resourceVersion": "694780",
    "creationTimestamp": "2019-02-26T11:33:08Z",
    "deletionTimestamp": "2019-02-26T11:40:58Z"
  },
  "spec": {
    "finalizers": [
      "kubernetes"
    ]
  },
  "status": {
    "phase": "Terminating"
  }
}        
        """)

        h = AccessApiServerActive(e)
        h.execute()

@handler.subscribe(CreateANamespace)
class test_CreateANamespace(object):
    def __init__(self, event):
        assert "abcde" in event.evidence

@handler.subscribe(DeleteANamespace)
class test_DeleteANamespace(object):
    def __init__(self, event):
        assert "2019-02-26" in event.evidence