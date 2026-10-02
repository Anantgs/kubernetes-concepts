# Pod → Service → Pod networking

This lab adds a frontend and backend to your existing Kubernetes cluster. The
frontend serves a web page and calls the backend using `http://backend:80`.
Two backend pods return their pod names and IP addresses so you can identify
which pod answered.

A Service does not initiate requests. The frontend **application inside its
pod** connects to the backend Service. The frontend Service provides an entry
point for callers of the frontend.

## Files

| File | Purpose |
| --- | --- |
| `apps/frontend.py` | Web page and server-side backend call |
| `apps/backend.py` | JSON API that identifies the responding pod |
| `frontend.yaml` | Frontend Deployment and ClusterIP Service |
| `backend.yaml` | Backend Deployment with two replicas and ClusterIP Service |
| `namespace.yaml` | Dedicated `service-networking` namespace |
| `kustomization.yaml` | Packages the Python files into ConfigMaps and combines the manifests |

The apps use Python's standard library and are small learning servers. No image
build or pip install is needed: the Python image runs source mounted from
ConfigMaps. Pod placement is left to the scheduler; inspect the node column to
see whether a request crosses nodes.

## 1. Deploy

Use a terminal where your existing kind cluster, Docker, and `kubectl` work.
The nodes need access to pull `python:3.12-alpine`.

The namespace is already declared in `namespace.yaml`, so do not run
`kubectl create namespace service-networking` separately.

Choose one of the following command blocks based on your current directory.
Do not combine the Kustomize path from one block with the working directory
from the other.

### From the repository root

If `pwd` prints `/mnt/d/Devops-concepts-videos`, run:

```bash
kubectl config current-context
kubectl get nodes
kubectl apply -k pod-to-service-connectivity
kubectl -n service-networking rollout status deployment/backend --timeout=180s
kubectl -n service-networking rollout status deployment/frontend --timeout=180s
kubectl -n service-networking get pods,services -o wide
```

### From inside the lab directory

If `pwd` prints
`/mnt/d/Devops-concepts-videos/pod-to-service-connectivity`, run:

```bash
kubectl config current-context
kubectl get nodes
kubectl apply -k .
kubectl -n service-networking rollout status deployment/backend --timeout=180s
kubectl -n service-networking rollout status deployment/frontend --timeout=180s
kubectl -n service-networking get pods,services -o wide
```

Here, `.` means the current directory containing `kustomization.yaml`. Running
`kubectl apply -k pod-to-service-connectivity` from inside this directory would
incorrectly look for a nested directory named
`pod-to-service-connectivity/pod-to-service-connectivity`.

Check that the context is your intended lab cluster before applying. For the
existing cluster, the kind context is normally `kind-my-second-cluster`.
Expect one ready frontend pod, two ready backend pods, and two ClusterIP
Services. Existing pod-to-pod lab resources are in a different namespace.

Use `apply -k`, because Kustomize generates the required code ConfigMaps.
After editing the application files, repeat the same apply command; changed
ConfigMap names trigger Deployment updates.

## 2. Open the frontend

```bash
kubectl -n service-networking port-forward service/frontend 8080:80
```

Leave that terminal running. Open **http://localhost:8080** in your browser and
click **Call backend**. An illustrative response is:

```json
{
  "frontend_pod": "frontend-<hash>-<suffix>",
  "backend_url": "http://backend:80",
  "backend_response": {
    "message": "Hello from the backend!",
    "backend_pod": "backend-<hash>-<suffix>",
    "backend_pod_ip": "10.244.x.x"
  }
}
```

Click several times to observe the responding backend. Requests can reach
either ready replica; strict alternation is not guaranteed.

The browser calls `/api/backend` on the frontend. The frontend's Python server
then calls `http://backend:80` from inside the cluster. Kubernetes Service names
are resolved inside the cluster, so the browser does not call `backend` directly.

## 3. Understand the connection

For an in-cluster caller, the logical application path is:

```text
Caller pod → frontend Service :80 → frontend pod :8080
                                       |
                                       | new HTTP request to http://backend:80
                                       v
                                backend Service :80
                                       |
                                       v
                                backend pod :8080
```

Services are virtual entry points implemented by the cluster's forwarding
mechanism, not separate proxy pods. The frontend makes a second connection to
the backend, then returns the response to its caller.

For browser access, `kubectl port-forward service/frontend` selects a frontend
pod and tunnels to it. It does **not** test routing through the frontend
ClusterIP. The frontend's outgoing backend call still exercises the backend
Service. Step 5 tests the frontend Service from inside the cluster.

| Setting | Meaning in this lab |
| --- | --- |
| `BACKEND_URL=http://backend:80` | Address used by the frontend application |
| Service `port: 80` | Port callers use on the Service |
| Service `targetPort: http` | Named container port, defined as `8080` |
| Service selector `app: backend` | Matches the backend pods' labels |
| EndpointSlices | Record the Service's backend addresses and readiness |

Both apps run in `service-networking`, so the short name `backend` works.
Across namespaces, use `backend.service-networking`. With the usual
`cluster.local` domain, the full name is
`backend.service-networking.svc.cluster.local`.

See the official [Service DNS documentation](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
and [connecting applications with Services tutorial](https://kubernetes.io/docs/tutorials/services/connect-applications-service/).

## 4. Call the backend directly from the frontend pod

No curl installation is needed; Python is already available in both apps.

Resolve the backend Service name:

```bash
kubectl -n service-networking exec deployment/frontend -- python -c "import socket; print(socket.gethostbyname('backend'))"
kubectl -n service-networking get service backend -o wide
```

The resolved IPv4 address should match the backend ClusterIP in this IPv4 lab.

Send an HTTP request from the frontend pod to that Service:

```bash
kubectl -n service-networking exec deployment/frontend -- python -c "import urllib.request; print(urllib.request.urlopen('http://backend:80', timeout=5).read().decode())"
```

Inspect which backend pod IPs the Service can use:

```bash
kubectl -n service-networking get pods -l app=backend -o wide
kubectl -n service-networking get endpointslices -l kubernetes.io/service-name=backend -o wide
kubectl -n service-networking describe service backend
```

Compare the returned `backend_pod_ip` with the pod and EndpointSlice addresses.
Use HTTP for these checks; pinging a ClusterIP does not test this TCP Service.

## 5. Test both Services from inside the cluster

Use an existing backend pod as a caller of the frontend Service:

```bash
kubectl -n service-networking exec deployment/backend -- python -c "import urllib.request; print(urllib.request.urlopen('http://frontend:80/api/backend', timeout=10).read().decode())"
```

This exercises:

```text
Caller backend pod → frontend Service → frontend pod
                                             |
                                             v
                                      backend Service → selected backend pod
```

The caller happens to be a backend pod to avoid deploying another test app.
It serves the same role as any in-cluster client for this request.

## Troubleshooting

```bash
kubectl -n service-networking get pods -o wide
kubectl -n service-networking describe pods
kubectl -n service-networking logs deployment/frontend
kubectl -n service-networking logs -l app=backend --prefix=true --tail=30
kubectl -n service-networking get endpointslices -l kubernetes.io/service-name=backend -o yaml
```

- **ImagePullBackOff:** inspect pod events and check node access to the image registry.
- **No ready backend endpoints:** check backend pod readiness and the `app: backend` labels.
- **DNS resolution error:** check that the namespace is correct and cluster DNS is working.
- **HTTP 502 from the frontend:** its JSON error describes the failed backend call; check endpoints, ports, and any policies that restrict traffic.
- **Browser cannot connect:** keep port-forward running and check whether local port 8080 is already occupied. Use `8081:80` and browse to port 8081 if needed.

## Cleanup

Stop port-forward with Ctrl+C. To remove this lab and everything in its dedicated
namespace:

```bash
kubectl delete namespace service-networking
```
