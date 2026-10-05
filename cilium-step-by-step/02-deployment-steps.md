# Cilium step-by-step lab

This lab uses a dedicated three-node kind cluster. We deliberately create the
cluster without kind's default CNI so that Cilium can become the cluster's pod
network in the next step.

## The three cluster network ranges

A Kubernetes cluster commonly uses three separate IP address ranges. It is
useful to call them the node, pod, and Service networks, but only the latter
two are configured as Kubernetes cluster subnets. The infrastructure beneath
Kubernetes provides the node network.

| Network | Range in this lab | Provided by | Purpose |
| --- | --- | --- | --- |
| Node network | `172.18.0.0/16` | Docker's kind bridge | Connects the Kubernetes node containers |
| Pod network | `10.244.0.0/16` | Kubernetes Pod CIDRs and Cilium IPAM | Gives ordinary pods routable cluster IP addresses |
| Service network | `10.96.0.0/16` | Kubernetes | Provides stable virtual ClusterIP addresses for Services |

The relationship is:

```text
Underlying node network: 172.18.0.0/16
|-- control-plane node: 172.18.0.7
|-- worker node:        172.18.0.5
`-- worker2 node:       172.18.0.6

Kubernetes pod network: 10.244.0.0/16
|-- control-plane Pod CIDR: 10.244.0.0/24
|-- worker Pod CIDR:        10.244.1.0/24
`-- worker2 Pod CIDR:       10.244.2.0/24

Kubernetes Service network: 10.96.0.0/16
`-- virtual ClusterIP addresses, including kubernetes.default
```

The node network carries traffic between machines (Docker node containers in
kind). Cilium allocates pod IPs from each node's Pod CIDR. In this lab Cilium
uses VXLAN, so cross-node pod packets are encapsulated and carried across the
underlying node network. Service IPs are virtual stable front doors: no network
interface owns a ClusterIP, and forwarding selects one of the Service's pod
endpoints.

Use these commands to inspect all three ranges:

```bash
# Node network and node addresses
docker network inspect kind --format '{{json .IPAM.Config}}'
kubectl get nodes -o wide

# Pod CIDRs assigned to nodes and actual pod addresses
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,NODE-IP:.status.addresses[?(@.type=="InternalIP")].address,POD-CIDR:.spec.podCIDR'
kubectl get ciliumnodes \
  -o custom-columns='NAME:.metadata.name,CILIUM-POD-CIDRS:.spec.ipam.podCIDRs'
kubectl get pods -A -o wide

# Allocated virtual Service addresses
kubectl get services -A -o wide
```

## Step 1: Create a Cilium-ready kind cluster

### Cluster configuration

The cluster is defined in `kind-config.yaml`:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: cilium-lab
networking:
  disableDefaultCNI: true
  podSubnet: 10.244.0.0/16
  serviceSubnet: 10.96.0.0/16
nodes:
  - role: control-plane
  - role: worker
  - role: worker
```

Important details:

- `disableDefaultCNI: true` prevents kindnet from being installed. The nodes
  remain `NotReady` until we install Cilium.
- `podSubnet` reserves `10.244.0.0/16` for pod IP addresses.
- `serviceSubnet` reserves `10.96.0.0/16` for virtual Service IP addresses.
- Repeating `role: worker` creates two uniquely named workers. `worker1` and
  `worker2` are not valid kind roles.
- We have not disabled `kube-proxy`. Initially, Cilium will provide pod
  networking while kube-proxy continues to implement Kubernetes Services.

### Create the cluster

From the lab directory:

```bash
cd /mnt/d/Devops-concepts-videos/cilium-step-by-step
kind create cluster --config kind-config.yaml
```

The successful creation output follows this pattern:

```text
Creating cluster "cilium-lab" ...
 ✓ Ensuring node image (kindest/node:v1.37.0)
 ✓ Preparing nodes
 ✓ Writing configuration
 ✓ Starting control-plane
 ✓ Installing StorageClass
 ✓ Joining worker nodes
Set kubectl context to "kind-cilium-lab"
```

Kind creates Docker containers that behave as Kubernetes nodes and changes the
current kubectl context to `kind-cilium-lab`.

### Check the nodes

```bash
kubectl get node
```

Output captured immediately after cluster creation:

```text
NAME                       STATUS     ROLES           AGE   VERSION
cilium-lab-control-plane   NotReady   control-plane   90s   v1.37.0
cilium-lab-worker          NotReady   <none>          75s   v1.37.0
cilium-lab-worker2         NotReady   <none>          75s   v1.37.0
```

`NotReady` is expected. Kubernetes adds a `node.kubernetes.io/not-ready` taint
because the kubelet cannot find a working CNI configuration. Cilium will supply
that configuration in Step 2.

### Inspect node addresses and runtimes

```bash
kubectl get node -o wide
```

Output:

```text
NAME                       STATUS     ROLES           AGE   VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                       KERNEL-VERSION                              CONTAINER-RUNTIME
cilium-lab-control-plane   NotReady   control-plane   94s   v1.37.0   172.18.0.7    <none>        Debian GNU/Linux 13 (trixie)   6.18.33.2-microsoft-standard-WSL2 (amd64)   containerd://2.3.4
cilium-lab-worker          NotReady   <none>          79s   v1.37.0   172.18.0.5    <none>        Debian GNU/Linux 13 (trixie)   6.18.33.2-microsoft-standard-WSL2 (amd64)   containerd://2.3.4
cilium-lab-worker2         NotReady   <none>          79s   v1.37.0   172.18.0.6    <none>        Debian GNU/Linux 13 (trixie)   6.18.33.2-microsoft-standard-WSL2 (amd64)   containerd://2.3.4
```

The `172.18.0.x` addresses belong to the Docker network used by kind. They are
node IPs, not pod IPs. Pods will later receive addresses from `10.244.0.0/16`.

### Inspect the system pods

```bash
kubectl get po -n kube-system
```

Output:

```text
NAME                                               READY   STATUS    RESTARTS   AGE
coredns-559f6c778d-jh4p5                           0/1     Pending   0          102s
coredns-559f6c778d-zwlfg                           0/1     Pending   0          102s
etcd-cilium-lab-control-plane                      1/1     Running   0          110s
kube-apiserver-cilium-lab-control-plane            1/1     Running   0          110s
kube-controller-manager-cilium-lab-control-plane   1/1     Running   0          110s
kube-proxy-9hwnj                                   1/1     Running   0          102s
kube-proxy-9tcdj                                   1/1     Running   0          98s
kube-proxy-tmvpp                                   1/1     Running   0          98s
kube-scheduler-cilium-lab-control-plane            1/1     Running   0          110s
```

The control-plane components use the host network, so they can run before a CNI
exists. CoreDNS needs a pod network and therefore remains `Pending`. There is
one kube-proxy pod per node because we are not replacing kube-proxy yet.

Pod names, ages, IP addresses, and other dynamic values will differ when these
commands are run again.

## Step 2: Install Cilium as the pod-network CNI

Step 1 intentionally left the nodes `NotReady`: kind did not install its
default CNI. Run the following from the **root shell** used to create the
cluster. Check that the Cilium CLI is available and that kubectl points to
this lab before installing anything:

```bash
cilium version --client
kubectl config current-context
# Expected context: kind-cilium-lab
```

If `cilium` is not installed, install the [Cilium CLI](https://github.com/cilium/cilium-cli#installation)
system-wide first. The command below installs Cilium **into the cluster**;
it does not install the CLI on your machine:

```bash
cilium install --context kind-cilium-lab --version 1.20.2 \
  --set ipam.mode=kubernetes \
  --set routingMode=tunnel \
  --set tunnelProtocol=vxlan \
  --set kubeProxyReplacement=false \
  --wait
```

This pins the Cilium version used in the lab. Kubernetes IPAM gives each
node pod addresses from its assigned Pod CIDR. VXLAN carries cross-node pod
traffic over the kind node network. We retain kube-proxy for Service
forwarding, since Step 1 did not disable it. The CLI deploys the Cilium
components and waits for them to become healthy. These are reproducible lab
settings, not a recovered transcript of the original installation command.

Verify the result:

```bash
cilium status --context kind-cilium-lab --wait
kubectl --context kind-cilium-lab get nodes -o wide
kubectl --context kind-cilium-lab -n kube-system get pods -l k8s-app=cilium -o wide
kubectl --context kind-cilium-lab -n kube-system get pods -l k8s-app=kube-dns
```

Expect three `Ready` nodes, a running Cilium agent on each node, and running
CoreDNS pods. The exact pod names and IP addresses will vary. If the nodes
are still `NotReady`, inspect `cilium status` before continuing.

## Checkpoint after Step 2

With Cilium installed and healthy, all three nodes should be `Ready` and
CoreDNS should have pod addresses from `10.244.0.0/16`.

## Next exercise: place two pods on different nodes

This exercise deliberately uses pod IPs and does not create a Service yet. It
separates direct pod networking from Kubernetes Service forwarding.

The manifest `two-pods.yaml` creates:

```text
client pod
|-- node:     cilium-lab-worker
`-- Pod CIDR: 10.244.1.0/24

server pod
|-- node:     cilium-lab-worker2
|-- Pod CIDR: 10.244.2.0/24
`-- HTTP port: 8080
```

Apply the manifest and wait for both pods:

```bash
kubectl apply -f two-pods.yaml
kubectl -n cilium-demo wait --for=condition=Ready pod --all --timeout=180s
kubectl -n cilium-demo get pods -o wide
```

Expected relationships in the output:

```text
client -> cilium-lab-worker  -> IP from 10.244.1.0/24
server -> cilium-lab-worker2 -> IP from 10.244.2.0/24
```

`nodeSelector` makes the cross-node lab deterministic. Without it, the
scheduler could place both pods on the same node. In the following step, the
client will call the server's pod IP directly so we can observe Cilium's
cross-node datapath without involving a Service.

## Direct cross-node pod-to-pod communication

A Kubernetes Service is not required when the caller already knows the
destination pod IP. Deploy the two pods and confirm that they are on different
nodes:

```bash
kubectl apply -f two-pods.yaml
kubectl -n cilium-demo wait --for=condition=Ready pod --all --timeout=180s
kubectl -n cilium-demo get pods -o wide
```

Read the server's current pod IP and make one direct HTTP request from the
client:

```bash
SERVER_IP=$(kubectl -n cilium-demo get pod server -o jsonpath='{.status.podIP}')
echo "$SERVER_IP"
kubectl -n cilium-demo exec client -- \
  wget -qO- "http://${SERVER_IP}:8080"
```

Expected response:

```text
Hello from the server pod
```

The request does not use DNS, a ClusterIP, or kube-proxy. Cilium sends the
packet from the client's `10.244.1.0/24` network to the server's
`10.244.2.0/24` network. Because the pods are on different nodes and this lab
uses tunnel mode, Cilium carries the original pod packet inside VXLAN across
the Docker node network.

## Cilium endpoints and security identities

For every networked pod, Cilium creates a `CiliumEndpoint` resource. An
endpoint connects the Kubernetes pod to Cilium's view of its IP address, node,
labels, security identity, and datapath state.

```bash
kubectl -n cilium-demo get ciliumendpoints
kubectl -n cilium-demo get ciliumendpoint client -o yaml
kubectl -n cilium-demo get ciliumendpoint server -o yaml
```

Observed endpoints:

```text
NAME     SECURITY IDENTITY   ENDPOINT STATE   IPV4
client   54895               ready            10.244.1.178
server   8157                ready            10.244.2.178
```

A security identity is a numeric representation of a workload's security
labels. The identities differ because the `app` labels differ:

```text
identity 54895 -> k8s:app=client, namespace=cilium-demo, serviceaccount=default
identity 8157  -> k8s:app=server, namespace=cilium-demo, serviceaccount=default
```

Inspect the cluster-scoped identity resources with:

```bash
kubectl get ciliumidentity 54895 -o yaml
kubectl get ciliumidentity 8157 -o yaml
```

Pod IPs can change after recreation, but labels describe the workload's role.
Cilium policies therefore select identities derived from labels instead of
hard-coding ephemeral pod IP addresses.

## Label-based access with CiliumNetworkPolicy

The `allow-client-to-server.yaml` policy selects the endpoint labeled
`app=server` and allows ingress only from endpoints labeled `app=client` on
TCP port `8080`:

```bash
kubectl apply -f allow-client-to-server.yaml
kubectl -n cilium-demo get ciliumnetworkpolicy
kubectl -n cilium-demo describe ciliumnetworkpolicy allow-client-to-server
```

Retest the explicitly allowed request:

```bash
SERVER_IP=$(kubectl -n cilium-demo get pod server -o jsonpath='{.status.podIP}')
kubectl -n cilium-demo exec client -- \
  wget -qO- "http://${SERVER_IP}:8080"
```

Expected response:

```text
Hello from the server pod
```

The `endpointSelector` identifies the protected destination. Adding an ingress
policy changes matching endpoints from default-allow ingress to default-deny
except for traffic allowed by an ingress rule. `fromEndpoints` matches the
source identity by labels, while `toPorts` limits the permission to TCP/8080.
The policy does not depend on either pod's current IP address.

Observed result after applying the policy:

```text
$ kubectl -n cilium-demo get ciliumnetworkpolicy
NAME                     AGE   VALID
allow-client-to-server   12s   True

$ kubectl -n cilium-demo exec client -- wget -qO- http://<server-pod-ip>:8080
Hello from the server pod
```

`VALID=True` confirms that Cilium accepted the policy. The successful HTTP
response proves that the client source identity and destination TCP/8080
matched the allow rule. It does not yet prove that non-matching traffic is
denied; that requires a separate negative test.

## Prove the implicit deny behavior

The `intruder.yaml` pod has `app=intruder`, so its Cilium identity does not
match the policy's required source label `app=client`.

```bash
kubectl apply -f intruder.yaml
kubectl -n cilium-demo wait --for=condition=Ready pod/intruder --timeout=180s
kubectl -n cilium-demo get pods -o wide
kubectl -n cilium-demo get ciliumendpoints
```

Run the disallowed request with a short timeout:

```bash
SERVER_IP=$(kubectl -n cilium-demo get pod server -o jsonpath='{.status.podIP}')
if kubectl -n cilium-demo exec intruder -- \
  wget -T 3 -qO- "http://${SERVER_IP}:8080"; then
  echo "UNEXPECTED: request was allowed"
else
  echo "DENIED as expected"
fi
```

Expected result:

```text
wget: download timed out
command terminated with exit code 1
DENIED as expected
```

Cilium normally drops denied packets instead of returning an application
error, so the caller observes a timeout. The destination, port, and network
path are identical to the successful client request; only the source identity
is different. That isolates identity-based policy enforcement as the reason
for the result.

Observed negative-test result:

```text
$ kubectl -n cilium-demo exec intruder -- wget -T 3 -qO- http://<server-pod-ip>:8080
wget: download timed out
command terminated with exit code 1
```

This is the expected caller-side symptom of Cilium silently dropping traffic
that does not match an allow rule. The monitor exercise below provides the
destination-node evidence that the timeout was specifically a policy drop.

## Observe the policy drop with Cilium monitor

The ingress policy is enforced on the server endpoint, which runs on
`cilium-lab-worker2`. In terminal 1, find that node's Cilium agent and monitor
only drop events:

```bash
CILIUM_POD=$(kubectl -n kube-system get pods \
  -l k8s-app=cilium \
  --field-selector spec.nodeName=cilium-lab-worker2 \
  -o jsonpath='{.items[0].metadata.name}')
echo "$CILIUM_POD"
kubectl -n kube-system exec -it "$CILIUM_POD" -- \
  cilium-dbg monitor --type drop
```

Leave terminal 1 running. In terminal 2, repeat the denied request:

```bash
SERVER_IP=$(kubectl -n cilium-demo get pod server -o jsonpath='{.status.podIP}')
kubectl -n cilium-demo exec intruder -- \
  wget -T 3 -qO- "http://${SERVER_IP}:8080"
```

Terminal 1 should show a policy-denied TCP packet involving the intruder IP,
server IP, and destination port `8080`. The exact text varies by Cilium
version. This proves that the timeout is an intentional eBPF policy drop, not
a missing route or unavailable server. Stop the monitor with Ctrl+C.

## Network troubleshooting tools in client pods

The client and intruder use `nicolaka/netshoot:v0.16` instead of BusyBox. This
image includes tools such as `curl`, `ping`, `dig`, `ip`, `ss`, `traceroute`,
and `tcpdump`. The server remains a small BusyBox HTTP server.

Pod container images are immutable after creation, so recreate only the client
and intruder after changing their manifests:

```bash
kubectl -n cilium-demo delete pod client intruder
kubectl apply -f two-pods.yaml
kubectl apply -f intruder.yaml
kubectl -n cilium-demo wait --for=condition=Ready pod/client pod/intruder \
  --timeout=300s
kubectl -n cilium-demo get pods -o wide
```

Confirm that the tools exist:

```bash
kubectl -n cilium-demo exec client -- curl --version
kubectl -n cilium-demo exec client -- ping -c 1 127.0.0.1
kubectl -n cilium-demo exec client -- \
  dig kubernetes.default.svc.cluster.local
kubectl -n cilium-demo exec intruder -- curl --version
```

The recreated pods may receive new IPs, but their labels remain `app=client`
and `app=intruder`. Cilium derives policy identities from those labels, so the
client remains allowed and the intruder remains denied. Always query the
server's current IP before repeating a request.

## Enable Hubble Relay

Hubble is Cilium's flow-observability system. Each Cilium agent already has a
node-local Hubble component that receives events from the eBPF datapath. Hubble
Relay aggregates those node-local streams so a client can query flows for the
whole cluster through one API.

```text
Cilium eBPF events on each node
              |
              v
Node-local Hubble in each Cilium agent
              |
              v
Hubble Relay: cluster-wide aggregation API
```

Enable Relay without enabling the optional web UI:

```bash
cilium hubble enable --context kind-cilium-lab
cilium status --context kind-cilium-lab --wait
kubectl -n kube-system get pods -l k8s-app=hubble-relay -o wide
```

The `cilium hubble enable` command deploys Relay by default; the UI is enabled
only when `--ui` is specified. A healthy status should change from
`Hubble Relay: disabled` to `Hubble Relay: OK`. Enabling Relay provides the
aggregation service but does not yet install or run a local Hubble CLI; querying
flows is the following exercise.

## Observe cluster flows with the Hubble CLI

Install the Hubble CLI system-wide from the root terminal if it is not already
installed. The next command copies this binary into the lab's `client` pod.

```bash
HUBBLE_VERSION=v1.19.4
HUBBLE_ARCH=amd64
if [ "$(uname -m)" = "aarch64" ]; then HUBBLE_ARCH=arm64; fi

curl -L --fail --remote-name-all \
  "https://github.com/cilium/hubble/releases/download/${HUBBLE_VERSION}/hubble-linux-${HUBBLE_ARCH}.tar.gz" \
  "https://github.com/cilium/hubble/releases/download/${HUBBLE_VERSION}/hubble-linux-${HUBBLE_ARCH}.tar.gz.sha256sum"
sha256sum --check "hubble-linux-${HUBBLE_ARCH}.tar.gz.sha256sum"
tar xzvf "hubble-linux-${HUBBLE_ARCH}.tar.gz" -C /usr/local/bin
hubble version
```

Copy the CLI into the existing `client` pod and query Relay through its
Kubernetes Service:

```bash
kubectl -n cilium-demo cp /usr/local/bin/hubble client:/tmp/hubble
kubectl -n cilium-demo exec client -- \
  /tmp/hubble status --server hubble-relay.kube-system.svc.cluster.local:80
kubectl -n cilium-demo exec client -- \
  /tmp/hubble observe --server hubble-relay.kube-system.svc.cluster.local:80 \
  --namespace cilium-demo --last 10
```

Copy the binary again only if the `client` pod is recreated. The verified status
was `Healthcheck: Ok` and `Connected Nodes: 3/3`. The v1.19.4 CLI prints a
version warning against Relay v1.20.2, but these queries succeeded.

### Read one allowed client-to-server flow

Generate an HTTP request, then filter Hubble to the source and destination pods:

```bash
SERVER_IP=$(kubectl -n cilium-demo get pod server -o jsonpath='{.status.podIP}')
kubectl -n cilium-demo exec client -- curl "http://${SERVER_IP}:8080"
kubectl -n cilium-demo exec client -- \
  /tmp/hubble observe \
  --server hubble-relay.kube-system.svc.cluster.local:80 \
  --from-pod cilium-demo/client \
  --to-pod cilium-demo/server \
  --since 1m --last 10
```

Observed request and representative flow lines:

```text
Hello from the server pod
client:34948 (ID:54895) -> server:8080 (ID:8157) to-overlay FORWARDED (TCP Flags: SYN)
client:34948 (ID:54895) -> server:8080 (ID:8157) policy-verdict:none ALLOWED (TCP Flags: SYN)
client:34948 (ID:54895) -> server:8080 (ID:8157) to-endpoint FORWARDED (TCP Flags: SYN)
client:34948 (ID:54895) -> server:8080 (ID:8157) to-overlay FORWARDED (TCP Flags: ACK, PSH)
client:34948 (ID:54895) -> server:8080 (ID:8157) to-endpoint FORWARDED (TCP Flags: ACK, PSH)
```

`34948` is this request's temporary client TCP port; `8080` is the server port.
The `ID` numbers are Cilium security identities. `to-overlay` means a packet
is sent toward the node's tunnel device, and `to-endpoint` means it is sent
toward the destination pod. Seeing both lines for the same TCP connection is
expected for a request between nodes. `SYN` begins the TCP connection;
`ACK, PSH` appears when data is carried. `FORWARDED` and `ALLOWED` show that
this request was permitted. The `none` text in `policy-verdict:none` is not a
drop verdict and does not by itself identify the matching policy rule.

The `--from-pod` and `--to-pod` filters select only client-to-server packets,
so the server-to-client reply does not appear in this view. See the
[Cilium flow protocol documentation](https://docs.cilium.io/en/stable/_api/v1/flow/README/)
for the observation-point and verdict definitions.

## Open the Hubble UI

The Hubble UI is a separate deployment from Hubble Relay. In this cluster,
`hubble-ui` has two ready containers and its Service is `ClusterIP`, which is
reachable inside Kubernetes but is not exposed as a host port. A request from
the `client` pod returned HTTP `200`.

In a terminal, run and leave this command running:

```bash
kubectl -n kube-system port-forward service/hubble-ui 12000:80
```

Open `http://localhost:12000` in your browser. The UI's HTTP port-forward was
tested from this WSL environment and returned HTTP `200`. If the page does not
open, first check `curl -I http://127.0.0.1:12000` in the same WSL environment
while the port-forward terminal remains open. If the page opens but shows no
flows, investigate the UI backend and its connection to Hubble Relay instead
of the browser-to-UI connection.

### Observe a policy drop in the UI

Keep the UI open with namespace `cilium-demo` selected. Choose the **Dropped**
verdict filter, then send a request from the `intruder` pod to the server's pod
IP:

```bash
SERVER_IP=$(kubectl -n cilium-demo get pod server -o jsonpath='{.status.podIP}')
kubectl -n cilium-demo exec intruder -- \
  curl -v --connect-timeout 3 --max-time 5 "http://${SERVER_IP}:8080"
```

The curl timeout and nonzero exit are expected: the ingress policy on `server`
allows `app=client`, but not `app=intruder`. The UI should show an
`intruder -> server` flow with a **dropped** verdict. A drop is visible in
Hubble even though the HTTP request never reaches the server application.
