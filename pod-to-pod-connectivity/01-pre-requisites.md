# Kubernetes Pod-to-Pod Networking Lab: Prerequisites

## Goal

In this lab, we will run one pod on each worker node and test direct
pod-to-pod communication across the nodes.

This lab focuses on the following path:

```text
test-pod-worker                         test-pod-worker2
Pod IP: 10.244.2.8                      Pod IP: 10.244.1.12
Node: my-second-cluster-worker          Node: my-second-cluster-worker2
             \                              /
              \____ kind node network ____/
```

The pod IP addresses above are examples from this cluster. They may change if
the pods are recreated.

## What we need

- Docker
- `kind`
- `kubectl`
- A kind cluster containing one control-plane node and two worker nodes
- The default kind pod network

> Cilium is not installed during this stage. First, we will understand the
> existing pod-to-pod network. Installing and studying Cilium will be the next
> stage.

## 1. Create the kind cluster

Create a kind configuration file named `01-kind-config.yaml` with one control-plane node and two worker nodes:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
  - role: worker
```

Then create the cluster:

```bash
kind create cluster --name my-second-cluster --config 01-kind-config.yaml
```

This creates a Kubernetes cluster with:

- 1 control-plane node
- 2 worker nodes
- default kind networking enabled

To verify the cluster was created successfully, list it:

```bash
kind get clusters
```

Expected output:

```text
my-second-cluster
```

## 2. Verify the cluster

List the kind clusters:

```bash
kind get clusters
```

Why we run this command:

- It confirms that `kind` is installed and working.
- It lists the kind clusters available to the current user.
- It gives us the cluster name required for later kind and Docker commands.

Observed output:

```text
my-second-cluster
```

This confirms that the `my-second-cluster` kind cluster exists and is visible
to the current user.

Verify that all Kubernetes nodes are ready:

```bash
kubectl get nodes -o wide
```

Why we run this command:

- It confirms that every node is available to run workloads.
- It shows which node is the control plane and which nodes are workers.
- The `-o wide` option includes each node's internal IP address. We will use
  these addresses later when tracing traffic between workers.

Observed output:

```text
NAME                              STATUS   ROLES           AGE    VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                       KERNEL-VERSION                              CONTAINER-RUNTIME
my-second-cluster-control-plane   Ready    control-plane   7d4h   v1.37.0   172.18.0.3    <none>        Debian GNU/Linux 13 (trixie)   6.18.33.2-microsoft-standard-WSL2 (amd64)   containerd://2.3.4
my-second-cluster-worker          Ready    <none>          7d4h   v1.37.0   172.18.0.2    <none>        Debian GNU/Linux 13 (trixie)   6.18.33.2-microsoft-standard-WSL2 (amd64)   containerd://2.3.4
my-second-cluster-worker2         Ready    <none>          7d4h   v1.37.0   172.18.0.4    <none>        Debian GNU/Linux 13 (trixie)   6.18.33.2-microsoft-standard-WSL2 (amd64)   containerd://2.3.4
```

All three nodes have the status `Ready`:

- Control plane: `172.18.0.3`
- Worker 1: `172.18.0.2`
- Worker 2: `172.18.0.4`

These are node IP addresses on the kind Docker network. They are different
from the `10.244.x.x` pod IP addresses that we will inspect later.

## 3. Test pod manifests

The test pods are already deployed and running, so we do not need to recreate
them.

- `02-network-worker-pod.yaml` sets `nodeName: my-second-cluster-worker`.
- `03-network-worker2-pod.yaml` sets `nodeName: my-second-cluster-worker2`.

Using `nodeName` ensures that the pods run on different workers. This gives us
a cross-node pod-to-pod network path to investigate.

On a new cluster, the manifests can be deployed with:

```bash
kubectl apply -f 02-network-worker-pod.yaml
kubectl apply -f 03-network-worker2-pod.yaml
```

## 4. Verify pod placement and IP addresses

```bash
kubectl get pods test-pod-worker test-pod-worker2 -o wide
```

Why we run this command:

- Naming the two pods filters out unrelated workloads.
- `STATUS` confirms whether each pod is running.
- `IP` displays the pod IP address used for direct pod-to-pod communication.
- `NODE` confirms that the pods are on different workers.

Observed output:

```text
NAME               READY   STATUS    RESTARTS   AGE    IP            NODE                        NOMINATED NODE   READINESS GATES
test-pod-worker    1/1     Running   0          129m   10.244.2.8    my-second-cluster-worker    <none>           <none>
test-pod-worker2   1/1     Running   0          130m   10.244.1.12   my-second-cluster-worker2   <none>           <none>
```

The result confirms:

- Pod 1 is `10.244.2.8` on worker 1 (`172.18.0.2`).
- Pod 2 is `10.244.1.12` on worker 2 (`172.18.0.4`).
- Both pods are running and ready.
- Traffic between these pod IPs must cross from one worker to the other.

If a pod is not running, inspect it with:

```bash
kubectl describe pod test-pod-worker
kubectl describe pod test-pod-worker2
```

## Result

The lab now has two test pods on different nodes. The next note will test
connectivity between their pod IP addresses and follow the packet from the
source pod to the destination pod.
