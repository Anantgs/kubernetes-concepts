# Test Pod-to-Pod Connectivity Across Workers

## Current path under test

```text
test-pod-worker                              test-pod-worker2
10.244.2.8                                   10.244.1.12
my-second-cluster-worker                     my-second-cluster-worker2
        |                                             ^
        +------------- cross-node ping ---------------+
```

The source and destination pods are on different worker nodes. This makes the
test useful for confirming that the cluster network routes pod traffic across
nodes.

## 1. Ping Pod 2 from Pod 1

Command:

```bash
kubectl exec test-pod-worker -- ping -c 4 10.244.1.12
```

Why we run this command:

- `kubectl exec test-pod-worker` runs a command inside Pod 1.
- `--` separates the `kubectl` options from the command executed in the pod.
- `ping` sends ICMP echo requests to Pod 2's IP address.
- `-c 4` stops the command after four requests instead of running forever.
- `10.244.1.12` is Pod 2's IP address.

Complete observed output:

```text
PING 10.244.1.12 (10.244.1.12) 56(84) bytes of data.
64 bytes from 10.244.1.12: icmp_seq=1 ttl=62 time=0.380 ms
64 bytes from 10.244.1.12: icmp_seq=2 ttl=62 time=0.079 ms
64 bytes from 10.244.1.12: icmp_seq=3 ttl=62 time=0.081 ms
64 bytes from 10.244.1.12: icmp_seq=4 ttl=62 time=0.089 ms

--- 10.244.1.12 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3063ms
rtt min/avg/max/mdev = 0.079/0.157/0.380/0.128 ms
```

## What the output proves

- Pod 1 received a reply for every ICMP request.
- `4 packets transmitted, 4 received` confirms successful communication.
- `0% packet loss` confirms that none of the four test packets were lost.
- `icmp_seq=1` through `icmp_seq=4` identify the four request/reply pairs.
- `time` is the round-trip time for each packet.
- `ttl=62` is the remaining IP time-to-live value when the reply reached the
  source pod.

This test proves that the existing cluster network can carry traffic directly
between pod IPs on different worker nodes. It does not yet explain how the
packet travels between them; the following commands will inspect that path.

## 2. Inspect the source pod's interfaces

Command:

```bash
kubectl exec test-pod-worker -- ip addr
```

Why we run this command:

- `ip addr` lists every network interface and address inside Pod 1's network
  namespace.
- It confirms which interface owns the source pod IP.
- It shows the interface index that links the pod interface to its veth peer
  on the worker node.

Complete observed output:

```text
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host proto kernel_lo 
       valid_lft forever preferred_lft forever
2: eth0@if9: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether be:8a:c1:78:cd:ea brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.244.2.8/24 brd 10.244.2.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::bc8a:c1ff:fe78:cdea/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
```

## What the output shows

- `lo` is the pod's loopback interface. It is used when a process communicates
  with another process inside the same pod through `127.0.0.1`.
- `eth0` is the pod's main network interface.
- `inet 10.244.2.8/24` confirms that `eth0` owns Pod 1's IPv4 address.
- `eth0@if9` means that `eth0`, interface index `2` inside the pod, is connected
  to a peer interface whose index is `9` in the peer network namespace.
- `link/ether be:8a:c1:78:cd:ea` is the MAC address of the pod's `eth0`
  interface.

## 3. Inspect the source pod's routing table

Command:

```bash
kubectl exec test-pod-worker -- ip route
```

Why we run this command:

- The routing table determines where the pod sends an IP packet.
- Pod 2 (`10.244.1.12`) is outside Pod 1's `10.244.2.0/24` subnet, so we need
  to identify Pod 1's next hop.

Complete observed output:

```text
default via 10.244.2.1 dev eth0 
10.244.2.0/24 via 10.244.2.1 dev eth0 src 10.244.2.8 
10.244.2.1 dev eth0 scope link src 10.244.2.8 
```

## How Pod 1 chooses the route

The destination is `10.244.1.12`. It does not match the
`10.244.2.0/24` route, so Pod 1 uses its default route:

```text
default via 10.244.2.1 dev eth0
```

This means Pod 1 sends the packet through `eth0` to the next-hop address
`10.244.2.1`. That next hop is reached through the veth connection between the
pod and worker 1. The worker must then decide how to route the packet toward
Pod 2.

## 4. Inspect worker 1's interfaces

Command:

```bash
docker exec my-second-cluster-worker ip addr
```

Why we run this command:

- A kind node is a Docker container, so `docker exec` runs `ip addr` inside
  worker 1.
- The complete list lets us find interface index `9`, which was referenced by
  the source pod's `eth0@if9` interface.

Complete observed output:

```text
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host proto kernel_lo 
       valid_lft forever preferred_lft forever
2: eth0@if5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether 7a:1e:8a:0f:e3:c2 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 172.18.0.2/16 brd 172.18.255.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fc00:f853:ccd:e793::2/64 scope global nodad 
       valid_lft forever preferred_lft forever
    inet6 fe80::781e:8aff:fe0f:e3c2/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
3: veth9d6abc42@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether 6a:9d:ae:d8:88:8c brd ff:ff:ff:ff:ff:ff link-netns cni-12e80976-c2fa-4526-b465-91f22c3d81e6
    inet 10.244.2.1/32 scope global veth9d6abc42
       valid_lft forever preferred_lft forever
    inet6 fe80::689d:aeff:fed8:888c/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
5: veth40c1f252@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether 76:1b:3e:b6:73:25 brd ff:ff:ff:ff:ff:ff link-netns cni-40af0412-9eae-6ae9-3e33-d0ccecdba7d2
    inet 10.244.2.1/32 scope global veth40c1f252
       valid_lft forever preferred_lft forever
    inet6 fe80::741b:3eff:feb6:7325/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
6: vethd15c632d@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether ee:7c:67:73:37:1b brd ff:ff:ff:ff:ff:ff link-netns cni-6d8494de-5ad3-336c-24a7-ee4e50eea3ca
    inet 10.244.2.1/32 scope global vethd15c632d
       valid_lft forever preferred_lft forever
    inet6 fe80::ec7c:67ff:fe73:371b/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
7: vetha0258712@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether be:8a:bf:15:6a:4f brd ff:ff:ff:ff:ff:ff link-netns cni-b43a1d88-ad95-4cf7-5ee8-12f056e8118d
    inet 10.244.2.1/32 scope global vetha0258712
       valid_lft forever preferred_lft forever
    inet6 fe80::bc8a:bfff:fe15:6a4f/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
8: veth12674f0b@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether c6:74:c8:66:6e:61 brd ff:ff:ff:ff:ff:ff link-netns cni-b4f57e3d-6c93-9e9c-6da7-f3184c4f849b
    inet 10.244.2.1/32 scope global veth12674f0b
       valid_lft forever preferred_lft forever
    inet6 fe80::c474:c8ff:fe66:6e61/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
9: vethb1135f87@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether da:a1:c1:ba:28:b6 brd ff:ff:ff:ff:ff:ff link-netns cni-3b4672c6-b6d9-683c-5b78-9aa706edb3c2
    inet 10.244.2.1/32 scope global vethb1135f87
       valid_lft forever preferred_lft forever
    inet6 fe80::d8a1:c1ff:feba:28b6/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever
```

## Match the two ends of the veth pair

The source pod showed:

```text
2: eth0@if9
```

Worker 1 shows:

```text
9: vethb1135f87@if2
```

The interface indexes point to each other:

```text
Pod network namespace                 Worker 1 network namespace

2: eth0@if9                           9: vethb1135f87@if2
   10.244.2.8                             10.244.2.1/32
        |                                      |
        +-------------- veth pair -------------+
```

The veth pair acts like a virtual cable. A packet leaving Pod 1 through
`eth0` appears on worker 1 through `vethb1135f87`.

## 5. Inspect worker 1's routing table

Command:

```bash
docker exec my-second-cluster-worker ip route
```

Why we run this command:

- After the packet enters worker 1 through the veth interface, worker 1 must
  choose the next hop.
- The routing table shows both the local pod routes and routes to pod subnets
  on the other kind nodes.

Complete observed output:

```text
default via 172.18.0.1 dev eth0 
10.244.0.0/24 via 172.18.0.3 dev eth0 
10.244.1.0/24 via 172.18.0.4 dev eth0 
10.244.2.2 dev veth9d6abc42 scope host 
10.244.2.4 dev veth40c1f252 scope host 
10.244.2.5 dev vethd15c632d scope host 
10.244.2.6 dev vetha0258712 scope host 
10.244.2.7 dev veth12674f0b scope host 
10.244.2.8 dev vethb1135f87 scope host 
172.18.0.0/16 dev eth0 proto kernel scope link src 172.18.0.2 
```

## How worker 1 chooses the route

Pod 2's address, `10.244.1.12`, matches this route:

```text
10.244.1.0/24 via 172.18.0.4 dev eth0
```

Worker 1 therefore:

1. Keeps the destination pod IP as `10.244.1.12`.
2. Selects worker 2 (`172.18.0.4`) as the next hop.
3. Sends the packet through the node's `eth0` interface.

The route below is also important for reply traffic:

```text
10.244.2.8 dev vethb1135f87 scope host
```

It tells worker 1 that packets for Pod 1 must leave through Pod 1's host-side
veth interface.

## 6. Inspect worker 1's neighbor entry for worker 2

Command:

```bash
docker exec my-second-cluster-worker ip neigh show 172.18.0.4
```

Why we run this command:

- The route selected `172.18.0.4` as the next hop.
- Before worker 1 can send an Ethernet frame to that next hop, it needs worker
  2's MAC address.
- `ip neigh` displays the neighbor-table entry learned through ARP for IPv4.

Complete observed output:

```text
172.18.0.4 dev eth0 lladdr 66:0e:a9:11:f8:50 REACHABLE 
```

The fields mean:

- `172.18.0.4` is worker 2's node IP address.
- `dev eth0` is worker 1's outgoing interface.
- `lladdr 66:0e:a9:11:f8:50` is worker 2's MAC address on the kind Docker
  network.
- `REACHABLE` means the kernel currently considers this neighbor entry valid.

ARP resolves the next-hop node IP, `172.18.0.4`. It does not resolve the
remote pod IP, `10.244.1.12`, because that pod is reached through worker 2.

## 7. Inspect worker 2's routing table

Command:

```bash
docker exec my-second-cluster-worker2 ip route
```

Why we run this command:

- Worker 2 receives the packet addressed to Pod 2 (`10.244.1.12`).
- Its routing table must identify the host-side veth interface connected to
  that pod.

Complete observed output:

```text
default via 172.18.0.1 dev eth0 
10.244.0.0/24 via 172.18.0.3 dev eth0 
10.244.1.2 dev veth747fcb0d scope host 
10.244.1.3 dev vetheb0c8835 scope host 
10.244.1.5 dev vethf6dfdd7e scope host 
10.244.1.6 dev veth200cf456 scope host 
10.244.1.7 dev veth30718cda scope host 
10.244.1.8 dev veth58858132 scope host 
10.244.1.9 dev veth46bd0528 scope host 
10.244.1.12 dev veth191a351d scope host 
10.244.2.0/24 via 172.18.0.2 dev eth0 
172.18.0.0/16 dev eth0 proto kernel scope link src 172.18.0.4 
```

Worker 2 finds this direct host route:

```text
10.244.1.12 dev veth191a351d scope host
```

This tells worker 2 to send the packet through `veth191a351d`, the host-side
interface connected to Pod 2.

The return path uses this route toward worker 1:

```text
10.244.2.0/24 via 172.18.0.2 dev eth0
```

## Forward packet path confirmed so far

```text
Pod 1: 10.244.2.8
  |
  | eth0
  v
worker 1: vethb1135f87
  |
  | route 10.244.1.0/24 via 172.18.0.4
  v
worker 1: eth0
  |
  | kind Docker network
  v
worker 2: eth0
  |
  | route 10.244.1.12 dev veth191a351d
  v
worker 2: veth191a351d
  |
  v
Pod 2: 10.244.1.12
```
