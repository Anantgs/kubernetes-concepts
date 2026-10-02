# Raw Networking Observations

These observations were captured while investigating pod-to-pod networking.
They are retained as source material for a later packet-flow note.

## Pod placement

```text
test-pod-worker    1/1   Running   0   3m46s   10.244.2.8    my-second-cluster-worker    <none>   <none>
test-pod-worker2   1/1   Running   0   4m58s   10.244.1.12   my-second-cluster-worker2   <none>   <none>
```

## Source pod interface

Command:

```bash
kubectl exec -it test-pod-worker -- bash
ip addr
```

Observed interface:

```text
2: eth0@if9: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether be:8a:c1:78:cd:ea brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.244.2.8/24 brd 10.244.2.255 scope global eth0
    inet6 fe80::bc8a:c1ff:fe78:cdea/64 scope link proto kernel_ll
```

## Worker interface paired with the pod

Command:

```bash
docker exec -it my-second-cluster-worker bash
```

Observed interface:

```text
9: vethb1135f87@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
    link/ether da:a1:c1:ba:28:b6 brd ff:ff:ff:ff:ff:ff link-netns cni-3b4672c6-b6d9-683c-5b78-9aa706edb3c2
    inet 10.244.2.1/32 scope global vethb1135f87
    inet6 fe80::d8a1:c1ff:feba:28b6/64 scope link proto kernel_ll
```

The interface indexes show the veth relationship:

```text
POD namespace                     WORKER1 namespace

2: eth0@if9                       9: vethb1135f87@if2
   10.244.2.8                        10.244.2.1
       |                                  |
       +---------- veth pair -------------+
```

## Routes observed on worker1

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

## Cross-node path initially identified

```text
Pod A: 10.244.2.8
        |
        v
worker1 routing
        |
        | 10.244.1.0/24 via 172.18.0.4
        v
worker1 eth0
        |
        v
worker2 eth0
        |
        v
worker2 routing
        |
        v
Pod B: 10.244.1.12
```

## Neighbor entry observed on worker1

```bash
ip neigh show 172.18.0.4
```

```text
172.18.0.4 dev eth0 lladdr 66:0e:a9:11:f8:50 REACHABLE
```

## Node addresses

```text
NAME                              INTERNAL-IP
my-second-cluster-control-plane   172.18.0.3
my-second-cluster-worker          172.18.0.2
my-second-cluster-worker2         172.18.0.4
```
